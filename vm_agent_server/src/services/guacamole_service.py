from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from collections.abc import AsyncIterator
from http.cookies import SimpleCookie
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode
from urllib.request import Request as UrlRequest, urlopen

from fastapi import WebSocket
from fastapi.responses import JSONResponse, Response, StreamingResponse

from vm_agent_server.src.services.rdp_monitor_service import RdpMonitorService
from vm_agent_server.src.users.models import UserSession

logger = logging.getLogger(__name__)


def _clean_string(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _format_token_marker(value: object) -> str:
    clean_value = _clean_string(value)
    if not clean_value:
        return "<none>"
    if len(clean_value) <= 12:
        return clean_value
    return f"{clean_value[:6]}...{clean_value[-6:]}"


class GuacamoleTunnelStreamResponse(Response):
    def __init__(
        self,
        content: AsyncIterator[bytes],
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        media_type: str | None = None,
    ) -> None:
        self.body_iterator = content
        self.status_code = status_code
        self.media_type = self.media_type if media_type is None else media_type
        self.background = None
        self.init_headers(headers)

    async def __call__(self, scope, receive, send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )

        try:
            async for chunk in self.body_iterator:
                if not isinstance(chunk, bytes | memoryview):
                    chunk = chunk.encode(self.charset)
                await send({"type": "http.response.body", "body": chunk, "more_body": True})

            await send({"type": "http.response.body", "body": b"", "more_body": False})
        except (asyncio.CancelledError, OSError):
            return


class GuacamoleService:
    def __init__(
        self,
        *,
        build_proxy_tunnel_urls: Callable[[str], dict[str, str]],
        get_guacamole_config: Callable[[], dict[str, Any]],
        list_guacamole_connections: Callable[[], Any],
        build_guacamole_session: Callable[[str, dict[str, Any] | None], dict[str, Any]],
        inspect_guacamole_connection: Callable[[str, dict[str, Any] | None], dict[str, Any]],
        create_guacamole_client_session: Callable[[str, dict[str, Any] | None, dict[str, str] | None], dict[str, Any]],
        invalidate_guacamole_token: Callable[[str, str], bool],
        get_guacamole_base_url: Callable[[], str],
        rdp_monitor: RdpMonitorService | None = None,
    ):
        self._build_proxy_tunnel_urls = build_proxy_tunnel_urls
        self._get_guacamole_config = get_guacamole_config
        self._list_guacamole_connections = list_guacamole_connections
        self._build_guacamole_session = build_guacamole_session
        self._inspect_guacamole_connection = inspect_guacamole_connection
        self._create_guacamole_client_session = create_guacamole_client_session
        self._invalidate_guacamole_token = invalidate_guacamole_token
        self._get_guacamole_base_url = get_guacamole_base_url
        self._rdp_monitor = rdp_monitor or RdpMonitorService()
        self._agent_tokens: dict[str, set[str]] = {}
        self._auth_cookies_by_auth_token: dict[str, str] = {}
        self._http_tunnel_tokens: dict[str, str] = {}
        self._http_tunnel_cookies: dict[str, str] = {}
        self._websocket_proxy_supported: bool | None = None
        self._websockets_by_auth_token: dict[str, set[WebSocket]] = {}
        self._active_streams: set[Any] = set()
        self._active_streams_lock = threading.Lock()
        self._shutdown_requested = threading.Event()
        self._pending_close_tasks: dict[str, asyncio.Task[None]] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._recent_close_reasons: dict[str, tuple[float, str]] = {}
        self._recent_recording_owners: list[dict[str, Any]] = []

    @property
    def rdp_monitor(self) -> RdpMonitorService:
        return self._rdp_monitor

    def get_config(self, public_base_url: str | None = None) -> dict[str, Any]:
        config = dict(self._get_guacamole_config())
        if public_base_url:
            proxy_tunnels = self._build_proxy_tunnel_urls(public_base_url)
            config["websocket_tunnel_url"] = proxy_tunnels.get("websocket", "")
            config["http_tunnel_url"] = proxy_tunnels.get("http", "")
        return config

    def list_connections(self):
        return self._list_guacamole_connections()

    def list_tracked_sessions(self) -> dict[str, Any]:
        snapshot = self._rdp_monitor.build_snapshot()
        snapshot.sort(key=lambda entry: float(entry.get("last_activity_at") or 0), reverse=True)
        return {
            "tracked_count": len(snapshot),
            "idle_timeout_seconds": self._rdp_monitor.idle_timeout_seconds,
            "sessions": snapshot,
        }

    def build_session(self, agent_id: str, state: dict[str, Any] | None) -> dict[str, Any]:
        return self._build_guacamole_session(agent_id, state)

    def inspect_connection(self, agent_id: str, state: dict[str, Any] | None) -> dict[str, Any]:
        return self._inspect_guacamole_connection(agent_id, state)

    def get_websocket_proxy_supported(self) -> bool | None:
        return self._websocket_proxy_supported

    def set_websocket_proxy_supported(self, supported: bool | None) -> None:
        self._websocket_proxy_supported = supported

    def _should_use_websocket_tunnel(self) -> bool:
        return True

    def _forget_http_tunnels_for_auth_token(self, auth_token: str) -> list[str]:
        released_tunnels = self._rdp_monitor.release_all_tunnels(auth_token)
        for tunnel_uuid in released_tunnels:
            self._http_tunnel_tokens.pop(tunnel_uuid, None)
            self._http_tunnel_cookies.pop(tunnel_uuid, None)
        return released_tunnels

    def _get_reusable_http_tunnel_uuid(self, auth_token: str) -> str:
        preferred_tunnel_uuid = self._rdp_monitor.get_primary_tunnel_uuid(auth_token)
        if preferred_tunnel_uuid and self._http_tunnel_tokens.get(preferred_tunnel_uuid):
            return preferred_tunnel_uuid

        for tunnel_uuid in reversed(self._rdp_monitor.get_tunnel_uuids(auth_token)):
            if self._http_tunnel_tokens.get(tunnel_uuid):
                self._rdp_monitor.touch_tunnel(tunnel_uuid)
                return tunnel_uuid

        return ""

    def _get_session_lock(self, agent_id: str) -> asyncio.Lock:
        clean_agent_id = _clean_string(agent_id) or "__default__"
        existing_lock = self._session_locks.get(clean_agent_id)
        if existing_lock is not None:
            return existing_lock

        next_lock = asyncio.Lock()
        self._session_locks[clean_agent_id] = next_lock
        return next_lock

    def _build_tracked_owner(self, user_session: UserSession | None) -> dict[str, str] | None:
        if user_session is None:
            return None

        user = user_session.user
        return {
            "subject": _clean_string(user.subject),
            "username": _clean_string(user.username),
            "display_name": _clean_string(user.display_name),
            "email": _clean_string(user.email),
            "avatar_url": _clean_string(user.avatar_url),
            "avatar_initials": _clean_string(user.avatar_initials),
            "auth_provider": _clean_string(user.auth_provider),
        }

    def _build_session_lock_key(self, agent_id: str, tracked_owner: dict[str, str] | None) -> str:
        owner_subject = _clean_string((tracked_owner or {}).get("subject"))
        if owner_subject:
            return f"owner:{owner_subject}"
        clean_agent_id = _clean_string(agent_id)
        if clean_agent_id:
            return f"agent:{clean_agent_id}"
        return "__default__"

    def _remember_close_reason(self, auth_token: str, close_reason: str) -> None:
        clean_auth_token = _clean_string(auth_token)
        clean_close_reason = _clean_string(close_reason)
        if not clean_auth_token or not clean_close_reason:
            return

        self._recent_close_reasons[clean_auth_token] = (asyncio.get_running_loop().time() + 120.0, clean_close_reason)

    def get_recent_close_reason(self, auth_token: str) -> str:
        clean_auth_token = _clean_string(auth_token)
        if not clean_auth_token:
            return ""

        now = asyncio.get_running_loop().time()
        for stored_auth_token, (expires_at, _) in list(self._recent_close_reasons.items()):
            if expires_at <= now:
                self._recent_close_reasons.pop(stored_auth_token, None)

        stored = self._recent_close_reasons.pop(clean_auth_token, None)
        if not stored:
            return ""

        expires_at, close_reason = stored
        if expires_at <= now:
            return ""
        return close_reason

    def _trim_recent_recording_owners(self) -> None:
        cutoff = time.time() - 86400.0
        self._recent_recording_owners = [
            entry
            for entry in self._recent_recording_owners
            if float(entry.get("created_at") or 0) >= cutoff
        ][-512:]

    def _remember_recording_owner(self, recording_entry: dict[str, Any] | None, agent_id: str, tracked_owner: dict[str, str] | None) -> None:
        if not recording_entry or not tracked_owner:
            return

        relative_path = _clean_string(recording_entry.get("relative_path"))
        if not relative_path:
            return

        self._trim_recent_recording_owners()
        self._recent_recording_owners.append({
            "created_at": time.time(),
            "agent_id": _clean_string(agent_id),
            "relative_path": relative_path,
            "relative_stem": relative_path[:-5] if relative_path.casefold().endswith(".guac") else relative_path,
            "owner": {key: _clean_string(value) for key, value in tracked_owner.items()},
        })

    def _find_recent_recording_owner(self, relative_path: str) -> dict[str, Any] | None:
        clean_relative_path = _clean_string(relative_path)
        if not clean_relative_path:
            return None

        self._trim_recent_recording_owners()
        candidate_stem = clean_relative_path[:-5] if clean_relative_path.casefold().endswith(".guac") else clean_relative_path
        best_match: dict[str, Any] | None = None
        best_length = -1
        for entry in self._recent_recording_owners:
            stored_path = _clean_string(entry.get("relative_path"))
            stored_stem = _clean_string(entry.get("relative_stem"))
            if not stored_path and not stored_stem:
                continue
            if clean_relative_path == stored_path or candidate_stem == stored_stem or candidate_stem.startswith(f"{stored_stem}."):
                match_length = len(stored_stem or stored_path)
                if match_length > best_length:
                    best_match = entry
                    best_length = match_length
        return best_match

    def annotate_recording_inventory(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return payload

        entries = payload.get("entries")
        if not isinstance(entries, list):
            return payload

        annotated_entries: list[dict[str, Any]] = []
        for raw_entry in entries:
            if not isinstance(raw_entry, dict):
                continue

            next_entry = dict(raw_entry)
            owner_match = self._find_recent_recording_owner(_clean_string(next_entry.get("relative_path")))
            if owner_match is not None:
                next_entry["owner"] = dict(owner_match.get("owner") or {})
                next_entry["agent_id"] = _clean_string(owner_match.get("agent_id")) or _clean_string(next_entry.get("agent_id"))
                owner_payload = next_entry.get("owner") if isinstance(next_entry.get("owner"), dict) else {}
                next_entry["username"] = _clean_string(owner_payload.get("username")) or _clean_string(next_entry.get("username"))
            annotated_entries.append(next_entry)

        return {
            **payload,
            "entries": annotated_entries,
        }

    async def create_client_session(
        self,
        agent_id: str,
        state: dict[str, Any] | None,
        public_base_url: str,
        *,
        user_session: UserSession | None = None,
        force_fresh: bool = False,
        refresh_tunnel: bool = False,
        resume_auth_token: str = "",
        connection_id: str = "",
        vm_username: str = "",
        read_only: bool = False,
        recorded: bool = False,
    ) -> dict[str, Any]:
        tracked_owner = self._build_tracked_owner(user_session)
        lock_key = self._build_session_lock_key(agent_id, tracked_owner)

        async with self._get_session_lock(lock_key):
            base_session = self._build_guacamole_session(agent_id, state)
            proxy_tunnels = self._build_proxy_tunnel_urls(public_base_url)
            if not self._should_use_websocket_tunnel() or self._websocket_proxy_supported is False:
                proxy_tunnels["websocket"] = ""
            should_prepare_http_resume = True

            requested_connection_id = _clean_string(connection_id)
            requested_username = _clean_string(vm_username) or _clean_string((base_session.get("resolved_fields") or {}).get("guacamole_username"))
            owner_subject = _clean_string((tracked_owner or {}).get("subject"))
            requested_resume_auth_token = _clean_string(resume_auth_token)

            existing = None
            if requested_resume_auth_token:
                requested_session = self._rdp_monitor.get_session(requested_resume_auth_token)
                requested_owner_subject = _clean_string(((requested_session.owner or {}) if requested_session else {}).get("subject"))
                if (
                    requested_session is not None
                    and requested_session.agent_id == agent_id
                    and (not owner_subject or requested_owner_subject == owner_subject)
                ):
                    existing = requested_session

            if existing is None:
                existing = self._rdp_monitor.get_session_for_owner(owner_subject) if owner_subject else self._rdp_monitor.get_session_for_agent(agent_id)
            reusing_requested_auth_token = existing is not None and _clean_string(existing.auth_token) == requested_resume_auth_token
            if existing is not None and recorded:
                force_fresh = True
            if existing is not None and existing.agent_id != agent_id:
                force_fresh = True
            if existing is not None and requested_connection_id and requested_connection_id != existing.connection_id and not reusing_requested_auth_token:
                force_fresh = True
            if existing is not None and force_fresh:
                self.cancel_scheduled_session_close(existing.auth_token)
                logger.info(
                    "Refreshing Guacamole session for owner=%s agent=%s auth=%s connection=%s refresh_tunnel=%s",
                    owner_subject or "<anonymous>",
                    agent_id,
                    _format_token_marker(existing.auth_token),
                    existing.connection_id or "<none>",
                    refresh_tunnel,
                )
                base_url = self._get_guacamole_base_url()
                try:
                    if base_url:
                        await asyncio.to_thread(self._invalidate_guacamole_token, base_url, existing.auth_token)
                except Exception as error:
                    logger.warning("Failed to invalidate Guacamole session %s before refresh: %s", existing.auth_token, error)
                await self._forget_session(existing.auth_token, close_reason="Session refreshed")
                existing = None

            if existing is not None:
                self.cancel_scheduled_session_close(existing.auth_token)
                self._rdp_monitor.register_session(
                    agent_id=agent_id,
                    auth_token=existing.auth_token,
                    connection_id=existing.connection_id,
                    data_source=existing.data_source,
                    username=requested_username or existing.username,
                    owner=tracked_owner,
                )
                existing_auth_cookie = self._auth_cookies_by_auth_token.get(existing.auth_token, "")
                resume_tunnel_uuid = ""
                if should_prepare_http_resume and refresh_tunnel:
                    released_tunnels = self._forget_http_tunnels_for_auth_token(existing.auth_token)
                    if released_tunnels:
                        logger.info(
                            "Dropped stale Guacamole tunnel(s) for agent=%s auth=%s tunnels=%s",
                            agent_id,
                            _format_token_marker(existing.auth_token),
                            ",".join(released_tunnels),
                        )
                    resume_tunnel_uuid = await asyncio.to_thread(
                        self._open_http_tunnel,
                        existing.auth_token,
                        existing.data_source,
                        existing.connection_id,
                        base_session.get("display") if isinstance(base_session.get("display"), dict) else {},
                    )
                if should_prepare_http_resume and not resume_tunnel_uuid:
                    resume_tunnel_uuid = self._get_reusable_http_tunnel_uuid(existing.auth_token)
                if should_prepare_http_resume and not resume_tunnel_uuid:
                    resume_tunnel_uuid = await asyncio.to_thread(
                        self._open_http_tunnel,
                        existing.auth_token,
                        existing.data_source,
                        existing.connection_id,
                        base_session.get("display") if isinstance(base_session.get("display"), dict) else {},
                    )
                logger.info(
                    "Reusing Guacamole session for owner=%s agent=%s auth=%s connection=%s resume_tunnel=%s",
                    owner_subject or "<anonymous>",
                    agent_id,
                    _format_token_marker(existing.auth_token),
                    existing.connection_id or "<none>",
                    resume_tunnel_uuid or "<none>",
                )
                reusable_session = {
                    **base_session,
                    "status": "ready",
                    "read_only": read_only,
                    "tunnels": proxy_tunnels,
                    "client_session": {
                        "auth_token": existing.auth_token,
                        "auth_cookie_header": existing_auth_cookie,
                        "data_source": existing.data_source,
                        "connection_id": existing.connection_id,
                        "connection_type": "c",
                        "display": (base_session.get("display") or {"mode": "dynamic", "dpi": 96}),
                        "tunnels": proxy_tunnels,
                    },
                }
                if resume_tunnel_uuid:
                    reusable_session["client_session"]["resume_tunnel_uuid"] = resume_tunnel_uuid
                return reusable_session

            logger.info(
                "Creating new Guacamole session for owner=%s agent=%s force_fresh=%s",
                owner_subject or "<anonymous>",
                agent_id,
                force_fresh,
            )
            session = await asyncio.to_thread(
                self._create_guacamole_client_session,
                agent_id,
                state,
                proxy_tunnels,
                connection_id=requested_connection_id,
                vm_username=vm_username,
                recording_owner=tracked_owner,
                recorded=recorded,
            )
            next_client_session = session.get("client_session") if isinstance(session.get("client_session"), dict) else {}
            recording_entry = session.get("recording_entry") if isinstance(session.get("recording_entry"), dict) else None
            auth_token = _clean_string(next_client_session.get("auth_token"))
            if auth_token:
                auth_cookie_header = _clean_string(next_client_session.get("auth_cookie_header"))
                if auth_cookie_header:
                    self._auth_cookies_by_auth_token[auth_token] = auth_cookie_header
                self._agent_tokens.setdefault(agent_id, set()).add(auth_token)
                self._rdp_monitor.register_session(
                    agent_id=agent_id,
                    auth_token=auth_token,
                    connection_id=_clean_string(next_client_session.get("connection_id")),
                    data_source=_clean_string(next_client_session.get("data_source")),
                    username=requested_username,
                    owner=tracked_owner,
                )
                self._remember_recording_owner(recording_entry, agent_id, tracked_owner)
                resume_tunnel_uuid = ""
                if should_prepare_http_resume:
                    resume_tunnel_uuid = await asyncio.to_thread(
                        self._open_http_tunnel,
                        auth_token,
                        _clean_string(next_client_session.get("data_source")),
                        _clean_string(next_client_session.get("connection_id")),
                        next_client_session.get("display") if isinstance(next_client_session.get("display"), dict) else {},
                    )
                if resume_tunnel_uuid:
                    next_client_session["resume_tunnel_uuid"] = resume_tunnel_uuid
                logger.info(
                    "Created Guacamole session for owner=%s agent=%s auth=%s connection=%s resume_tunnel=%s",
                    owner_subject or "<anonymous>",
                    agent_id,
                    _format_token_marker(auth_token),
                    _clean_string(next_client_session.get("connection_id")) or "<none>",
                    resume_tunnel_uuid or "<none>",
                )
            else:
                session_status = _clean_string(session.get("status")) or "<unknown>"
                session_warnings = session.get("warnings") if isinstance(session.get("warnings"), list) else []
                logger.warning(
                    "Guacamole session creation for agent=%s did not return a usable client session; status=%s warnings=%s",
                    agent_id,
                    session_status,
                    session_warnings,
                )
            session["read_only"] = read_only
            return session

    async def revoke_client_session(self, auth_token: str) -> bool:
        self.cancel_scheduled_session_close(auth_token)
        base_url = self._get_guacamole_base_url()
        if not base_url:
            raise RuntimeError("Guacamole bridge is not configured")

        revoked = await asyncio.to_thread(self._invalidate_guacamole_token, base_url, auth_token)
        await self._forget_session(auth_token)
        return revoked

    async def expire_idle_sessions(self) -> int:
        expired_auth_tokens = self._rdp_monitor.get_idle_auth_tokens()
        if not expired_auth_tokens:
            return 0

        expired_count = 0
        base_url = self._get_guacamole_base_url()
        for auth_token in expired_auth_tokens:
            try:
                if base_url:
                    await asyncio.to_thread(self._invalidate_guacamole_token, base_url, auth_token)
            except Exception as error:
                logger.warning("Failed to invalidate idle Guacamole session %s: %s", auth_token, error)
            await self._forget_session(auth_token, close_reason="Idle timeout")
            expired_count += 1
        return expired_count

    async def close_tracked_sessions(self, auth_tokens: list[str] | None = None, *, close_reason: str = "Operator terminated") -> int:
        self._close_active_streams()

        if auth_tokens is None:
            auth_tokens = [
                entry["auth_token"]
                for entry in self._rdp_monitor.build_snapshot()
                if isinstance(entry.get("auth_token"), str)
            ]

        clean_auth_tokens = [_clean_string(auth_token) for auth_token in auth_tokens if _clean_string(auth_token)]
        if not clean_auth_tokens:
            return 0

        closed_count = 0
        base_url = self._get_guacamole_base_url()
        for auth_token in clean_auth_tokens:
            self.cancel_scheduled_session_close(auth_token)
            try:
                if base_url:
                    await asyncio.to_thread(self._invalidate_guacamole_token, base_url, auth_token)
            except Exception as error:
                logger.warning("Failed to invalidate tracked Guacamole session %s: %s", auth_token, error)
            await self._forget_session(auth_token, close_reason=close_reason)
            closed_count += 1
        return closed_count

    async def close_agent_owner_session(self, agent_id: str, owner_subject: str, *, close_reason: str) -> bool:
        clean_agent_id = _clean_string(agent_id)
        clean_owner_subject = _clean_string(owner_subject)
        if not clean_agent_id or not clean_owner_subject:
            return False

        tracked_session = next(
            (
                session
                for session in self._rdp_monitor.get_sessions_for_agent(clean_agent_id)
                if _clean_string((session.owner or {}).get("subject")) == clean_owner_subject
            ),
            None,
        )
        if tracked_session is None:
            return False

        closed_count = await self.close_tracked_sessions([tracked_session.auth_token], close_reason=close_reason)
        return closed_count > 0

    async def close_all_sessions(self) -> int:
        self._shutdown_requested.set()
        for auth_token in list(self._pending_close_tasks):
            self.cancel_scheduled_session_close(auth_token)
        return await self.close_tracked_sessions(close_reason="Server shutdown")

    def cancel_scheduled_session_close(self, auth_token: str) -> bool:
        clean_auth_token = _clean_string(auth_token)
        if not clean_auth_token:
            return False

        task = self._pending_close_tasks.pop(clean_auth_token, None)
        if task is None:
            return False

        task.cancel()
        return True

    def _mark_session_activity(self, auth_token: str) -> bool:
        clean_auth_token = _clean_string(auth_token)
        if not clean_auth_token:
            return False

        self.cancel_scheduled_session_close(clean_auth_token)
        self._rdp_monitor.touch_auth_token(clean_auth_token)
        return True

    def schedule_session_close(self, auth_token: str, delay_seconds: float = 5.0, *, close_reason: str = "Browser tab closed") -> bool:
        clean_auth_token = _clean_string(auth_token)
        if not clean_auth_token:
            return False

        self.cancel_scheduled_session_close(clean_auth_token)
        clamped_delay = max(0.5, float(delay_seconds))
        scheduled_at = time.time()

        async def close_later() -> None:
            try:
                await asyncio.sleep(clamped_delay)
                if self._shutdown_requested.is_set():
                    return

                tracked_session = self._rdp_monitor.get_session(clean_auth_token)
                if tracked_session is None:
                    return

                if tracked_session.last_activity_at > scheduled_at:
                    logger.info(
                        "Skipping delayed Guacamole close for auth=%s because newer activity was observed",
                        _format_token_marker(clean_auth_token),
                    )
                    return

                active_websockets = self._websockets_by_auth_token.get(clean_auth_token) or set()
                if active_websockets:
                    logger.info(
                        "Skipping delayed Guacamole close for auth=%s because websocket activity resumed",
                        _format_token_marker(clean_auth_token),
                    )
                    return

                if self._get_guacamole_base_url():
                    try:
                        await asyncio.to_thread(self._invalidate_guacamole_token, self._get_guacamole_base_url(), clean_auth_token)
                    except Exception as error:
                        logger.warning("Failed to invalidate delayed Guacamole session %s: %s", clean_auth_token, error)

                await self._forget_session(clean_auth_token, close_reason=close_reason)
            except asyncio.CancelledError:
                return
            finally:
                self._pending_close_tasks.pop(clean_auth_token, None)

        self._pending_close_tasks[clean_auth_token] = asyncio.create_task(close_later())
        return True

    async def register_websocket(self, raw_query: str, ws: WebSocket) -> str:
        auth_token = self._extract_auth_token_from_query(raw_query)
        if not auth_token:
            return ""
        sockets = self._websockets_by_auth_token.setdefault(auth_token, set())
        sockets.add(ws)
        self._mark_session_activity(auth_token)
        return auth_token

    async def unregister_websocket(self, auth_token: str, ws: WebSocket | None = None) -> None:
        clean_auth_token = _clean_string(auth_token)
        if not clean_auth_token:
            return

        sockets = self._websockets_by_auth_token.get(clean_auth_token)
        if not sockets:
            return

        if ws is not None:
            sockets.discard(ws)
        if not sockets or ws is None:
            self._websockets_by_auth_token.pop(clean_auth_token, None)

    def touch_websocket(self, raw_query: str) -> None:
        auth_token = self._extract_auth_token_from_query(raw_query)
        if auth_token:
            self._mark_session_activity(auth_token)

    def proxy_tunnel_request(self, method: str, raw_query: str, body: bytes, headers: dict[str, str]) -> Response:
        if self._shutdown_requested.is_set():
            return JSONResponse({"error": "Guacamole service is shutting down"}, status_code=503)

        auth_token = self._extract_auth_token_from_query(raw_query)
        if not auth_token:
            auth_token = self._extract_auth_token_from_body(body)
        if auth_token:
            self._mark_session_activity(auth_token)

        base_url = self._get_guacamole_base_url()
        if not base_url:
            return JSONResponse({"error": "Guacamole bridge is not configured"}, status_code=503)

        requested_resume_tunnel_uuid = ""
        if raw_query == "connect":
            requested_resume_tunnel_uuid = self._extract_resume_tunnel_uuid(body)
            if requested_resume_tunnel_uuid:
                logger.info(
                    "Forwarding Guacamole HTTP tunnel resume connect uuid=%s tunnel_token=%s cookie_present=%s",
                    requested_resume_tunnel_uuid,
                    _format_token_marker(self._http_tunnel_tokens.get(requested_resume_tunnel_uuid, "")),
                    bool(self._http_tunnel_cookies.get(requested_resume_tunnel_uuid, "")),
                )
                self._rdp_monitor.touch_tunnel(requested_resume_tunnel_uuid)

        upstream_url = f"{base_url}/tunnel"
        if raw_query:
            upstream_url = f"{upstream_url}?{raw_query}"

        tunnel_uuid = self._extract_tunnel_uuid(raw_query)
        if tunnel_uuid:
            self._rdp_monitor.touch_tunnel(tunnel_uuid)
        tunnel_header_uuid = tunnel_uuid or requested_resume_tunnel_uuid

        request_headers = {
            "Accept": headers.get("accept") or "*/*",
        }
        content_type = headers.get("content-type")
        if content_type:
            request_headers["Content-Type"] = content_type

        tunnel_token = headers.get("guacamole-tunnel-token") or self._http_tunnel_tokens.get(tunnel_header_uuid, "")
        # For resumed Guacamole tunnels prefer the cookie captured when the tunnel was opened.
        # Browser cookies for the app origin are unrelated and can break upstream tunnel resume.
        auth_cookie = self._auth_cookies_by_auth_token.get(auth_token, "") if auth_token else ""
        tunnel_cookie = self._http_tunnel_cookies.get(tunnel_header_uuid, "") or auth_cookie or headers.get("cookie") or ""
        if tunnel_token:
            request_headers["Guacamole-Tunnel-Token"] = tunnel_token
        if tunnel_cookie:
            request_headers["Cookie"] = tunnel_cookie

        upstream_request = UrlRequest(
            upstream_url,
            data=body if method != "GET" else None,
            headers=request_headers,
            method=method,
        )

        try:
            upstream_response = urlopen(upstream_request, timeout=60)
        except HTTPError as error:
            error_body = error.read()
            if raw_query.startswith(("read:", "write:")):
                logger.warning(
                    "Guacamole HTTP tunnel request failed: method=%s query=%s status=%s token_forwarded=%s cookie_forwarded=%s",
                    method,
                    raw_query,
                    error.code,
                    bool(tunnel_token),
                    bool(tunnel_cookie),
                )
            if tunnel_uuid and error.code in {404, 410}:
                self._http_tunnel_tokens.pop(tunnel_uuid, None)
                self._http_tunnel_cookies.pop(tunnel_uuid, None)
                self._rdp_monitor.release_tunnel(tunnel_uuid)
            return Response(
                content=error_body,
                status_code=error.code,
                headers=self._copy_response_headers(error.headers),
                media_type=error.headers.get("Content-Type"),
            )
        except URLError as error:
            return JSONResponse({"error": f"Could not reach Guacamole tunnel: {error.reason}"}, status_code=502)
        except OSError as error:
            return JSONResponse({"error": f"Guacamole tunnel proxy failed: {error}"}, status_code=502)

        response_headers = self._copy_response_headers(upstream_response.headers)
        media_type = upstream_response.headers.get("Content-Type")

        if raw_query == "connect":
            connect_uuid = upstream_response.read().decode("utf-8").strip()
            connect_tunnel_token = response_headers.get("Guacamole-Tunnel-Token", "").strip()
            connect_cookie_header = self._extract_cookie_header(upstream_response.headers)
            connect_auth_token = self._extract_auth_token_from_body(body)
            upstream_response.close()
            if connect_uuid and connect_tunnel_token:
                self._http_tunnel_tokens[connect_uuid] = connect_tunnel_token
            if connect_uuid and connect_cookie_header:
                self._http_tunnel_cookies[connect_uuid] = connect_cookie_header
            if connect_uuid and connect_auth_token:
                self._rdp_monitor.bind_tunnel(connect_auth_token, connect_uuid)
                logger.info(
                    "Opened Guacamole HTTP tunnel uuid=%s auth=%s",
                    connect_uuid,
                    _format_token_marker(connect_auth_token),
                )
            return Response(
                content=connect_uuid,
                status_code=upstream_response.status,
                headers=response_headers,
                media_type=media_type,
            )

        if method == "GET":
            self._register_active_stream(upstream_response)

            async def iter_chunks():
                reader = getattr(upstream_response, "read1", upstream_response.read)
                try:
                    while True:
                        if self._shutdown_requested.is_set():
                            break
                        chunk = await asyncio.to_thread(reader, 65536)
                        if not chunk:
                            break
                        if tunnel_uuid:
                            self._rdp_monitor.touch_tunnel(tunnel_uuid)
                        yield chunk
                except asyncio.CancelledError:
                    return
                finally:
                    self._unregister_active_stream(upstream_response)
                    upstream_response.close()

            return GuacamoleTunnelStreamResponse(
                iter_chunks(),
                status_code=upstream_response.status,
                headers={
                    **response_headers,
                    "Cache-Control": response_headers.get("Cache-Control", "no-cache"),
                    "X-Accel-Buffering": "no",
                },
                media_type=media_type,
            )

        response_body = upstream_response.read()
        upstream_response.close()
        if tunnel_uuid:
            self._rdp_monitor.touch_tunnel(tunnel_uuid)
        if tunnel_uuid and raw_query.startswith("write:") and upstream_response.status >= 400:
            self._http_tunnel_tokens.pop(tunnel_uuid, None)
            self._http_tunnel_cookies.pop(tunnel_uuid, None)
            self._rdp_monitor.release_tunnel(tunnel_uuid)
        return Response(
            content=response_body,
            status_code=upstream_response.status,
            headers=response_headers,
            media_type=media_type,
        )

    def _register_active_stream(self, upstream_response: Any) -> None:
        with self._active_streams_lock:
            self._active_streams.add(upstream_response)

    def _unregister_active_stream(self, upstream_response: Any) -> None:
        with self._active_streams_lock:
            self._active_streams.discard(upstream_response)

    def _close_active_streams(self) -> None:
        with self._active_streams_lock:
            streams = list(self._active_streams)
            self._active_streams.clear()

        for stream in streams:
            try:
                stream.close()
            except Exception:
                pass

    async def _forget_session(self, auth_token: str, close_reason: str = "Session closed") -> None:
        clean_auth_token = _clean_string(auth_token)
        if not clean_auth_token:
            return

        self._remember_close_reason(clean_auth_token, close_reason)

        tracked_session = self._rdp_monitor.remove_session(clean_auth_token)
        self._auth_cookies_by_auth_token.pop(clean_auth_token, None)
        if tracked_session is not None:
            for tunnel_uuid in list(tracked_session.tunnel_uuids):
                self._http_tunnel_tokens.pop(tunnel_uuid, None)
                self._http_tunnel_cookies.pop(tunnel_uuid, None)

        for agent_id, stored_tokens in list(self._agent_tokens.items()):
            if clean_auth_token in stored_tokens:
                stored_tokens.discard(clean_auth_token)
                if not stored_tokens:
                    self._agent_tokens.pop(agent_id, None)

        sockets = self._websockets_by_auth_token.pop(clean_auth_token, set())
        for ws in list(sockets):
            try:
                await ws.close(code=1000, reason=close_reason)
            except Exception:
                pass

    @staticmethod
    def _extract_tunnel_uuid(raw_query: str) -> str:
        if raw_query == "connect":
            return ""
        for prefix in ("read:", "write:"):
            if raw_query.startswith(prefix):
                remainder = raw_query[len(prefix):]
                return remainder.split(":", 1)[0].strip()
        return ""

    @staticmethod
    def _extract_auth_token_from_query(raw_query: str) -> str:
        parsed_query = parse_qs(raw_query, keep_blank_values=True)
        values = parsed_query.get("token") or parsed_query.get("authToken") or []
        return _clean_string(values[0] if values else "")

    @staticmethod
    def _extract_auth_token_from_body(body: bytes) -> str:
        if not body:
            return ""
        parsed_body = parse_qs(body.decode("utf-8", errors="ignore"), keep_blank_values=True)
        values = parsed_body.get("token") or parsed_body.get("authToken") or []
        return _clean_string(values[0] if values else "")

    @staticmethod
    def _extract_resume_tunnel_uuid(body: bytes) -> str:
        if not body:
            return ""
        parsed_body = parse_qs(body.decode("utf-8", errors="ignore"), keep_blank_values=True)
        values = parsed_body.get("GUAC_RESUME_TUNNEL") or parsed_body.get("resume_tunnel_uuid") or []
        return _clean_string(values[0] if values else "")

    def _open_http_tunnel(
        self,
        auth_token: str,
        data_source: str,
        connection_id: str,
        display: dict[str, Any] | None,
    ) -> str:
        base_url = self._get_guacamole_base_url()
        if not base_url:
            return ""

        display = display if isinstance(display, dict) else {}
        dpi = int(display.get("dpi") or 96)
        width = int(display.get("width") or 1280)
        height = int(display.get("height") or 720)
        body = urlencode(
            {
                "token": auth_token,
                "GUAC_DATA_SOURCE": data_source,
                "GUAC_ID": connection_id,
                "GUAC_TYPE": "c",
                "GUAC_WIDTH": str(width),
                "GUAC_HEIGHT": str(height),
                "GUAC_DPI": str(dpi),
                "GUAC_TIMEZONE": "UTC",
            }
        ).encode("utf-8")

        request = UrlRequest(
            f"{base_url}/tunnel?connect",
            data=body,
            headers={
                "Accept": "*/*",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                **({"Cookie": self._auth_cookies_by_auth_token.get(auth_token, "")} if self._auth_cookies_by_auth_token.get(auth_token, "") else {}),
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=60) as response:
                connect_uuid = response.read().decode("utf-8").strip()
                connect_tunnel_token = self._copy_response_headers(response.headers).get("Guacamole-Tunnel-Token", "").strip()
                connect_cookie_header = self._extract_cookie_header(response.headers)
        except Exception as error:
            logger.warning("Failed to pre-open Guacamole HTTP tunnel for %s: %s", connection_id, error)
            return ""

        if connect_uuid and connect_tunnel_token:
            self._http_tunnel_tokens[connect_uuid] = connect_tunnel_token
            self._rdp_monitor.bind_tunnel(auth_token, connect_uuid)
        if connect_uuid and connect_cookie_header:
            self._http_tunnel_cookies[connect_uuid] = connect_cookie_header

        return connect_uuid

    @staticmethod
    def _copy_response_headers(headers: Any) -> dict[str, str]:
        forwarded: dict[str, str] = {}
        for header_name in [
            "Content-Type",
            "Guacamole-Tunnel-Token",
            "Guacamole-Status-Code",
            "Guacamole-Error-Message",
            "Cache-Control",
        ]:
            value = headers.get(header_name)
            if value:
                forwarded[header_name] = value
        return forwarded

    @staticmethod
    def _extract_cookie_header(headers: Any) -> str:
        raw_cookie_headers: list[str] = []
        get_all = getattr(headers, "get_all", None)
        if callable(get_all):
            raw_cookie_headers = get_all("Set-Cookie") or []

        if not raw_cookie_headers:
            single_cookie = headers.get("Set-Cookie")
            if single_cookie:
                raw_cookie_headers = [single_cookie]

        if not raw_cookie_headers:
            return ""

        cookie = SimpleCookie()
        for raw_cookie in raw_cookie_headers:
            try:
                cookie.load(raw_cookie)
            except Exception:
                continue

        return "; ".join(f"{morsel.key}={morsel.value}" for morsel in cookie.values())