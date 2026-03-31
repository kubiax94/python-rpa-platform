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


class GuacamoleRecordingSettingsPatchRequest(ApiRequestModel):
    enabled: bool | None = None
    browse_url: str | None = None
    path_template: str | None = None
    name_template: str | None = None
    create_path: bool | None = None
    exclude_output: bool | None = None
    exclude_mouse: bool | None = None
    exclude_touch: bool | None = None
    include_keys: bool | None = None


class GuacamoleDisplaySettingsPatchRequest(ApiRequestModel):
    mode: str | None = Field(default=None, pattern="^(dynamic|fixed)$")
    width: int | None = Field(default=None, ge=1, le=16384)
    height: int | None = Field(default=None, ge=1, le=16384)
    dpi: int | None = Field(default=None, ge=1, le=1000)


class GuacamoleSettingsPatchRequest(ApiRequestModel):
    display: GuacamoleDisplaySettingsPatchRequest | None = None
    recording: GuacamoleRecordingSettingsPatchRequest | None = None


class UpdateServerSettingsRequest(ApiRequestModel):
    deployment: DeploymentDefaultsPatchRequest | None = None
    identity: IdentitySettingsPatchRequest | None = None
    guacamole: GuacamoleSettingsPatchRequest | None = None