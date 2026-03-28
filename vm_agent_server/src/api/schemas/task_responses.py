from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiResponseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class TaskComponentResponse(ApiResponseModel):
    type: str
    config: dict[str, Any] = Field(default_factory=dict)


class TaskResponse(ApiResponseModel):
    id: str
    pipeline_run_id: str | None = None
    step_index: int = 0
    agent_id: str
    session: str = ""
    name: str = ""
    script: str
    cwd: str = ""
    timeout_sec: int = 300
    config_id: str | None = None
    status: str
    pid: int | None = None
    exit_code: int | None = None
    error: str | None = None
    requested_by: str = "system"
    requested_from: str = ""
    created_at: int | None = None
    started_at: int | None = None
    completed_at: int | None = None
    kind: str = "agent"
    payload: dict[str, Any] = Field(default_factory=dict)
    components: list[TaskComponentResponse] = Field(default_factory=list)


class TaskLogResponse(ApiResponseModel):
    content: str
    offset: int
    size: int


class PipelineStepResponse(ApiResponseModel):
    id: int | None = None
    pipeline_id: str | None = None
    step_index: int
    name: str = ""
    script: str
    cwd: str = ""
    timeout_sec: int = 300
    on_fail: str = "stop"
    retry_count: int = 0


class PipelineResponse(ApiResponseModel):
    id: str
    name: str
    description: str = ""
    created_by: str | None = None
    created_at: int | None = None
    updated_at: int | None = None
    steps: list[PipelineStepResponse] | int | None = None


class PipelineRunResponse(ApiResponseModel):
    id: str
    pipeline_id: str
    agent_id: str
    session: str = ""
    status: str
    current_step: int = 0
    requested_by: str = "system"
    requested_from: str = ""
    created_at: int | None = None
    started_at: int | None = None
    completed_at: int | None = None
    tasks: list[TaskResponse] = Field(default_factory=list)


class AuditEntryResponse(ApiResponseModel):
    id: int
    ts: int
    entity_type: str
    entity_id: str
    action: str
    actor: str = "system"
    detail: str = ""
    ip_address: str = ""


class TaskCancelResponse(ApiResponseModel):
    ok: bool
    sent: bool


class PipelineRunLaunchResponse(ApiResponseModel):
    run_id: str
    task_id: str
    sent: bool