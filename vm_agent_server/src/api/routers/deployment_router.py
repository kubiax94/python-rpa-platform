from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from vm_agent_server.src.persistence.agent_registry_db import AgentRegistryDB
from vm_agent_server.src.api.schemas.deployment_requests import PrepareDeploymentRequest
from vm_agent_server.src.api.schemas.deployment_responses import (
    DeploymentConfigResponse,
    DeploymentReleasesResponse,
    DeploymentResponse,
    GuacamoleProvisioningDiagnosticsResponse,
)
from vm_agent_server.src.api.schemas.query_params import DeploymentListQuery
from vm_agent_server.src.authz import request_has_minimum_role, role_required_response
from vm_agent_server.src.services.deployment_service import DeploymentService


def build_deployment_router(
    deployment_service: DeploymentService,
    registry_db: AgentRegistryDB,
    resolve_agent_ws_url,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/deployments/prepare", response_model=DeploymentResponse)
    async def api_prepare_deployment(body: PrepareDeploymentRequest, request: Request):
        if not request_has_minimum_role(request, "operator"):
            return role_required_response("operator")
        hostname = body.hostname
        agent_id = (body.agent_id or hostname).strip()
        display_name = (body.display_name or hostname).strip()
        guacamole_target_host = (body.guacamole_target_host or hostname).strip()
        guacamole_username = (body.guacamole_username or "").strip()
        guacamole_domain = (body.guacamole_domain or "").strip()
        guacamole_password = (body.guacamole_password or "").strip()
        guacamole_secret = (body.guacamole_secret or "").strip()
        guacamole_group_name = (body.guacamole_group_name or agent_id).strip()
        guacamole_connection_name = (body.guacamole_connection_name or hostname).strip()
        release_id = (body.release_id or "").strip() or None
        requested_by = body.requested_by.strip() or "user"

        try:
            deployment = await deployment_service.prepare_deployment(
                agent_id=agent_id,
                hostname=hostname,
                display_name=display_name,
                guacamole_target_host=guacamole_target_host,
                guacamole_username=guacamole_username,
                guacamole_domain=guacamole_domain,
                guacamole_password=guacamole_password,
                guacamole_secret=guacamole_secret,
                guacamole_group_name=guacamole_group_name,
                guacamole_connection_name=guacamole_connection_name,
                release_id=release_id,
                requested_by=requested_by,
                server_ws_url=resolve_agent_ws_url(request),
            )
        except RuntimeError as exc:
            active = await registry_db.get_active_deployment()
            if active:
                return JSONResponse({"error": str(exc), "active_deployment": active}, status_code=409)
            return JSONResponse({"error": str(exc)}, status_code=502)
        return deployment

    @router.get("/deployments/config", response_model=DeploymentConfigResponse)
    async def api_get_deployment_config():
        return await deployment_service.get_prepare_config()

    @router.get("/deployments/releases", response_model=DeploymentReleasesResponse)
    async def api_get_deployment_releases():
        return await deployment_service.get_releases_config()

    @router.get("/deployments/releases/{release_id}/artifact")
    async def api_proxy_release_artifact(release_id: str, request: Request):
        if not request_has_minimum_role(request, "operator"):
            return role_required_response("operator")

        try:
            artifact_path, asset_name = await deployment_service.get_release_artifact_proxy(release_id)
        except RuntimeError as exc:
            detail = str(exc)
            status_code = 404 if "Release not found" in detail else 502
            return JSONResponse({"error": detail}, status_code=status_code)

        if not artifact_path.exists():
            return JSONResponse({"error": "Release artifact not found on disk"}, status_code=404)

        return FileResponse(
            artifact_path,
            media_type="application/octet-stream",
            filename=asset_name,
        )

    @router.get("/deployments", response_model=list[DeploymentResponse])
    async def api_list_deployments(query: Annotated[DeploymentListQuery, Depends()]):
        return await registry_db.get_deployments(agent_id=query.agent_id, limit=query.limit)

    @router.get("/deployments/{deployment_id}", response_model=DeploymentResponse)
    async def api_get_deployment(deployment_id: str):
        deployment = await registry_db.get_deployment(deployment_id)
        if not deployment:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return deployment

    @router.get("/deployments/{deployment_id}/guacamole/provisioning", response_model=GuacamoleProvisioningDiagnosticsResponse)
    async def api_get_deployment_guacamole_provisioning(deployment_id: str):
        deployment = await registry_db.get_deployment(deployment_id)
        if not deployment:
            return JSONResponse({"error": "Not found"}, status_code=404)

        metadata = deployment.get("metadata") if isinstance(deployment.get("metadata"), dict) else {}
        diagnostics = metadata.get("guacamole_provisioning") if isinstance(metadata.get("guacamole_provisioning"), dict) else None
        if not diagnostics:
            return {
                "available": False,
                "deployment_id": deployment_id,
                "agent_id": str(deployment.get("agent_id") or ""),
                "hostname": str(deployment.get("hostname") or ""),
                "detail": "No Guacamole provisioning diagnostics recorded for this deployment.",
                "group": {},
                "connection": {},
            }

        return {
            "available": True,
            "deployment_id": deployment_id,
            "agent_id": str(deployment.get("agent_id") or ""),
            "hostname": str(deployment.get("hostname") or ""),
            "data_source": str(diagnostics.get("data_source") or ""),
            "detail": diagnostics.get("detail"),
            "group": diagnostics.get("group") if isinstance(diagnostics.get("group"), dict) else {},
            "connection": diagnostics.get("connection") if isinstance(diagnostics.get("connection"), dict) else {},
        }

    @router.get("/deployments/{deployment_id}/installer")
    async def api_get_deployment_installer(deployment_id: str, request: Request):
        if not request_has_minimum_role(request, "operator"):
            return role_required_response("operator")
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

    @router.get("/deployments/{deployment_id}/package")
    async def api_get_deployment_package(deployment_id: str, request: Request):
        if not request_has_minimum_role(request, "operator"):
            return role_required_response("operator")
        deployment = await registry_db.get_deployment(deployment_id)
        if not deployment:
            return JSONResponse({"error": "Not found"}, status_code=404)

        candidate_path = deployment.get("package_zip_path")
        if not candidate_path:
            return JSONResponse({"error": "Package ZIP not available"}, status_code=404)

        package_path = Path(candidate_path)
        if not package_path.exists():
            return JSONResponse({"error": "Package ZIP not found on disk"}, status_code=404)

        return FileResponse(
            package_path,
            media_type="application/zip",
            filename=f"deployment-{deployment_id}.zip",
        )

    return router