from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AgentPermissionRuleRequest(BaseModel):
    enabled: bool | None = None
    minimum_role: Literal["viewer", "operator", "admin"] | None = None
    users: list[str] | None = None
    groups: list[str] | None = None


class AgentGuacamoleAccessUpdateRequest(BaseModel):
    permissions: dict[str, AgentPermissionRuleRequest] | None = Field(default=None)


class AgentRegistryUpdateRequest(BaseModel):
    hostname: str | None = None
    display_name: str | None = None
    guacamole_access: AgentGuacamoleAccessUpdateRequest | None = None