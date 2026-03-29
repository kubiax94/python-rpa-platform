from __future__ import annotations

import asyncio
from collections.abc import Callable
from urllib.error import HTTPError, URLError

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from vm_agent_server.src.api.schemas.deployment_responses import GenericStatusResponse, GuacamoleConfigResponse
from vm_agent_server.src.authz import request_has_minimum_role, role_required_response
from vm_agent_server.src.services.guacamole_service import GuacamoleService


def build_guacamole_router(
    get_agent_state,
    get_agent_record,
    resolve_public_base_url: Callable[[Request], str],
    guacamole_service: GuacamoleService,
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
    async def api_guacamole_config(request: Request):
        return guacamole_service.get_config(resolve_public_base_url(request))

    @router.get("/guacamole/connections")
    async def api_guacamole_connections():
        return await asyncio.to_thread(guacamole_service.list_connections)

    @router.get("/guacamole/tracked-sessions")
    async def api_guacamole_tracked_sessions(request: Request):
        if not request_has_minimum_role(request, "operator"):
            return role_required_response("operator")
        return guacamole_service.list_tracked_sessions()

    @router.post("/guacamole/tracked-sessions/kill-all")
    async def api_guacamole_kill_all_tracked_sessions(request: Request):
        if not request_has_minimum_role(request, "operator"):
            return role_required_response("operator")
        closed_count = await guacamole_service.close_tracked_sessions(close_reason="Operator terminated")
        return {"ok": True, "closed_count": closed_count}

    @router.get("/agents/{agent_id}/guacamole")
    async def api_agent_guacamole(agent_id: str):
        state = await build_agent_context(agent_id)
        if state is None:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return guacamole_service.build_session(agent_id, state)

    @router.get("/agents/{agent_id}/guacamole/diagnostics")
    async def api_agent_guacamole_diagnostics(agent_id: str):
        state = await build_agent_context(agent_id)
        if state is None:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return await asyncio.to_thread(guacamole_service.inspect_connection, agent_id, state)

    @router.post("/agents/{agent_id}/guacamole/session")
    async def api_agent_guacamole_session(
        agent_id: str,
        request: Request,
        force_fresh: bool = Query(False),
        refresh_tunnel: bool = Query(False),
    ):
        if not request_has_minimum_role(request, "operator"):
            return role_required_response("operator")
        state = await build_agent_context(agent_id)
        if state is None:
            return JSONResponse({"error": "Not found"}, status_code=404)

        return await guacamole_service.create_client_session(
            agent_id,
            state,
            resolve_public_base_url(request),
            force_fresh=force_fresh,
            refresh_tunnel=refresh_tunnel,
        )

    @router.delete("/guacamole/session/{auth_token}", response_model=GenericStatusResponse)
    async def api_guacamole_revoke_session(auth_token: str, request: Request):
        if not request_has_minimum_role(request, "operator"):
            return role_required_response("operator")
        if not guacamole_service.get_config().get("request_base_url"):
            return JSONResponse({"error": "Guacamole bridge is not configured"}, status_code=503)

        try:
            revoked = await guacamole_service.revoke_client_session(auth_token)
        except HTTPError as error:
            if error.code == 404:
                return {"ok": True, "revoked": False, "detail": "Token already invalidated"}
            return JSONResponse({"error": f"Guacamole token revoke failed with HTTP {error.code}"}, status_code=502)
        except URLError as error:
            return JSONResponse({"error": f"Could not reach Guacamole: {error.reason}"}, status_code=502)
        except RuntimeError as error:
            return JSONResponse({"error": str(error)}, status_code=503)
        except OSError as error:
            return JSONResponse({"error": f"Guacamole token revoke failed: {error}"}, status_code=502)

        return {"ok": True, "revoked": revoked}

    @router.post("/guacamole/session/{auth_token}/close", response_model=GenericStatusResponse)
    async def api_guacamole_close_session(auth_token: str, request: Request, delay_seconds: float = Query(5.0)):
        if not request_has_minimum_role(request, "operator"):
            return role_required_response("operator")
        scheduled = guacamole_service.schedule_session_close(auth_token, delay_seconds=delay_seconds)
        return {"ok": scheduled, "revoked": False, "detail": "Scheduled session close" if scheduled else "Invalid auth token"}

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
        return await asyncio.to_thread(guacamole_service.proxy_tunnel_request, request.method, raw_query, body, proxy_headers)

    return router