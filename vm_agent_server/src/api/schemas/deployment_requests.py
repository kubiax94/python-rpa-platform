from __future__ import annotations

from pydantic import Field

from vm_agent_server.src.api.schemas.task_requests import ApiRequestModel


class PrepareDeploymentRequest(ApiRequestModel):
    hostname: str = Field(min_length=1)
    agent_id: str | None = None
    display_name: str | None = None
    guacamole_target_host: str | None = None
    guacamole_username: str | None = None
    guacamole_domain: str | None = None
    guacamole_password: str | None = None
    guacamole_secret: str | None = None
    guacamole_group_name: str | None = None
    guacamole_connection_name: str | None = None
    release_id: str | None = None
    requested_by: str = "user"