from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from vm_agent_server.src.authz import get_highest_role
from vm_agent_server.src.settings.models import (
    AzureSsoPatch,
    IdentityGroupRoleMapping,
    IdentitySettings,
    IdentitySettingsPatch,
    MICROSOFT_SSO_REDIRECT_PATH,
)
from vm_agent_server.src.users.access_policy import evaluate_identity_access
from vm_agent_server.src.users.helpers import build_avatar_initials, clean_str, decode_unverified_jwt, format_http_error, now_ts
from vm_agent_server.src.users.models import PendingOidcLogin, PublicAuthConfig, RecentUserIdentity, UserIdentity, UserSession
from vm_agent_server.src.users.recent_users_db import RecentUsersDB


LOCAL_ADMIN_USERNAME_ENV = "VM_AGENT_LOCAL_ADMIN_USERNAME"
LOCAL_ADMIN_PASSWORD_ENV = "VM_AGENT_LOCAL_ADMIN_PASSWORD"
def _build_pkce_verifier() -> str:
    return secrets.token_urlsafe(64)


def _build_pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
class UserService:
    def __init__(self, recent_users_db: RecentUsersDB | None = None):
        self._sessions: dict[str, UserSession] = {}
        self._pending_oidc: dict[str, PendingOidcLogin] = {}
        self._oidc_metadata_cache: dict[str, object] | None = None
        self._oidc_metadata_fetched_at = 0
        self._recent_users_db = recent_users_db

    def get_public_auth_config(self, identity: IdentitySettings) -> PublicAuthConfig:
        azure = identity.azure
        azure_configured = bool(clean_str(azure.tenant_id) and clean_str(azure.client_id))
        azure_active = identity.provider == "azure_entra" and bool(azure.activated_at)
        return PublicAuthConfig(
            provider=identity.provider,
            provider_locked=identity.provider_locked,
            local_bootstrap_available=self.local_bootstrap_available(identity),
            azure_configured=azure_configured,
            azure_active=azure_active,
            microsoft_login_available=azure_active and azure_configured,
            client_id_configured=bool(clean_str(azure.client_id)),
            tenant_id_configured=bool(clean_str(azure.tenant_id)),
            client_secret_configured=bool(clean_str(azure.client_secret)),
            group_mapping_count=len(azure.group_role_mappings),
        )

    def build_settings_response_identity(self, identity: IdentitySettings) -> dict[str, object]:
        azure = identity.azure
        return {
            "provider": identity.provider,
            "provider_locked": identity.provider_locked,
            "session_ttl_seconds": identity.session_ttl_seconds,
            "local_bootstrap_available": self.local_bootstrap_available(identity),
            "access": {
                "mode": identity.access.mode,
                "allow_mapped_groups": identity.access.allow_mapped_groups,
                "allowed_user_subjects": list(identity.access.allowed_user_subjects),
                "allowed_group_ids": list(identity.access.allowed_group_ids),
            },
            "azure": {
                "tenant_id": azure.tenant_id,
                "client_id": azure.client_id,
                "authority_url": azure.authority_url,
                "redirect_path": MICROSOFT_SSO_REDIRECT_PATH,
                "scopes": list(azure.scopes),
                "group_role_mappings": [mapping.model_dump(mode="json") for mapping in azure.group_role_mappings],
                "client_secret_configured": bool(clean_str(azure.client_secret)),
                "activated_at": azure.activated_at,
                "active": identity.provider == "azure_entra" and bool(azure.activated_at),
            },
        }

    def local_bootstrap_available(self, identity: IdentitySettings) -> bool:
        if identity.provider == "azure_entra" and identity.provider_locked:
            return False
        return bool(clean_str(os.getenv(LOCAL_ADMIN_USERNAME_ENV)) and clean_str(os.getenv(LOCAL_ADMIN_PASSWORD_ENV)))

    def prepare_identity_patch(self, current: IdentitySettings, requested: IdentitySettingsPatch) -> IdentitySettingsPatch:
        if requested.session_ttl_seconds is not None and requested.session_ttl_seconds < 900:
            raise ValueError("Session TTL must be at least 900 seconds")

        access_patch = requested.access
        if access_patch:
            if access_patch.allowed_user_subjects is not None:
                access_patch.allowed_user_subjects = [str(item).strip() for item in access_patch.allowed_user_subjects if str(item).strip()]
            if access_patch.allowed_group_ids is not None:
                access_patch.allowed_group_ids = [str(item).strip() for item in access_patch.allowed_group_ids if str(item).strip()]

        azure_patch = requested.azure
        if not azure_patch:
            return requested

        if current.provider_locked and current.provider == "azure_entra":
            immutable_changes = []
            if azure_patch.tenant_id is not None and azure_patch.tenant_id != current.azure.tenant_id:
                immutable_changes.append("tenant_id")
            if azure_patch.client_id is not None and azure_patch.client_id != current.azure.client_id:
                immutable_changes.append("client_id")
            if azure_patch.authority_url is not None and azure_patch.authority_url != current.azure.authority_url:
                immutable_changes.append("authority_url")
            if immutable_changes:
                raise ValueError(f"Azure SSO provider is locked. Immutable fields cannot change: {', '.join(immutable_changes)}")

        if azure_patch.activate:
            tenant_id = clean_str(azure_patch.tenant_id) or current.azure.tenant_id
            client_id = clean_str(azure_patch.client_id) or current.azure.client_id
            if not tenant_id or not client_id:
                raise ValueError("Azure SSO activation requires tenant_id and client_id")

        return requested

    def finalize_identity_settings(self, current: IdentitySettings, requested: IdentitySettings) -> IdentitySettings:
        if requested.azure.activated_at and requested.provider != "azure_entra":
            requested.provider = "azure_entra"
        return requested

    def build_identity_payload_after_update(self, current: IdentitySettings, requested_patch: IdentitySettingsPatch) -> dict[str, object]:
        payload = current.model_dump(mode="python")
        patch_payload = requested_patch.model_dump(exclude_none=True)
        if not patch_payload:
            return payload

        if requested_patch.azure and requested_patch.azure.group_role_mappings is not None:
            mappings: list[IdentityGroupRoleMapping] = []
            for requested_mapping in requested_patch.azure.group_role_mappings:
                mapping_payload = requested_mapping.model_dump(exclude_none=True)
                mappings.append(IdentityGroupRoleMapping.model_validate(mapping_payload))
            patch_payload.setdefault("azure", {})["group_role_mappings"] = [mapping.model_dump(mode="python") for mapping in mappings]

        if "azure" in patch_payload:
            patch_payload["azure"].pop("redirect_path", None)
            patch_payload["azure"]["redirect_path"] = MICROSOFT_SSO_REDIRECT_PATH

        azure_patch = requested_patch.azure
        if azure_patch and azure_patch.activate:
            patch_payload.setdefault("azure", {})["activated_at"] = current.azure.activated_at or now_ts()
            payload["provider"] = "azure_entra"
            payload["provider_locked"] = True

        payload.update({key: value for key, value in patch_payload.items() if key not in {"access", "azure"}})
        if "access" in patch_payload:
            access_payload = dict(payload.get("access") or {})
            access_payload.update(patch_payload["access"])
            payload["access"] = access_payload
        if "azure" in patch_payload:
            azure_payload = dict(payload.get("azure") or {})
            azure_payload.update({key: value for key, value in patch_payload["azure"].items() if key != "activate"})
            payload["azure"] = azure_payload
        return payload

    def authenticate_local_admin(self, identity: IdentitySettings, username: str, password: str) -> UserIdentity | None:
        if not self.local_bootstrap_available(identity):
            return None

        expected_username = clean_str(os.getenv(LOCAL_ADMIN_USERNAME_ENV))
        expected_password = clean_str(os.getenv(LOCAL_ADMIN_PASSWORD_ENV))
        if username != expected_username or password != expected_password:
            return None

        return UserIdentity(
            subject=f"local:{expected_username}",
            username=expected_username,
            display_name="Local Admin",
            avatar_initials=build_avatar_initials("Local Admin", expected_username),
            auth_provider="local_bootstrap",
            roles=["admin"],
            claims={},
        )

    def create_session(self, identity_settings: IdentitySettings, user: UserIdentity) -> UserSession:
        self._purge_expired_sessions()
        now = now_ts()
        ttl = max(900, int(identity_settings.session_ttl_seconds or 43200))
        access_token = secrets.token_urlsafe(48)
        session = UserSession(
            access_token=access_token,
            user=user,
            created_at=now,
            expires_at=now + ttl,
            last_seen_at=now,
        )
        self._sessions[access_token] = session
        if self._recent_users_db is not None:
            try:
                asyncio.get_running_loop().create_task(self._recent_users_db.record_identity(user))
            except RuntimeError:
                pass
        return session

    def get_session(self, access_token: str | None) -> UserSession | None:
        self._purge_expired_sessions()
        if not access_token:
            return None
        session = self._sessions.get(access_token)
        if not session:
            return None
        session.last_seen_at = now_ts()
        return session

    def revoke_session(self, access_token: str | None) -> None:
        if not access_token:
            return
        self._sessions.pop(access_token, None)

    def list_active_identities(self) -> list[UserIdentity]:
        self._purge_expired_sessions()
        identities: list[UserIdentity] = []
        seen_subjects: set[str] = set()
        for session in self._sessions.values():
            subject = clean_str(session.user.subject)
            if not subject or subject in seen_subjects:
                continue
            seen_subjects.add(subject)
            identities.append(session.user)
        return identities

    async def list_recent_identities(self, limit: int = 100) -> list[RecentUserIdentity]:
        if self._recent_users_db is None:
            return []
        return await self._recent_users_db.list_recent(limit)

    def begin_microsoft_login(self, identity: IdentitySettings, public_base_url: str, return_to: str) -> str:
        metadata = self._get_oidc_metadata(identity)
        authorize_endpoint = clean_str(str(metadata.get("authorization_endpoint") or ""))
        if not authorize_endpoint:
            raise RuntimeError("Microsoft authorization endpoint is not configured")

        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        code_verifier = _build_pkce_verifier()
        redirect_uri = f"{public_base_url.rstrip('/')}{MICROSOFT_SSO_REDIRECT_PATH}"
        self._pending_oidc[state] = PendingOidcLogin(
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            return_to=return_to,
            expires_at=now_ts() + 600,
        )

        scopes = list(identity.azure.scopes or ["openid", "profile", "email"])
        if "openid" not in scopes:
            scopes.insert(0, "openid")

        query = urlencode(
            {
                "client_id": identity.azure.client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "response_mode": "query",
                "scope": " ".join(scopes),
                "state": state,
                "nonce": nonce,
                "code_challenge": _build_pkce_challenge(code_verifier),
                "code_challenge_method": "S256",
            }
        )
        return f"{authorize_endpoint}?{query}"

    def finish_microsoft_login(self, identity: IdentitySettings, state: str, code: str) -> tuple[UserSession, str]:
        self._purge_expired_pending_oidc()
        pending = self._pending_oidc.pop(state, None)
        if not pending:
            raise ValueError("Invalid or expired Microsoft login state")

        token_payload = self._exchange_authorization_code(identity, code, pending)
        id_token = clean_str(str(token_payload.get("id_token") or ""))
        if not id_token:
            raise RuntimeError("Microsoft token response did not include an id_token")
        claims = decode_unverified_jwt(id_token)
        if clean_str(str(claims.get("nonce") or "")) != pending.nonce:
            raise ValueError("Microsoft login nonce mismatch")

        user = self._build_user_from_claims(identity, claims)
        session = self.create_session(identity, user)
        return session, pending.return_to

    def _build_user_from_claims(self, identity: IdentitySettings, claims: dict[str, object]) -> UserIdentity:
        now = now_ts()
        exp = int(claims.get("exp") or 0)
        if exp and exp < now:
            raise ValueError("Microsoft id_token is expired")

        audience = claims.get("aud")
        allowed_audiences = {identity.azure.client_id}
        if isinstance(audience, str):
            if audience not in allowed_audiences:
                raise ValueError("Microsoft id_token audience mismatch")
        elif isinstance(audience, list):
            if not any(isinstance(item, str) and item in allowed_audiences for item in audience):
                raise ValueError("Microsoft id_token audience mismatch")

        issuer = clean_str(str(claims.get("iss") or ""))
        tenant_id = identity.azure.tenant_id
        if tenant_id and tenant_id not in issuer:
            raise ValueError("Microsoft id_token issuer mismatch")

        subject = clean_str(str(claims.get("sub") or claims.get("oid") or ""))
        if not subject:
            raise ValueError("Microsoft id_token is missing subject")

        username = clean_str(str(claims.get("preferred_username") or claims.get("email") or claims.get("upn") or subject))
        display_name = clean_str(str(claims.get("name") or username))
        email = clean_str(str(claims.get("email") or claims.get("preferred_username") or ""))
        avatar_url = clean_str(str(claims.get("picture") or ""))
        group_ids = [str(item).strip() for item in (claims.get("groups") or []) if str(item).strip()] if isinstance(claims.get("groups"), list) else []
        role_names = [str(item).strip() for item in (claims.get("roles") or []) if str(item).strip()] if isinstance(claims.get("roles"), list) else []

        mapped_roles: set[str] = set(role_names)
        matched_mapping_ids: set[str] = set()
        mapped_group_names: list[str] = []
        for mapping in identity.azure.group_role_mappings:
            group_object_id = clean_str(mapping.group_object_id)
            if group_object_id and group_object_id in group_ids:
                matched_mapping_ids.add(group_object_id)
                mapped_roles.update(role for role in mapping.app_roles if role)
                if mapping.group_name:
                    mapped_group_names.append(mapping.group_name)

        subject_key = f"microsoft:{subject}"
        access_decision = evaluate_identity_access(identity, subject_key, group_ids, matched_mapping_ids)
        if not access_decision.allow_login:
            raise ValueError("This user is not authorized for this application")

        effective_role = get_highest_role(mapped_roles)

        return UserIdentity(
            subject=f"microsoft:{subject}",
            username=username,
            display_name=display_name,
            email=email,
            avatar_url=avatar_url,
            avatar_initials=build_avatar_initials(display_name, username, email),
            auth_provider="azure_entra",
            roles=[effective_role],
            agent_visibility=access_decision.agent_visibility,
            group_ids=group_ids,
            group_names=sorted({name for name in mapped_group_names if name}),
            claims={
                "oid": claims.get("oid"),
                "tid": claims.get("tid"),
                "preferred_username": claims.get("preferred_username"),
                "upn": claims.get("upn"),
                "email": claims.get("email"),
                "picture": claims.get("picture"),
                "roles": role_names,
                "has_groups_overage": bool(claims.get("_claim_names") or claims.get("hasgroups")),
            },
        )

    def _exchange_authorization_code(self, identity: IdentitySettings, code: str, pending: PendingOidcLogin) -> dict[str, object]:
        metadata = self._get_oidc_metadata(identity)
        token_endpoint = clean_str(str(metadata.get("token_endpoint") or ""))
        if not token_endpoint:
            raise RuntimeError("Microsoft token endpoint is not configured")

        form = {
            "grant_type": "authorization_code",
            "client_id": identity.azure.client_id,
            "code": code,
            "redirect_uri": pending.redirect_uri,
            "code_verifier": pending.code_verifier,
        }
        if clean_str(identity.azure.client_secret):
            form["client_secret"] = identity.azure.client_secret

        request = Request(
            token_endpoint,
            data=urlencode(form).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise RuntimeError(format_http_error("Microsoft token exchange", "request", error)) from error
        except URLError as error:
            raise RuntimeError(f"Microsoft token exchange request failed: {error.reason}") from error
        if not isinstance(payload, dict):
            raise RuntimeError("Microsoft token response is invalid")
        return payload

    def _get_oidc_metadata(self, identity: IdentitySettings) -> dict[str, object]:
        now = now_ts()
        if self._oidc_metadata_cache and now - self._oidc_metadata_fetched_at < 3600:
            return self._oidc_metadata_cache

        authority_url = clean_str(identity.azure.authority_url)
        if not authority_url:
            tenant_id = clean_str(identity.azure.tenant_id)
            if not tenant_id:
                raise RuntimeError("Azure SSO tenant_id is not configured")
            authority_url = f"https://login.microsoftonline.com/{tenant_id}/v2.0"

        discovery_url = f"{authority_url.rstrip('/')}/.well-known/openid-configuration"
        request = Request(discovery_url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise RuntimeError(format_http_error("OIDC discovery", "request", error)) from error
        except URLError as error:
            raise RuntimeError(f"OIDC discovery request failed: {error.reason}") from error
        if not isinstance(payload, dict):
            raise RuntimeError("OIDC discovery response is invalid")
        self._oidc_metadata_cache = payload
        self._oidc_metadata_fetched_at = now
        return payload

    def _purge_expired_sessions(self) -> None:
        now = now_ts()
        expired = [token for token, session in self._sessions.items() if session.expires_at <= now]
        for token in expired:
            self._sessions.pop(token, None)

    def _purge_expired_pending_oidc(self) -> None:
        now = now_ts()
        expired = [state for state, pending in self._pending_oidc.items() if pending.expires_at <= now]
        for state in expired:
            self._pending_oidc.pop(state, None)