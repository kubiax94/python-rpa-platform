from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateTaskRequest(ApiRequestModel):
    agent_id: str = Field(min_length=1)
    script: str = Field(min_length=1)
    name: str = ""
    cwd: str = ""
    timeout_sec: int = Field(default=300, ge=1)
    session: str = ""
    requested_by: str = "user"
    env: dict[str, Any] = Field(default_factory=dict)


class PipelineStepRequest(ApiRequestModel):
    step_index: int = Field(default=0, ge=0)
    name: str = ""
    script: str = Field(min_length=1)
    cwd: str = ""
    timeout_sec: int = Field(default=300, ge=1)
    on_fail: Literal["stop", "continue", "retry"] = "stop"
    retry_count: int = Field(default=0, ge=0)


class CreatePipelineRequest(ApiRequestModel):
    name: str = "Unnamed Pipeline"
    description: str = ""
    created_by: str = "user"
    steps: list[PipelineStepRequest] = Field(min_length=1)


class RunPipelineRequest(ApiRequestModel):
    agent_id: str = Field(min_length=1)
    session: str = ""
    requested_by: str = "user"