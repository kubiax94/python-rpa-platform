from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from vm_agent_server.src.api.schemas.agent_registry_requests import AgentRegistryUpdateRequest
from vm_agent_server.src.api.schemas.agent_responses import AgentTokenRotationResponse
from vm_agent_server.src.authz import request_has_agent_visibility, request_has_minimum_role, role_required_response


def build_agent_runtime_router(
    telemetry_db,
    registry_db,
    agent_runtime,
    frontend_snapshot_event,
    reprovision_guacamole_mapping: Callable[[str, str, dict[str, Any]], Any],
    logger: logging.Logger,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/metrics")
    async def api_metrics(
        request: Request,
        agent_id: str,
        pid: int = None,
        from_ts: int = None,
        to_ts: int = None,
        limit: int = Query(default=50000, le=100000),
    ):
        if not request_has_minimum_role(request, "viewer"):
            return role_required_response("viewer")
        if not request_has_agent_visibility(request):
            return JSONResponse([])
        rows = await telemetry_db.get_metrics(agent_id, pid, from_ts, to_ts, limit)
        return JSONResponse(rows)

    @router.get("/events")
    async def api_events(
        request: Request,
        agent_id: str = None,
        event_type: str = None,
        from_ts: int = None,
        to_ts: int = None,
        limit: int = Query(default=200, le=5000),
    ):
        if not request_has_minimum_role(request, "viewer"):
            return role_required_response("viewer")
        if not request_has_agent_visibility(request):
            return JSONResponse([])
        rows = await telemetry_db.get_events(agent_id, event_type, from_ts, to_ts, limit)
        return JSONResponse(rows)

    @router.get("/agents/summary")
    async def api_agents_summary(request: Request):
        if not request_has_minimum_role(request, "viewer"):
            return role_required_response("viewer")
        if not request_has_agent_visibility(request):
            return JSONResponse([])
        rows = await telemetry_db.get_agents_summary()
        return JSONResponse(rows)

    @router.get("/agents/{agent_id}")
    async def api_agent_state(agent_id: str, request: Request):
        if not request_has_minimum_role(request, "viewer"):
            return role_required_response("viewer")
        if not request_has_agent_visibility(request):
            return JSONResponse({"error": "Not found"}, status_code=404)
        state = agent_runtime.get_agent_state(agent_id)
        if state is None:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return JSONResponse(state)

    @router.get("/agent-registry")
    async def api_agent_registry(request: Request, limit: int = Query(default=200, le=500)):
        if not request_has_minimum_role(request, "viewer"):
            return role_required_response("viewer")
        if not request_has_agent_visibility(request):
            return JSONResponse([])
        return JSONResponse(await registry_db.get_agents(limit))

    @router.get("/agent-registry/{agent_id}")
    async def api_agent_registry_item(agent_id: str, request: Request):
        if not request_has_minimum_role(request, "viewer"):
            return role_required_response("viewer")
        if not request_has_agent_visibility(request):
            return JSONResponse({"error": "Not found"}, status_code=404)
        item = await registry_db.get_agent(agent_id)
        if not item:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return JSONResponse(item)

    @router.patch("/agent-registry/{agent_id}")
    async def api_update_agent_registry_item(agent_id: str, body: AgentRegistryUpdateRequest, request: Request):
        if not request_has_minimum_role(request, "admin"):
            return role_required_response("admin")

        existing = await registry_db.get_agent(agent_id)
        if not existing:
            return JSONResponse({"error": "Not found"}, status_code=404)

        hostname = body.hostname.strip() if isinstance(body.hostname, str) else ""
        display_name = body.display_name.strip() if isinstance(body.display_name, str) else ""
        metadata = None
        if body.guacamole_access is not None:
            metadata = {
                "guacamole": {
                    "access": body.guacamole_access.model_dump(mode="python", exclude_none=True),
                },
            }

        await registry_db.upsert_agent(agent_id, hostname=hostname, display_name=display_name, metadata=metadata)
        updated = await registry_db.get_agent(agent_id)

        if updated:
            updated_metadata = updated.get("metadata") if isinstance(updated.get("metadata"), dict) else {}
            guacamole_mapping = updated_metadata.get("guacamole") if isinstance(updated_metadata.get("guacamole"), dict) else {}
            if guacamole_mapping:
                provision_hostname = str(updated.get("hostname") or guacamole_mapping.get("target_host") or agent_id).strip() or agent_id
                try:
                    refreshed_mapping, _ = await asyncio.to_thread(
                        reprovision_guacamole_mapping,
                        agent_id,
                        provision_hostname,
                        guacamole_mapping,
                    )
                    await registry_db.upsert_agent(agent_id, metadata={"guacamole": refreshed_mapping})
                    updated = await registry_db.get_agent(agent_id)
                except Exception as error:
                    logger.warning("Failed to reprovision Guacamole connection for agent %s after registry update: %s", agent_id, error)

        return JSONResponse(updated or {"id": agent_id})

    @router.delete("/agent-registry/{agent_id}")
    async def api_delete_agent_registry_item(agent_id: str, request: Request):
        if not request_has_minimum_role(request, "admin"):
            return role_required_response("admin")

        existing = await registry_db.get_agent(agent_id)
        if not existing:
            return JSONResponse({"error": "Not found"}, status_code=404)

        await agent_runtime.timeout_agent(agent_id)
        agent_runtime.remove_agent(agent_id)
        await registry_db.delete_agent(agent_id)
        frontend_snapshot_event.set()
        return JSONResponse({"deleted": True, "agent_id": agent_id})

    @router.post("/agent-registry/{agent_id}/rotate-token", response_model=AgentTokenRotationResponse)
    async def api_rotate_agent_token(agent_id: str, request: Request):
        if not request_has_minimum_role(request, "admin"):
            return role_required_response("admin")
        rotated = await registry_db.rotate_agent_token_version(agent_id)
        if not rotated:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return {"ok": True, **rotated}

    return router
