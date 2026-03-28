from __future__ import annotations

from pydantic import Field

from vm_agent_server.src.api.schemas.task_requests import ApiRequestModel


class TaskListQuery(ApiRequestModel):
    agent_id: str | None = None
    status: str | None = None
    limit: int = Field(default=50, ge=1, le=500)


class TaskLogQuery(ApiRequestModel):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=0, ge=0)


class PipelineListQuery(ApiRequestModel):
    limit: int = Field(default=50, ge=1, le=200)


class DeploymentListQuery(ApiRequestModel):
    agent_id: str | None = None
    limit: int = Field(default=100, ge=1, le=500)


class AuditLogQuery(ApiRequestModel):
    entity_type: str | None = None
    entity_id: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)