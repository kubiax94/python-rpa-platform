from __future__ import annotations

from pydantic import Field

from vm_agent_server.src.api.schemas.task_requests import ApiRequestModel


class LocalLoginRequest(ApiRequestModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class BeginMicrosoftLoginRequest(ApiRequestModel):
    return_to: str = Field(min_length=1)