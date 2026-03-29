from __future__ import annotations

from collections.abc import Iterable

from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse


ROLE_ORDER = {
    "viewer": 0,
    "operator": 1,
    "admin": 2,
}


def normalize_roles(roles: Iterable[str] | None) -> set[str]:
    normalized = {
        str(role).strip().lower()
        for role in (roles or [])
        if str(role).strip().lower() in ROLE_ORDER
    }
    if not normalized:
        normalized.add("viewer")
    return normalized


def get_highest_role(roles: Iterable[str] | None) -> str:
    effective_roles = normalize_roles(roles)
    return max(effective_roles, key=lambda role: ROLE_ORDER[role])


def has_minimum_role(roles: Iterable[str] | None, minimum_role: str) -> bool:
    minimum = ROLE_ORDER.get(minimum_role, ROLE_ORDER["admin"])
    return ROLE_ORDER[get_highest_role(roles)] >= minimum


def request_has_minimum_role(request: Request, minimum_role: str) -> bool:
    session = getattr(request.state, "user_session", None)
    if session is None:
        return False
    return has_minimum_role(getattr(session.user, "roles", []), minimum_role)


def websocket_has_minimum_role(ws: WebSocket, minimum_role: str) -> bool:
    session = getattr(ws.state, "user_session", None)
    if session is None:
        return False
    return has_minimum_role(getattr(session.user, "roles", []), minimum_role)


def role_required_response(minimum_role: str) -> JSONResponse:
    return JSONResponse({"error": f"{minimum_role.capitalize()} role required"}, status_code=403)