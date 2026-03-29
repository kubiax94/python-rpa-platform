from __future__ import annotations

import os

from shared.security.agent_jwt import TOKEN_PURPOSE_AGENT_WS, AgentJwtClaims, issue_agent_jwt, verify_agent_jwt

JWT_SECRET_ENV = "VM_AGENT_JWT_SECRET"
JWT_ISSUER_ENV = "VM_AGENT_JWT_ISSUER"
JWT_TTL_ENV = "VM_AGENT_JWT_TTL_SECONDS"
DEFAULT_AGENT_JWT_SECRET = "vm-agent-development-secret-change-me"
DEFAULT_AGENT_JWT_ISSUER = "vm_agent_server"


def get_agent_jwt_secret() -> str:
    return str(os.getenv(JWT_SECRET_ENV) or DEFAULT_AGENT_JWT_SECRET)


def get_agent_jwt_issuer() -> str:
    return str(os.getenv(JWT_ISSUER_ENV) or DEFAULT_AGENT_JWT_ISSUER)


def get_agent_jwt_ttl_seconds() -> int | None:
    raw = str(os.getenv(JWT_TTL_ENV) or "").strip()
    if not raw:
        return None
    try:
        ttl = int(raw)
    except ValueError:
        return None
    return ttl if ttl > 0 else None


def issue_agent_access_token(agent_id: str, *, token_version: int) -> str:
    return issue_agent_jwt(
        secret=get_agent_jwt_secret(),
        agent_id=agent_id,
        issuer=get_agent_jwt_issuer(),
        purpose=TOKEN_PURPOSE_AGENT_WS,
        token_version=token_version,
        ttl_seconds=get_agent_jwt_ttl_seconds(),
    )


def verify_agent_access_token(token: str, expected_agent_id: str, *, expected_version: int) -> AgentJwtClaims:
    return verify_agent_jwt(
        token,
        get_agent_jwt_secret(),
        expected_agent_id=expected_agent_id,
        expected_version=expected_version,
        expected_purpose=TOKEN_PURPOSE_AGENT_WS,
        expected_issuer=get_agent_jwt_issuer(),
    )