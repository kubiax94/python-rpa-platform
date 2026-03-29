from __future__ import annotations

from vm_agent_server.src.api.schemas.task_responses import ApiResponseModel


class UserIdentityResponse(ApiResponseModel):
    subject: str
    username: str
    display_name: str = ""
    email: str = ""
    auth_provider: str
    roles: list[str] = []
    group_ids: list[str] = []
    group_names: list[str] = []
    claims: dict[str, object] = {}


class UserSessionResponse(ApiResponseModel):
    access_token: str
    expires_at: int
    user: UserIdentityResponse


class PublicAuthConfigResponse(ApiResponseModel):
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


class BeginMicrosoftLoginResponse(ApiResponseModel):
    authorize_url: str


class LogoutResponse(ApiResponseModel):
    ok: bool