from __future__ import annotations

from vm_agent_server.src.api.schemas.task_responses import ApiResponseModel


class DeploymentDefaultsResponse(ApiResponseModel):
    default_repo_url: str = ""
    default_source_ref: str = "main"
    artifact_share_root: str = ""
    latest_installer_share_template: str = ""


class IdentityGroupRoleMappingResponse(ApiResponseModel):
    group_object_id: str = ""
    group_name: str = ""
    app_roles: list[str] = []


class AzureSsoSettingsResponse(ApiResponseModel):
    tenant_id: str = ""
    client_id: str = ""
    authority_url: str = ""
    redirect_path: str = "/api/users/callback/microsoft"
    scopes: list[str] = ["openid", "profile", "email"]
    group_role_mappings: list[IdentityGroupRoleMappingResponse] = []
    client_secret_configured: bool = False
    activated_at: int | None = None
    active: bool = False


class IdentitySettingsResponse(ApiResponseModel):
    provider: str = "local_bootstrap"
    provider_locked: bool = False
    session_ttl_seconds: int = 43200
    local_bootstrap_available: bool = False
    azure: AzureSsoSettingsResponse = AzureSsoSettingsResponse()


class ServerSettingsResponse(ApiResponseModel):
    deployment: DeploymentDefaultsResponse = DeploymentDefaultsResponse()
    identity: IdentitySettingsResponse = IdentitySettingsResponse()