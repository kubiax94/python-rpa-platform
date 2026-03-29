from __future__ import annotations

import asyncio
from collections.abc import Callable
from urllib.error import HTTPError, URLError

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from vm_agent_server.src.api.schemas.deployment_responses import GenericStatusResponse, GuacamoleConfigResponse


def build_guacamole_router(
    get_agent_state,
    get_agent_record,
    resolve_public_base_url: Callable[[Request], str],
    build_proxy_tunnel_urls,
    get_guacamole_config,
    list_guacamole_connections,
    build_guacamole_session,
    inspect_guacamole_connection,
    create_guacamole_client_session,
    invalidate_guacamole_token,
    get_guacamole_base_url,
    proxy_guacamole_tunnel_request,
    get_websocket_proxy_supported: Callable[[], bool | None],
    guacamole_agent_tokens: dict[str, set[str]],
) -> APIRouter:
    router = APIRouter(prefix="/api")

    async def build_agent_context(agent_id: str) -> dict | None:
        state = get_agent_state(agent_id) or {}
        agent_record = await get_agent_record(agent_id)
        if not state and not agent_record:
            return None
        if agent_record:
            state = dict(state)
            state["__agent_record"] = agent_record
        return state

    @router.get("/guacamole/config", response_model=GuacamoleConfigResponse)
    async def api_guacamole_config():
        return get_guacamole_config()

    @router.get("/guacamole/connections")
    async def api_guacamole_connections():
        return await asyncio.to_thread(list_guacamole_connections)

    @router.get("/agents/{agent_id}/guacamole")
    async def api_agent_guacamole(agent_id: str):
        state = await build_agent_context(agent_id)
        if state is None:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return build_guacamole_session(agent_id, state)

    @router.get("/agents/{agent_id}/guacamole/diagnostics")
    async def api_agent_guacamole_diagnostics(agent_id: str):
        state = await build_agent_context(agent_id)
        if state is None:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return await asyncio.to_thread(inspect_guacamole_connection, agent_id, state)

    @router.post("/agents/{agent_id}/guacamole/session")
    async def api_agent_guacamole_session(agent_id: str, request: Request):
        state = await build_agent_context(agent_id)
        if state is None:
            return JSONResponse({"error": "Not found"}, status_code=404)

        proxy_tunnels = build_proxy_tunnel_urls(resolve_public_base_url(request))
        if get_websocket_proxy_supported() is False:
            proxy_tunnels["websocket"] = ""
        session = await asyncio.to_thread(create_guacamole_client_session, agent_id, state, proxy_tunnels)
        next_auth_token = str(((session.get("client_session") or {}).get("auth_token") or "")).strip()
        if next_auth_token:
            guacamole_agent_tokens.setdefault(agent_id, set()).add(next_auth_token)
        return session

    @router.delete("/guacamole/session/{auth_token}", response_model=GenericStatusResponse)
    async def api_guacamole_revoke_session(auth_token: str):
        base_url = get_guacamole_base_url()
        if not base_url:
            return JSONResponse({"error": "Guacamole bridge is not configured"}, status_code=503)

        try:
            revoked = await asyncio.to_thread(invalidate_guacamole_token, base_url, auth_token)
        except HTTPError as error:
            if error.code == 404:
                return {"ok": True, "revoked": False, "detail": "Token already invalidated"}
            return JSONResponse({"error": f"Guacamole token revoke failed with HTTP {error.code}"}, status_code=502)
        except URLError as error:
            return JSONResponse({"error": f"Could not reach Guacamole: {error.reason}"}, status_code=502)
        except OSError as error:
            return JSONResponse({"error": f"Guacamole token revoke failed: {error}"}, status_code=502)

        for agent_id, stored_tokens in list(guacamole_agent_tokens.items()):
            if auth_token in stored_tokens:
                stored_tokens.discard(auth_token)
                if not stored_tokens:
                    guacamole_agent_tokens.pop(agent_id, None)

        return {"ok": True, "revoked": revoked}

    @router.api_route("/guacamole/tunnel", methods=["GET", "POST"])
    async def api_guacamole_tunnel(request: Request):
        raw_query = request.scope.get("query_string", b"").decode("utf-8")
        body = await request.body() if request.method != "GET" else b""
        proxy_headers = {
            "accept": request.headers.get("accept", "*/*"),
            "content-type": request.headers.get("content-type", ""),
            "guacamole-tunnel-token": request.headers.get("guacamole-tunnel-token", ""),
            "cookie": request.headers.get("cookie", ""),
        }
        return await asyncio.to_thread(proxy_guacamole_tunnel_request, request.method, raw_query, body, proxy_headers)

    return router