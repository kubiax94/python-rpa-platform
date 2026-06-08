from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from vm_agent_server.src.authz import ROLE_ORDER


def _normalize_role(value: Any, default: str) -> str:
    role = str(value or "").strip().lower()
    if role in ROLE_ORDER:
        return role
    return default


def normalize_guacamole_access_policy(raw_policy: Any) -> dict[str, Any]:
    policy = raw_policy if isinstance(raw_policy, Mapping) else {}
    minimum_role = _normalize_role(policy.get("minimum_role"), "operator")
    interactive_minimum_role = _normalize_role(policy.get("interactive_minimum_role"), "admin")
    if ROLE_ORDER[interactive_minimum_role] < ROLE_ORDER[minimum_role]:
        interactive_minimum_role = minimum_role

    file_transfer = policy.get("file_transfer") if isinstance(policy.get("file_transfer"), Mapping) else {}
    upload_enabled = file_transfer.get("upload_enabled") if isinstance(file_transfer.get("upload_enabled"), bool) else True
    download_enabled = file_transfer.get("download_enabled") if isinstance(file_transfer.get("download_enabled"), bool) else True

    return {
        "minimum_role": minimum_role,
        "interactive_minimum_role": interactive_minimum_role,
        "file_transfer": {
            "upload_enabled": upload_enabled,
            "download_enabled": download_enabled,
        },
    }


def extract_guacamole_access_policy(agent_state: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(agent_state, Mapping):
        return normalize_guacamole_access_policy(None)

    agent_record = agent_state.get("__agent_record") if isinstance(agent_state.get("__agent_record"), Mapping) else agent_state
    metadata = agent_record.get("metadata") if isinstance(agent_record.get("metadata"), Mapping) else {}
    guacamole = metadata.get("guacamole") if isinstance(metadata.get("guacamole"), Mapping) else {}

    raw_policy = guacamole.get("access") if isinstance(guacamole.get("access"), Mapping) else {}
    legacy_file_transfer = guacamole.get("file_transfer") if isinstance(guacamole.get("file_transfer"), Mapping) else {}
    if legacy_file_transfer:
        raw_policy = {
            **raw_policy,
            "file_transfer": {
                **(raw_policy.get("file_transfer") if isinstance(raw_policy.get("file_transfer"), Mapping) else {}),
                **legacy_file_transfer,
            },
        }

    return normalize_guacamole_access_policy(raw_policy)