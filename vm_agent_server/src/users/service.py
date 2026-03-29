from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
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
from vm_agent_server.src.users.models import PendingOidcLogin, PublicAuthConfig, UserIdentity, UserSession


LOCAL_ADMIN_USERNAME_ENV = "VM_AGENT_LOCAL_ADMIN_USERNAME"
LOCAL_ADMIN_PASSWORD_ENV = "VM_AGENT_LOCAL_ADMIN_PASSWORD"


def _now() -> int:
    return int(time.time())


def _clean(value: str | None) -> str:
    return str(value or "").strip()


def _decode_unverified_jwt(token: str) -> dict[str, object]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    decoded = base64.urlsafe_b64decode(payload + padding)
    parsed = json.loads(decoded.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("Invalid JWT payload")
    return parsed


def _build_pkce_verifier() -> str:
    return secrets.token_urlsafe(64)


def _build_pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def _truncate_message(value: str, limit: int = 500) -> str:
    cleaned = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit - 3]}..."


def _read_error_payload(error: HTTPError) -> dict[str, object]:
    try:
        raw_payload = error.read()
    except Exception:
        return {}

    if not raw_payload:
        return {}

    decoded = raw_payload.decode("utf-8", errors="replace").strip()
    if not decoded:
        return {}

    try:
        parsed = json.loads(decoded)
    except Exception:
        return {"raw": decoded}

    return parsed if isinstance(parsed, dict) else {"raw": decoded}


def _format_http_error(provider_label: str, action: str, error: HTTPError) -> str:
    payload = _read_error_payload(error)
    oauth_error = _clean(str(payload.get("error") or ""))
    oauth_description = _truncate_message(str(payload.get("error_description") or payload.get("error_summary") or payload.get("message") or payload.get("raw") or ""))
    error_codes = payload.get("error_codes")

    message = f"{provider_label} {action} failed"
    if oauth_error:
        message = f"{message}: {oauth_error}"
    else:
        message = f"{message} with HTTP {getattr(error, 'code', 'unknown')}"

    if oauth_description:
        message = f"{message} - {oauth_description}"

    if isinstance(error_codes, list) and error_codes:
        compact_codes = ", ".join(str(code) for code in error_codes[:5])
        message = f"{message} (codes: {compact_codes})"

    return message


class UserService:
    def __init__(self):
        self._sessions: dict[str, UserSession] = {}
        self._pending_oidc: dict[str, PendingOidcLogin] = {}
        self._oidc_metadata_cache: dict[str, object] | None = None
        self._oidc_metadata_fetched_at = 0

    def get_public_auth_config(self, identity: IdentitySettings) -> PublicAuthConfig:
        azure = identity.azure
        azure_configured = bool(_clean(azure.tenant_id) and _clean(azure.client_id))
        azure_active = identity.provider == "azure_entra" and bool(azure.activated_at)
        return PublicAuthConfig(
            provider=identity.provider,
            provider_locked=identity.provider_locked,
            local_bootstrap_available=self.local_bootstrap_available(identity),
            azure_configured=azure_configured,
            azure_active=azure_active,
            microsoft_login_available=azure_active and azure_configured,
            client_id_configured=bool(_clean(azure.client_id)),
            tenant_id_configured=bool(_clean(azure.tenant_id)),
            client_secret_configured=bool(_clean(azure.client_secret)),
            group_mapping_count=len(azure.group_role_mappings),
        )

    def build_settings_response_identity(self, identity: IdentitySettings) -> dict[str, object]:
        azure = identity.azure
        return {
            "provider": identity.provider,
            "provider_locked": identity.provider_locked,
            "session_ttl_seconds": identity.session_ttl_seconds,
            "local_bootstrap_available": self.local_bootstrap_available(identity),
            "azure": {
                "tenant_id": azure.tenant_id,
                "client_id": azure.client_id,
                "authority_url": azure.authority_url,
                "redirect_path": MICROSOFT_SSO_REDIRECT_PATH,
                "scopes": list(azure.scopes),
                "group_role_mappings": [mapping.model_dump(mode="json") for mapping in azure.group_role_mappings],
                "client_secret_configured": bool(_clean(azure.client_secret)),
                "activated_at": azure.activated_at,
                "active": identity.provider == "azure_entra" and bool(azure.activated_at),
            },
        }

    def local_bootstrap_available(self, identity: IdentitySettings) -> bool:
        if identity.provider == "azure_entra" and identity.provider_locked:
            return False
        return bool(_clean(os.getenv(LOCAL_ADMIN_USERNAME_ENV)) and _clean(os.getenv(LOCAL_ADMIN_PASSWORD_ENV)))

    def prepare_identity_patch(self, current: IdentitySettings, requested: IdentitySettingsPatch) -> IdentitySettingsPatch:
        if requested.session_ttl_seconds is not None and requested.session_ttl_seconds < 900:
            raise ValueError("Session TTL must be at least 900 seconds")

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
            tenant_id = _clean(azure_patch.tenant_id) or current.azure.tenant_id
            client_id = _clean(azure_patch.client_id) or current.azure.client_id
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
            patch_payload.setdefault("azure", {})["activated_at"] = current.azure.activated_at or _now()
            payload["provider"] = "azure_entra"
            payload["provider_locked"] = True

        payload.update({key: value for key, value in patch_payload.items() if key != "azure"})
        if "azure" in patch_payload:
            azure_payload = dict(payload.get("azure") or {})
            azure_payload.update({key: value for key, value in patch_payload["azure"].items() if key != "activate"})
            payload["azure"] = azure_payload
        return payload

    def authenticate_local_admin(self, identity: IdentitySettings, username: str, password: str) -> UserIdentity | None:
        if not self.local_bootstrap_available(identity):
            return None

        expected_username = _clean(os.getenv(LOCAL_ADMIN_USERNAME_ENV))
        expected_password = _clean(os.getenv(LOCAL_ADMIN_PASSWORD_ENV))
        if username != expected_username or password != expected_password:
            return None

        return UserIdentity(
            subject=f"local:{expected_username}",
            username=expected_username,
            display_name="Local Admin",
            auth_provider="local_bootstrap",
            roles=["admin"],
            claims={},
        )

    def create_session(self, identity_settings: IdentitySettings, user: UserIdentity) -> UserSession:
        self._purge_expired_sessions()
        now = _now()
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
        return session

    def get_session(self, access_token: str | None) -> UserSession | None:
        self._purge_expired_sessions()
        if not access_token:
            return None
        session = self._sessions.get(access_token)
        if not session:
            return None
        session.last_seen_at = _now()
        return session

    def revoke_session(self, access_token: str | None) -> None:
        if not access_token:
            return
        self._sessions.pop(access_token, None)

    def begin_microsoft_login(self, identity: IdentitySettings, public_base_url: str, return_to: str) -> str:
        metadata = self._get_oidc_metadata(identity)
        authorize_endpoint = _clean(str(metadata.get("authorization_endpoint") or ""))
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
            expires_at=_now() + 600,
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
        id_token = _clean(str(token_payload.get("id_token") or ""))
        if not id_token:
            raise RuntimeError("Microsoft token response did not include an id_token")
        claims = _decode_unverified_jwt(id_token)
        if _clean(str(claims.get("nonce") or "")) != pending.nonce:
            raise ValueError("Microsoft login nonce mismatch")

        user = self._build_user_from_claims(identity, claims)
        session = self.create_session(identity, user)
        return session, pending.return_to

    def _build_user_from_claims(self, identity: IdentitySettings, claims: dict[str, object]) -> UserIdentity:
        now = _now()
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

        issuer = _clean(str(claims.get("iss") or ""))
        tenant_id = identity.azure.tenant_id
        if tenant_id and tenant_id not in issuer:
            raise ValueError("Microsoft id_token issuer mismatch")

        subject = _clean(str(claims.get("sub") or claims.get("oid") or ""))
        if not subject:
            raise ValueError("Microsoft id_token is missing subject")

        username = _clean(str(claims.get("preferred_username") or claims.get("email") or claims.get("upn") or subject))
        display_name = _clean(str(claims.get("name") or username))
        email = _clean(str(claims.get("email") or claims.get("preferred_username") or ""))
        group_ids = [str(item).strip() for item in (claims.get("groups") or []) if str(item).strip()] if isinstance(claims.get("groups"), list) else []
        role_names = [str(item).strip() for item in (claims.get("roles") or []) if str(item).strip()] if isinstance(claims.get("roles"), list) else []

        mapped_roles: set[str] = set(role_names)
        mapped_group_names: list[str] = []
        for mapping in identity.azure.group_role_mappings:
            group_object_id = _clean(mapping.group_object_id)
            if group_object_id and group_object_id in group_ids:
                mapped_roles.update(role for role in mapping.app_roles if role)
                if mapping.group_name:
                    mapped_group_names.append(mapping.group_name)

        effective_role = get_highest_role(mapped_roles)

        return UserIdentity(
            subject=f"microsoft:{subject}",
            username=username,
            display_name=display_name,
            email=email,
            auth_provider="azure_entra",
            roles=[effective_role],
            group_ids=group_ids,
            group_names=sorted({name for name in mapped_group_names if name}),
            claims={
                "oid": claims.get("oid"),
                "tid": claims.get("tid"),
                "preferred_username": claims.get("preferred_username"),
                "roles": role_names,
                "has_groups_overage": bool(claims.get("_claim_names") or claims.get("hasgroups")),
            },
        )

    def _exchange_authorization_code(self, identity: IdentitySettings, code: str, pending: PendingOidcLogin) -> dict[str, object]:
        metadata = self._get_oidc_metadata(identity)
        token_endpoint = _clean(str(metadata.get("token_endpoint") or ""))
        if not token_endpoint:
            raise RuntimeError("Microsoft token endpoint is not configured")

        form = {
            "grant_type": "authorization_code",
            "client_id": identity.azure.client_id,
            "code": code,
            "redirect_uri": pending.redirect_uri,
            "code_verifier": pending.code_verifier,
        }
        if _clean(identity.azure.client_secret):
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
            raise RuntimeError(_format_http_error("Microsoft token exchange", "request", error)) from error
        except URLError as error:
            raise RuntimeError(f"Microsoft token exchange request failed: {error.reason}") from error
        if not isinstance(payload, dict):
            raise RuntimeError("Microsoft token response is invalid")
        return payload

    def _get_oidc_metadata(self, identity: IdentitySettings) -> dict[str, object]:
        now = _now()
        if self._oidc_metadata_cache and now - self._oidc_metadata_fetched_at < 3600:
            return self._oidc_metadata_cache

        authority_url = _clean(identity.azure.authority_url)
        if not authority_url:
            tenant_id = _clean(identity.azure.tenant_id)
            if not tenant_id:
                raise RuntimeError("Azure SSO tenant_id is not configured")
            authority_url = f"https://login.microsoftonline.com/{tenant_id}/v2.0"

        discovery_url = f"{authority_url.rstrip('/')}/.well-known/openid-configuration"
        request = Request(discovery_url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise RuntimeError(_format_http_error("OIDC discovery", "request", error)) from error
        except URLError as error:
            raise RuntimeError(f"OIDC discovery request failed: {error.reason}") from error
        if not isinstance(payload, dict):
            raise RuntimeError("OIDC discovery response is invalid")
        self._oidc_metadata_cache = payload
        self._oidc_metadata_fetched_at = now
        return payload

    def _purge_expired_sessions(self) -> None:
        now = _now()
        expired = [token for token, session in self._sessions.items() if session.expires_at <= now]
        for token in expired:
            self._sessions.pop(token, None)

    def _purge_expired_pending_oidc(self) -> None:
        now = _now()
        expired = [state for state, pending in self._pending_oidc.items() if pending.expires_at <= now]
        for state in expired:
            self._pending_oidc.pop(state, None)