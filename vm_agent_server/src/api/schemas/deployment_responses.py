from __future__ import annotations

from typing import Any

from pydantic import Field

from vm_agent_server.src.api.schemas.task_responses import ApiResponseModel


class DeploymentResponse(ApiResponseModel):
    id: str
    agent_id: str = ""
    hostname: str = ""
    release_id: str | None = None
    tag_name: str = ""
    requested_by: str = "user"
    status: str = "queued"
    task_id: str | None = None
    commit_sha: str = ""
    artifact_dir: str = ""
    artifact_exe_path: str = ""
    package_zip_path: str = ""
    bootstrap_path: str = ""
    install_script_path: str = ""
    installer_copy_path: str = ""
    error: str | None = None
    build_log: str = ""
    created_at: int | None = None
    started_at: int | None = None
    completed_at: int | None = None


class AgentReleaseResponse(ApiResponseModel):
    id: str
    version: str = ""
    tag_name: str = ""
    commit_sha: str = ""
    artifact_url: str = ""
    artifact_sha256: str = ""
    workflow_run_id: str | None = None
    created_at: int | None = None
    published_at: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeploymentConfigResponse(ApiResponseModel):
    default_repo_url: str = ""
    artifact_share_root: str = ""
    latest_installer_share_template: str = ""
    active_deployment: DeploymentResponse | None = None
    latest_release: AgentReleaseResponse | None = None
    releases: list[AgentReleaseResponse] = Field(default_factory=list)


class DeploymentReleasesResponse(ApiResponseModel):
    repo_slug: str = ""
    repo_url: str = ""
    latest_release: AgentReleaseResponse | None = None
    releases: list[AgentReleaseResponse] = Field(default_factory=list)


class GuacamoleProvisioningDiagnosticsResponse(ApiResponseModel):
    available: bool
    deployment_id: str
    agent_id: str = ""
    hostname: str = ""
    data_source: str = ""
    detail: str | None = None
    group: dict[str, Any] = Field(default_factory=dict)
    connection: dict[str, Any] = Field(default_factory=dict)


class GenericStatusResponse(ApiResponseModel):
    ok: bool
    revoked: bool | None = None
    detail: str | None = None
    error: str | None = None


class GuacamoleConfigResponse(ApiResponseModel):
    enabled: bool
    configured: bool
    base_url: str = ""
    request_base_url: str = ""
    display: dict[str, Any] = Field(default_factory=dict)
    allow_embed: bool = True
    default_connection_mode: str = ""
    mapping_count: int = 0
    embed_template_configured: bool = False
    launch_template_configured: bool = False
    auth_username_configured: bool = False
    auth_password_configured: bool = False
    auth_provider: str = "default"
    connection_type: str = "c"
    recording: dict[str, Any] = Field(default_factory=dict)
    websocket_tunnel_url: str = ""
    http_tunnel_url: str = ""
    notes: list[str] = Field(default_factory=list)


class GuacamoleRecordingEntryResponse(ApiResponseModel):
    agent_id: str = ""
    username: str = ""
    owner: dict[str, Any] = Field(default_factory=dict)
    name: str = ""
    relative_path: str = ""
    size_bytes: int | None = None
    modified_at: int | None = None
    download_url: str = ""


class GuacamoleRecordingsResponse(ApiResponseModel):
    enabled: bool = False
    configured: bool = False
    browse_url: str = ""
    entry_count: int = 0
    entries: list[GuacamoleRecordingEntryResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GuacamoleSessionStatusResponse(ApiResponseModel):
    active: bool = False
    close_reason: str = ""