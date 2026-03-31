from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UserIdentity(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    subject: str
    username: str
    display_name: str = ""
    email: str = ""
    avatar_url: str = ""
    avatar_initials: str = ""
    auth_provider: str
    roles: list[str] = Field(default_factory=list)
    group_ids: list[str] = Field(default_factory=list)
    group_names: list[str] = Field(default_factory=list)
    claims: dict[str, Any] = Field(default_factory=dict)


class UserSession(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    access_token: str
    user: UserIdentity
    created_at: int = Field(default_factory=lambda: int(time.time()))
    expires_at: int
    last_seen_at: int = Field(default_factory=lambda: int(time.time()))


class PendingOidcLogin(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    state: str
    nonce: str
    code_verifier: str
    redirect_uri: str
    return_to: str
    created_at: int = Field(default_factory=lambda: int(time.time()))
    expires_at: int


class PublicAuthConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    provider: str = "local_bootstrap"
    provider_locked: bool = False
    local_bootstrap_available: bool = False
    azure_configured: bool = False
    azure_active: bool = False
    microsoft_login_available: bool = False
    client_id_configured: bool = False
    tenant_id_configured: bool = False
    client_secret_configured: bool = False
    group_mapping_count: int = 0
