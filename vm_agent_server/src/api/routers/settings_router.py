from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from vm_agent_server.src.api.schemas.settings_requests import UpdateServerSettingsRequest
from vm_agent_server.src.api.schemas.settings_responses import ServerSettingsResponse
from vm_agent_server.src.settings.models import (
    AzureSsoPatch,
    DeploymentDefaultsPatch,
    GuacamoleSettingsPatch,
    GuacamoleRecordingSettingsPatch,
    IdentitySettingsPatch,
    ServerSettings,
    ServerSettingsPatch,
)
from vm_agent_server.src.settings.service import ServerSettingsService


def build_settings_router(server_settings_service: ServerSettingsService, user_service) -> APIRouter:
    router = APIRouter(prefix="/api")

    def _build_response_payload(settings: ServerSettings) -> dict[str, object]:
        snapshot = settings.model_dump(mode="json")
        snapshot["identity"] = user_service.build_settings_response_identity(settings.identity)
        return snapshot

    @router.get("/settings/server", response_model=ServerSettingsResponse)
    async def api_get_server_settings(request: Request):
        session = getattr(request.state, "user_session", None)
        if session is None or "admin" not in set(session.user.roles):
            return JSONResponse({"error": "Admin role required"}, status_code=403)
        return _build_response_payload(server_settings_service.get_snapshot())

    @router.patch("/settings/server", response_model=ServerSettingsResponse)
    async def api_update_server_settings(body: UpdateServerSettingsRequest, request: Request):
        session = getattr(request.state, "user_session", None)
        if session is None or "admin" not in set(session.user.roles):
            return JSONResponse({"error": "Admin role required"}, status_code=403)
        current_settings = server_settings_service.get_snapshot()
        identity_patch = None
        if body.identity:
            requested_identity_patch = IdentitySettingsPatch(
                session_ttl_seconds=body.identity.session_ttl_seconds,
                azure=(AzureSsoPatch.model_validate(body.identity.azure.model_dump(exclude_none=True)) if body.identity.azure else None),
            )
            identity_patch = user_service.prepare_identity_patch(current_settings.identity, requested_identity_patch)

        patch = ServerSettingsPatch(
            deployment=(DeploymentDefaultsPatch.model_validate(body.deployment.model_dump(exclude_none=True)) if body.deployment else None),
            identity=identity_patch,
            guacamole=(GuacamoleSettingsPatch.model_validate(body.guacamole.model_dump(exclude_none=True)) if body.guacamole else None),
        )

        if identity_patch is None:
            updated = await server_settings_service.update(patch)
            return _build_response_payload(updated)

        next_payload = current_settings.model_dump(mode="python")
        if patch.deployment:
            deployment_patch = patch.deployment.model_dump(exclude_none=True)
            next_payload["deployment"] = {
                **dict(next_payload.get("deployment") or {}),
                **deployment_patch,
            }
        next_payload["identity"] = user_service.build_identity_payload_after_update(current_settings.identity, identity_patch)
        updated = await server_settings_service.replace(ServerSettings.model_validate(next_payload))
        return _build_response_payload(updated)

    return router