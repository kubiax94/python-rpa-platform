from __future__ import annotations

import asyncio
from collections.abc import Callable
from urllib.error import HTTPError, URLError

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from vm_agent_server.src.api.schemas.deployment_responses import GenericStatusResponse, GuacamoleConfigResponse, GuacamoleRecordingsResponse, GuacamoleSessionStatusResponse
from vm_agent_server.src.authz import request_has_minimum_role, role_required_response
from vm_agent_server.src.guacamole.bridge import list_guacamole_recordings, list_vm_user_sessions, open_guacamole_recording
from vm_agent_server.src.services.guacamole_service import GuacamoleService
from vm_agent_server.src.users.service import UserService


def _build_recording_filename(path: str) -> str:
    filename = path.replace("\\", "/").split("/")[-1].strip() or "recording"
    if filename.casefold().endswith(".guac"):
        return filename
    return f"{filename}.guac"


def _get_actor_label(request: Request) -> str:
    session = getattr(request.state, "user_session", None)
    if session is None:
        return "an administrator"

    user = session.user
    for value in (user.display_name, user.username, user.email, user.subject):
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned
    return "an administrator"


def build_guacamole_router(
    get_agent_state,
    get_agent_record,
    resolve_public_base_url: Callable[[Request], str],
    guacamole_service: GuacamoleService,
    user_service: UserService,
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
        if not request_has_minimum_role(request, "admin"):
            return role_required_response("admin")
        return guacamole_service.list_tracked_sessions()

    @router.get("/guacamole/recordings", response_model=GuacamoleRecordingsResponse)
    async def api_guacamole_recordings(
        request: Request,
        agent_id: str = Query(""),
        username: str = Query(""),
    ):
        if not request_has_minimum_role(request, "viewer"):
            return role_required_response("viewer")
        payload = await asyncio.to_thread(
            list_guacamole_recordings,
            resolve_public_base_url(request),
            agent_id=agent_id,
            username=username,
        )
        return guacamole_service.annotate_recording_inventory(payload)

    @router.get("/guacamole/recordings/download")
    async def api_guacamole_recording_download(request: Request, path: str = Query("")):
        if not request_has_minimum_role(request, "viewer"):
            return role_required_response("viewer")
        try:
            upstream = await asyncio.to_thread(open_guacamole_recording, path)
        except HTTPError as error:
            if error.code == 404:
                return JSONResponse({"error": "Recording not found"}, status_code=404)
            return JSONResponse({"error": f"Recording download failed with HTTP {error.code}"}, status_code=502)
        except URLError as error:
            return JSONResponse({"error": f"Could not reach recording host: {error.reason}"}, status_code=502)
        except RuntimeError as error:
            return JSONResponse({"error": str(error)}, status_code=503)
        except OSError as error:
            return JSONResponse({"error": f"Recording download failed: {error}"}, status_code=502)

        filename = _build_recording_filename(path)
        content_type = upstream.headers.get_content_type() or "application/octet-stream"

        def iter_stream():
            try:
                while True:
                    chunk = upstream.read(64 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                upstream.close()

        return StreamingResponse(
            iter_stream(),
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    @router.post("/guacamole/tracked-sessions/kill-all")
    async def api_guacamole_kill_all_tracked_sessions(request: Request):
        if not request_has_minimum_role(request, "admin"):
            return role_required_response("admin")
        closed_count = await guacamole_service.close_tracked_sessions(close_reason=f"Session closed by {_get_actor_label(request)}")
        return {"ok": True, "closed_count": closed_count}

    @router.get("/agents/{agent_id}/guacamole")
    async def api_agent_guacamole(agent_id: str):
        state = await build_agent_context(agent_id)
        if state is None:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return guacamole_service.build_session(agent_id, state)

    @router.get("/agents/{agent_id}/guacamole/user-sessions")
    async def api_agent_guacamole_user_sessions(agent_id: str, request: Request):
        if not request_has_minimum_role(request, "viewer"):
            return role_required_response("viewer")
        state = await build_agent_context(agent_id)
        if state is None:
            return JSONResponse({"error": "Not found"}, status_code=404)

        tracked_sessions = guacamole_service.rdp_monitor.get_sessions_for_agent(agent_id)

        return {
            "agent_id": agent_id,
            "sessions": list_vm_user_sessions(
                agent_id,
                state,
                active_identities=user_service.list_active_identities(),
                tracked_sessions=[
                    {
                        "connection_id": tracked_session.connection_id,
                        "username": tracked_session.username,
                        "owner": tracked_session.owner,
                    }
                    for tracked_session in tracked_sessions
                ],
                maintain_connections=True,
            ),
        }

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
        connection_id: str = Query(""),
        vm_username: str = Query(""),
        read_only: bool = Query(False),
        recorded: bool = Query(False),
    ):
        if not request_has_minimum_role(request, "operator"):
            return role_required_response("operator")
        state = await build_agent_context(agent_id)
        if state is None:
            return JSONResponse({"error": "Not found"}, status_code=404)

        enforced_read_only = read_only or not request_has_minimum_role(request, "admin")
        if recorded:
            enforced_read_only = True

        return await guacamole_service.create_client_session(
            agent_id,
            state,
            resolve_public_base_url(request),
            user_session=getattr(request.state, "user_session", None),
            force_fresh=force_fresh,
            refresh_tunnel=refresh_tunnel,
            connection_id=connection_id,
            vm_username=vm_username,
            read_only=enforced_read_only,
            recorded=recorded,
        )

    @router.post("/agents/{agent_id}/guacamole/tracked-sessions/{owner_subject}/kick", response_model=GenericStatusResponse)
    async def api_agent_guacamole_kick_owner_session(agent_id: str, owner_subject: str, request: Request):
        if not request_has_minimum_role(request, "admin"):
            return role_required_response("admin")

        closed = await guacamole_service.close_agent_owner_session(
            agent_id,
            owner_subject,
            close_reason=f"Session closed by {_get_actor_label(request)}",
        )
        return {
            "ok": closed,
            "revoked": False,
            "detail": "Session closed" if closed else "No tracked session matched that user on this agent",
        }

    @router.delete("/guacamole/session/{auth_token}", response_model=GenericStatusResponse)
    async def api_guacamole_revoke_session(auth_token: str, request: Request):
        if not request_has_minimum_role(request, "operator"):
            return role_required_response("operator")
        if not guacamole_service.get_config().get("request_base_url"):
            return JSONResponse({"error": "Guacamole bridge is not configured"}, status_code=503)

        tracked_session = guacamole_service.rdp_monitor.get_session(auth_token)
        request_user = getattr(getattr(request.state, "user_session", None), "user", None)
        request_subject = str(getattr(request_user, "subject", "") or "").strip()
        owner_subject = str(((tracked_session.owner or {}) if tracked_session else {}).get("subject") or "").strip()
        if tracked_session is not None and owner_subject and owner_subject != request_subject and not request_has_minimum_role(request, "admin"):
            return role_required_response("admin")

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
        tracked_session = guacamole_service.rdp_monitor.get_session(auth_token)
        request_user = getattr(getattr(request.state, "user_session", None), "user", None)
        request_subject = str(getattr(request_user, "subject", "") or "").strip()
        owner_subject = str(((tracked_session.owner or {}) if tracked_session else {}).get("subject") or "").strip()
        if tracked_session is not None and owner_subject and owner_subject != request_subject and not request_has_minimum_role(request, "admin"):
            return role_required_response("admin")
        scheduled = guacamole_service.schedule_session_close(auth_token, delay_seconds=delay_seconds)
        return {"ok": scheduled, "revoked": False, "detail": "Scheduled session close" if scheduled else "Invalid auth token"}

    @router.get("/guacamole/session/{auth_token}/status", response_model=GuacamoleSessionStatusResponse)
    async def api_guacamole_session_status(auth_token: str, request: Request):
        if not request_has_minimum_role(request, "viewer"):
            return role_required_response("viewer")

        tracked_session = guacamole_service.rdp_monitor.get_session(auth_token)
        if tracked_session is not None:
            return {"active": True, "close_reason": ""}

        return {
            "active": False,
            "close_reason": guacamole_service.get_recent_close_reason(auth_token),
        }

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