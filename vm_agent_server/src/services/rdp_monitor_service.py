from __future__ import annotations

import os
import time
from dataclasses import dataclass, field


def _clean_string(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


@dataclass(slots=True)
class TrackedRdpSession:
    auth_token: str
    agent_id: str
    connection_id: str
    data_source: str
    created_at: float
    last_activity_at: float
    tunnel_uuids: set[str] = field(default_factory=set)


class RdpMonitorService:
    def __init__(self, idle_timeout_seconds: int | None = None):
        configured_timeout = idle_timeout_seconds
        if configured_timeout is None:
            raw_timeout = (os.getenv("GUACAMOLE_SESSION_IDLE_TIMEOUT_SECONDS") or "900").strip()
            try:
                configured_timeout = int(raw_timeout)
            except ValueError:
                configured_timeout = 900

        self._idle_timeout_seconds = max(0, configured_timeout)
        self._sessions_by_token: dict[str, TrackedRdpSession] = {}
        self._token_by_tunnel_uuid: dict[str, str] = {}

    @property
    def idle_timeout_seconds(self) -> int:
        return self._idle_timeout_seconds

    def register_session(self, *, agent_id: str, auth_token: str, connection_id: str = "", data_source: str = "") -> None:
        clean_auth_token = _clean_string(auth_token)
        if not clean_auth_token:
            return

        now = time.time()
        existing = self._sessions_by_token.get(clean_auth_token)
        if existing is not None:
            existing.agent_id = _clean_string(agent_id) or existing.agent_id
            existing.connection_id = _clean_string(connection_id) or existing.connection_id
            existing.data_source = _clean_string(data_source) or existing.data_source
            existing.last_activity_at = now
            return

        self._sessions_by_token[clean_auth_token] = TrackedRdpSession(
            auth_token=clean_auth_token,
            agent_id=_clean_string(agent_id),
            connection_id=_clean_string(connection_id),
            data_source=_clean_string(data_source),
            created_at=now,
            last_activity_at=now,
        )

    def get_session_for_agent(self, agent_id: str) -> TrackedRdpSession | None:
        clean_agent_id = _clean_string(agent_id)
        if not clean_agent_id:
            return None
        for session in self._sessions_by_token.values():
            if session.agent_id == clean_agent_id:
                return session
        return None

    def get_primary_tunnel_uuid(self, auth_token: str) -> str:
        session = self._sessions_by_token.get(_clean_string(auth_token))
        if session is None or not session.tunnel_uuids:
            return ""
        return sorted(session.tunnel_uuids)[0]

    def touch_auth_token(self, auth_token: str) -> None:
        session = self._sessions_by_token.get(_clean_string(auth_token))
        if session is not None:
            session.last_activity_at = time.time()

    def bind_tunnel(self, auth_token: str, tunnel_uuid: str) -> None:
        clean_auth_token = _clean_string(auth_token)
        clean_tunnel_uuid = _clean_string(tunnel_uuid)
        if not clean_auth_token or not clean_tunnel_uuid:
            return

        session = self._sessions_by_token.get(clean_auth_token)
        if session is None:
            self.register_session(agent_id="", auth_token=clean_auth_token)
            session = self._sessions_by_token.get(clean_auth_token)
            if session is None:
                return

        session.tunnel_uuids.add(clean_tunnel_uuid)
        session.last_activity_at = time.time()
        self._token_by_tunnel_uuid[clean_tunnel_uuid] = clean_auth_token

    def touch_tunnel(self, tunnel_uuid: str) -> None:
        clean_tunnel_uuid = _clean_string(tunnel_uuid)
        if not clean_tunnel_uuid:
            return
        auth_token = self._token_by_tunnel_uuid.get(clean_tunnel_uuid)
        if auth_token:
            self.touch_auth_token(auth_token)

    def release_tunnel(self, tunnel_uuid: str) -> None:
        clean_tunnel_uuid = _clean_string(tunnel_uuid)
        if not clean_tunnel_uuid:
            return
        auth_token = self._token_by_tunnel_uuid.pop(clean_tunnel_uuid, "")
        if not auth_token:
            return
        session = self._sessions_by_token.get(auth_token)
        if session is not None:
            session.tunnel_uuids.discard(clean_tunnel_uuid)

    def remove_session(self, auth_token: str) -> TrackedRdpSession | None:
        clean_auth_token = _clean_string(auth_token)
        if not clean_auth_token:
            return None

        session = self._sessions_by_token.pop(clean_auth_token, None)
        if session is None:
            return None

        for tunnel_uuid in list(session.tunnel_uuids):
            if self._token_by_tunnel_uuid.get(tunnel_uuid) == clean_auth_token:
                self._token_by_tunnel_uuid.pop(tunnel_uuid, None)

        session.tunnel_uuids.clear()
        return session

    def get_idle_auth_tokens(self) -> list[str]:
        if self._idle_timeout_seconds <= 0:
            return []

        cutoff = time.time() - self._idle_timeout_seconds
        return [
            auth_token
            for auth_token, session in self._sessions_by_token.items()
            if session.last_activity_at <= cutoff
        ]

    def build_snapshot(self) -> list[dict[str, object]]:
        snapshot: list[dict[str, object]] = []
        for session in self._sessions_by_token.values():
            snapshot.append(
                {
                    "auth_token": session.auth_token,
                    "agent_id": session.agent_id,
                    "connection_id": session.connection_id,
                    "data_source": session.data_source,
                    "created_at": session.created_at,
                    "last_activity_at": session.last_activity_at,
                    "idle_seconds": max(0.0, time.time() - session.last_activity_at),
                    "tunnel_count": len(session.tunnel_uuids),
                }
            )
        return snapshot