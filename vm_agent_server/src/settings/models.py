from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


MICROSOFT_SSO_REDIRECT_PATH = "/api/users/callback/microsoft"


class DeploymentDefaultsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    default_repo_url: str = ""
    default_source_ref: str = "main"
    artifact_share_root: str = ""
    latest_installer_share_template: str = ""


class IdentityGroupRoleMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    group_object_id: str = ""
    group_name: str = ""
    app_roles: list[str] = Field(default_factory=list)


class AzureSsoSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    authority_url: str = ""
    redirect_path: str = MICROSOFT_SSO_REDIRECT_PATH
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email"])
    group_role_mappings: list[IdentityGroupRoleMapping] = Field(default_factory=list)
    activated_at: int | None = None


class IdentitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider: Literal["local_bootstrap", "azure_entra"] = "local_bootstrap"
    provider_locked: bool = False
    session_ttl_seconds: int = 43200
    azure: AzureSsoSettings = AzureSsoSettings()


class GuacamoleRecordingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    enabled: bool = False
    browse_url: str = ""
    path_template: str = ""
    name_template: str = "{connection_name}-{timestamp}.guac"
    create_path: bool = True
    exclude_output: bool = False
    exclude_mouse: bool = False
    exclude_touch: bool = False
    include_keys: bool = True


class GuacamoleDisplaySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mode: Literal["dynamic", "fixed"] = "dynamic"
    width: int | None = None
    height: int | None = None
    dpi: int = 96


class GuacamoleSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display: GuacamoleDisplaySettings = GuacamoleDisplaySettings()
    recording: GuacamoleRecordingSettings = GuacamoleRecordingSettings()


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deployment: DeploymentDefaultsSettings = DeploymentDefaultsSettings()
    identity: IdentitySettings = IdentitySettings()
    guacamole: GuacamoleSettings = GuacamoleSettings()


class DeploymentDefaultsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    default_repo_url: str | None = None
    default_source_ref: str | None = None
    artifact_share_root: str | None = None
    latest_installer_share_template: str | None = None


class IdentityGroupRoleMappingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    group_object_id: str | None = None
    group_name: str | None = None
    app_roles: list[str] | None = None


class AzureSsoPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    authority_url: str | None = None
    redirect_path: str | None = None
    scopes: list[str] | None = None
    group_role_mappings: list[IdentityGroupRoleMappingPatch] | None = None
    activate: bool | None = None


class IdentitySettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_ttl_seconds: int | None = None
    azure: AzureSsoPatch | None = None


class GuacamoleRecordingSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    enabled: bool | None = None
    browse_url: str | None = None
    path_template: str | None = None
    name_template: str | None = None
    create_path: bool | None = None
    exclude_output: bool | None = None
    exclude_mouse: bool | None = None
    exclude_touch: bool | None = None
    include_keys: bool | None = None


class GuacamoleDisplaySettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mode: Literal["dynamic", "fixed"] | None = None
    width: int | None = None
    height: int | None = None
    dpi: int | None = None


class GuacamoleSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display: GuacamoleDisplaySettingsPatch | None = None
    recording: GuacamoleRecordingSettingsPatch | None = None


class ServerSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deployment: DeploymentDefaultsPatch | None = None
    identity: IdentitySettingsPatch | None = None
    guacamole: GuacamoleSettingsPatch | None = None