from __future__ import annotations

from vm_agent_server.src.api.schemas.task_responses import ApiResponseModel


class AgentTokenRotationResponse(ApiResponseModel):
    ok: bool
    agent_id: str
    token_version: int
    rotated_at: int