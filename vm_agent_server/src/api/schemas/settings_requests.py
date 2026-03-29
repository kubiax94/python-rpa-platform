from __future__ import annotations

from pydantic import Field

from vm_agent_server.src.api.schemas.task_requests import ApiRequestModel


class DeploymentDefaultsPatchRequest(ApiRequestModel):
    default_repo_url: str | None = None
    default_source_ref: str | None = Field(default=None, min_length=1)
    artifact_share_root: str | None = None
    latest_installer_share_template: str | None = None


class IdentityGroupRoleMappingRequest(ApiRequestModel):
    group_object_id: str | None = None
    group_name: str | None = None
    app_roles: list[str] | None = None


class AzureSsoPatchRequest(ApiRequestModel):
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    authority_url: str | None = None
    redirect_path: str | None = None
    scopes: list[str] | None = None
    group_role_mappings: list[IdentityGroupRoleMappingRequest] | None = None
    activate: bool | None = None


class IdentitySettingsPatchRequest(ApiRequestModel):
    session_ttl_seconds: int | None = Field(default=None, ge=900, le=604800)
    azure: AzureSsoPatchRequest | None = None


class UpdateServerSettingsRequest(ApiRequestModel):
    deployment: DeploymentDefaultsPatchRequest | None = None
    identity: IdentitySettingsPatchRequest | None = None