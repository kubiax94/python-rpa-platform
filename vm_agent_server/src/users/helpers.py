from __future__ import annotations

import base64
import json
import time
from urllib.error import HTTPError


def now_ts() -> int:
    return int(time.time())


def clean_str(value: str | None) -> str:
    return str(value or "").strip()


def decode_unverified_jwt(token: str) -> dict[str, object]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    decoded = base64.urlsafe_b64decode(payload + padding)
    parsed = json.loads(decoded.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("Invalid JWT payload")
    return parsed


def truncate_message(value: str, limit: int = 500) -> str:
    cleaned = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit - 3]}..."


def build_avatar_initials(*values: str) -> str:
    tokens: list[str] = []
    for value in values:
        cleaned = clean_str(value)
        if not cleaned:
            continue
        if "@" in cleaned:
            cleaned = cleaned.split("@", 1)[0]
        cleaned = cleaned.replace("\\", " ").replace(".", " ").replace("_", " ").replace("-", " ")
        candidate_tokens = [part for part in cleaned.split() if part]
        if candidate_tokens:
            tokens = candidate_tokens
            break

    if not tokens:
        return "U"
    if len(tokens) == 1:
        return tokens[0][:2].upper()
    return f"{tokens[0][0]}{tokens[1][0]}".upper()


def read_error_payload(error: HTTPError) -> dict[str, object]:
    try:
        raw_payload = error.read()
    except Exception:
        return {}

    if not raw_payload:
        return {}

    decoded = raw_payload.decode("utf-8", errors="replace").strip()
    if not decoded:
        return {}

    try:
        parsed = json.loads(decoded)
    except Exception:
        return {"raw": decoded}

    return parsed if isinstance(parsed, dict) else {"raw": decoded}


def format_http_error(provider_label: str, action: str, error: HTTPError) -> str:
    payload = read_error_payload(error)
    oauth_error = clean_str(str(payload.get("error") or ""))
    oauth_description = truncate_message(str(payload.get("error_description") or payload.get("error_summary") or payload.get("message") or payload.get("raw") or ""))
    error_codes = payload.get("error_codes")

    message = f"{provider_label} {action} failed"
    if oauth_error:
        message = f"{message}: {oauth_error}"
    else:
        message = f"{message} with HTTP {getattr(error, 'code', 'unknown')}"

    if oauth_description:
        message = f"{message} - {oauth_description}"

    if isinstance(error_codes, list) and error_codes:
        compact_codes = ", ".join(str(code) for code in error_codes[:5])
        message = f"{message} (codes: {compact_codes})"

    return message