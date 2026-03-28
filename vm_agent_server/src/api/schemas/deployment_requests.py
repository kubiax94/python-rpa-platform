from __future__ import annotations

from pydantic import Field

from vm_agent_server.src.api.schemas.task_requests import ApiRequestModel


class PrepareDeploymentRequest(ApiRequestModel):
    hostname: str = Field(min_length=1)
    agent_id: str | None = None
    display_name: str | None = None
    repo_url: str | None = None
    source_ref: str = "main"
    requested_by: str = "user"