from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from vm_agent_server.src.api.schemas.user_requests import BeginMicrosoftLoginRequest, LocalLoginRequest
from vm_agent_server.src.api.schemas.user_responses import (
    BeginMicrosoftLoginResponse,
    LogoutResponse,
    PublicAuthConfigResponse,
    RecentUsersResponse,
    UserSessionResponse,
)
from vm_agent_server.src.users.service import UserService


def build_users_router(
    server_settings_service,
    user_service: UserService,
    resolve_public_base_url,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/users/auth-config", response_model=PublicAuthConfigResponse)
    async def api_user_auth_config():
        return user_service.get_public_auth_config(server_settings_service.get_snapshot().identity).model_dump(mode="json")

    @router.post("/users/login/local", response_model=UserSessionResponse)
    async def api_user_local_login(body: LocalLoginRequest):
        identity_settings = server_settings_service.get_snapshot().identity
        user = user_service.authenticate_local_admin(identity_settings, body.username, body.password)
        if not user:
            return JSONResponse({"error": "Invalid credentials"}, status_code=401)
        session = user_service.create_session(identity_settings, user)
        return session.model_dump(mode="json")

    @router.post("/users/login/microsoft", response_model=BeginMicrosoftLoginResponse)
    async def api_user_begin_microsoft_login(body: BeginMicrosoftLoginRequest, request: Request):
        identity_settings = server_settings_service.get_snapshot().identity
        public_base_url = resolve_public_base_url(request)
        try:
            authorize_url = user_service.begin_microsoft_login(identity_settings, public_base_url, body.return_to)
        except Exception as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        return {"authorize_url": authorize_url}

    @router.get("/users/callback/microsoft")
    async def api_user_microsoft_callback(
        state: str = Query(..., min_length=1),
        code: str = Query(..., min_length=1),
    ):
        identity_settings = server_settings_service.get_snapshot().identity
        try:
            session, return_to = user_service.finish_microsoft_login(identity_settings, state, code)
        except Exception as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        separator = "&" if "#" in return_to or "?" in return_to else "#"
        return RedirectResponse(url=f"{return_to}{separator}auth_token={session.access_token}")

    @router.get("/users/me", response_model=UserSessionResponse)
    async def api_user_me(request: Request):
        session = getattr(request.state, "user_session", None)
        if session is None:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return session.model_dump(mode="json")

    @router.get("/users/recent", response_model=RecentUsersResponse)
    async def api_recent_users(request: Request, limit: int = Query(default=100, ge=1, le=500)):
        session = getattr(request.state, "user_session", None)
        if session is None or "admin" not in set(session.user.roles):
            return JSONResponse({"error": "Admin role required"}, status_code=403)
        return {"items": [item.model_dump(mode="json") for item in await user_service.list_recent_identities(limit)]}

    @router.post("/users/logout", response_model=LogoutResponse)
    async def api_user_logout(request: Request):
        session = getattr(request.state, "user_session", None)
        if session is not None:
            user_service.revoke_session(session.access_token)
        return {"ok": True}

    return router