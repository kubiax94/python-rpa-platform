from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from vm_agent_server.src.agent_registry_db import AgentRegistryDB
from vm_agent_server.src.api.schemas.deployment_requests import PrepareDeploymentRequest
from vm_agent_server.src.api.schemas.deployment_responses import DeploymentConfigResponse, DeploymentResponse
from vm_agent_server.src.api.schemas.query_params import DeploymentListQuery
from vm_agent_server.src.deployment_service import DeploymentService


def build_deployment_router(
    deployment_service: DeploymentService,
    registry_db: AgentRegistryDB,
    resolve_agent_ws_url,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/deployments/prepare", response_model=DeploymentResponse)
    async def api_prepare_deployment(body: PrepareDeploymentRequest, request: Request):
        hostname = body.hostname
        agent_id = (body.agent_id or hostname).strip()
        display_name = (body.display_name or hostname).strip()
        repo_url = (body.repo_url or deployment_service.get_default_repo_url()).strip()
        source_ref = body.source_ref.strip() or "main"
        requested_by = body.requested_by.strip() or "user"

        try:
            deployment = await deployment_service.prepare_deployment(
                agent_id=agent_id,
                hostname=hostname,
                display_name=display_name,
                repo_url=repo_url,
                source_ref=source_ref,
                requested_by=requested_by,
                server_ws_url=resolve_agent_ws_url(request),
            )
        except RuntimeError as exc:
            active = await registry_db.get_active_deployment()
            return JSONResponse({"error": str(exc), "active_deployment": active}, status_code=409)
        return deployment

    @router.get("/deployments/config", response_model=DeploymentConfigResponse)
    async def api_get_deployment_config():
        return await deployment_service.get_prepare_config()

    @router.get("/deployments", response_model=list[DeploymentResponse])
    async def api_list_deployments(query: Annotated[DeploymentListQuery, Depends()]):
        return await registry_db.get_deployments(agent_id=query.agent_id, limit=query.limit)

    @router.get("/deployments/{deployment_id}", response_model=DeploymentResponse)
    async def api_get_deployment(deployment_id: str):
        deployment = await registry_db.get_deployment(deployment_id)
        if not deployment:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return deployment

    @router.get("/deployments/{deployment_id}/installer")
    async def api_get_deployment_installer(deployment_id: str):
        deployment = await registry_db.get_deployment(deployment_id)
        if not deployment:
            return JSONResponse({"error": "Not found"}, status_code=404)

        candidate_path = deployment.get("installer_copy_path") or deployment.get("install_script_path")
        if not candidate_path:
            return JSONResponse({"error": "Installer script not available"}, status_code=404)

        installer_path = Path(candidate_path)
        if not installer_path.exists():
            return JSONResponse({"error": "Installer script not found on disk"}, status_code=404)

        return PlainTextResponse(installer_path.read_text(encoding="utf-8"), media_type="text/plain")

    return router