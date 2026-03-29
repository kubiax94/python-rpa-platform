from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

AGENT_JWT_ALGORITHM = "HS256"
TOKEN_PURPOSE_AGENT_WS = "agent_ws"


class AgentJwtError(ValueError):
    pass


class AgentJwtClaims(BaseModel):
    iss: str = Field(default="vm_agent_server")
    sub: str
    agent_id: str
    purpose: str = Field(default=TOKEN_PURPOSE_AGENT_WS)
    iat: int
    exp: int | None = None
    jti: str = Field(default_factory=lambda: uuid.uuid4().hex)
    ver: int = Field(default=1)

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="after")
    def _validate_subject(self) -> "AgentJwtClaims":
        if self.sub != self.agent_id:
            raise ValueError("sub must match agent_id")
        return self


def _b64url_encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except Exception as exc:
        raise AgentJwtError("invalid base64url payload") from exc


def _json_dumps(value: dict[str, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=True).encode("utf-8")


def looks_like_jwt(token: str | None) -> bool:
    if not token:
        return False
    return token.count(".") == 2


def sign_agent_jwt(claims: AgentJwtClaims, secret: str) -> str:
    if not secret:
        raise AgentJwtError("signing secret is required")

    header = {"alg": AGENT_JWT_ALGORITHM, "typ": "JWT"}
    header_segment = _b64url_encode(_json_dumps(header))
    payload_segment = _b64url_encode(_json_dumps(claims.model_dump(exclude_none=True)))
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature_segment = _b64url_encode(signature)
    return f"{header_segment}.{payload_segment}.{signature_segment}"


def verify_agent_jwt(
    token: str,
    secret: str,
    *,
    expected_agent_id: str | None = None,
    expected_version: int | None = None,
    expected_purpose: str | None = None,
    expected_issuer: str | None = None,
    now: int | None = None,
) -> AgentJwtClaims:
    if not secret:
        raise AgentJwtError("signing secret is required")

    parts = token.split(".")
    if len(parts) != 3:
        raise AgentJwtError("invalid token format")

    header_segment, payload_segment, signature_segment = parts
    try:
        header = json.loads(_b64url_decode(header_segment).decode("utf-8"))
        payload = json.loads(_b64url_decode(payload_segment).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AgentJwtError("invalid token payload") from exc

    if header.get("alg") != AGENT_JWT_ALGORITHM:
        raise AgentJwtError("unsupported token algorithm")

    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    expected_signature = _b64url_encode(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    if not hmac.compare_digest(signature_segment, expected_signature):
        raise AgentJwtError("invalid token signature")

    try:
        claims = AgentJwtClaims.model_validate(payload)
    except ValidationError as exc:
        raise AgentJwtError("invalid token claims") from exc

    timestamp = int(time.time()) if now is None else int(now)
    if claims.exp is not None and claims.exp < timestamp:
        raise AgentJwtError("token expired")
    if expected_agent_id and claims.agent_id != expected_agent_id:
        raise AgentJwtError("token agent mismatch")
    if expected_version is not None and claims.ver != expected_version:
        raise AgentJwtError("token version mismatch")
    if expected_purpose and claims.purpose != expected_purpose:
        raise AgentJwtError("token purpose mismatch")
    if expected_issuer and claims.iss != expected_issuer:
        raise AgentJwtError("token issuer mismatch")

    return claims


def issue_agent_jwt(
    *,
    secret: str,
    agent_id: str,
    issuer: str = "vm_agent_server",
    purpose: str = TOKEN_PURPOSE_AGENT_WS,
    token_version: int = 1,
    ttl_seconds: int | None = None,
    now: int | None = None,
) -> str:
    issued_at = int(time.time()) if now is None else int(now)
    expires_at = issued_at + int(ttl_seconds) if ttl_seconds and ttl_seconds > 0 else None
    claims = AgentJwtClaims(
        iss=issuer,
        sub=agent_id,
        agent_id=agent_id,
        purpose=purpose,
        iat=issued_at,
        exp=expires_at,
        ver=token_version,
    )
    return sign_agent_jwt(claims, secret)