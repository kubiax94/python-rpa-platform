from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from vm_agent_server.src.authz import ROLE_ORDER, has_minimum_role


PERMISSION_DEFAULTS: dict[str, dict[str, Any]] = {
    "view": {"enabled": True, "minimum_role": "operator"},
    "interact": {"enabled": True, "minimum_role": "admin"},
    "clipboard": {"enabled": True, "minimum_role": "operator"},
    "upload": {"enabled": True, "minimum_role": "admin"},
    "download": {"enabled": True, "minimum_role": "admin"},
    "recording": {"enabled": True, "minimum_role": "operator"},
    "session_kick": {"enabled": True, "minimum_role": "admin"},
}


def _normalize_principals(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        lowered = cleaned.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(cleaned)
    return normalized


def _normalize_permission_rule(raw_rule: Any, *, default_minimum_role: str) -> dict[str, Any]:
    rule = raw_rule if isinstance(raw_rule, Mapping) else {}
    minimum_role = _normalize_role(rule.get("minimum_role"), default_minimum_role) if rule.get("minimum_role") is not None else default_minimum_role
    enabled = rule.get("enabled") if isinstance(rule.get("enabled"), bool) else True
    return {
        "enabled": enabled,
        "minimum_role": minimum_role,
        "users": _normalize_principals(rule.get("users")),
        "groups": _normalize_principals(rule.get("groups")),
    }


def _normalize_role(value: Any, default: str) -> str:
    role = str(value or "").strip().lower()
    if role in ROLE_ORDER:
        return role
    return default


def normalize_guacamole_access_policy(raw_policy: Any) -> dict[str, Any]:
    policy = raw_policy if isinstance(raw_policy, Mapping) else {}
    permissions = policy.get("permissions") if isinstance(policy.get("permissions"), Mapping) else {}

    legacy_view_minimum_role = _normalize_role(policy.get("minimum_role"), "operator")
    legacy_interact_minimum_role = _normalize_role(policy.get("interactive_minimum_role"), "admin")
    legacy_file_transfer = policy.get("file_transfer") if isinstance(policy.get("file_transfer"), Mapping) else {}

    normalized_permissions: dict[str, dict[str, Any]] = {}
    for permission, defaults in PERMISSION_DEFAULTS.items():
        raw_rule = permissions.get(permission)
        if raw_rule is None and permission == "view":
            raw_rule = {"minimum_role": legacy_view_minimum_role}
        elif raw_rule is None and permission == "interact":
            raw_rule = {"minimum_role": legacy_interact_minimum_role}
        elif raw_rule is None and permission in {"clipboard", "recording"}:
            raw_rule = {"minimum_role": legacy_view_minimum_role}
        elif raw_rule is None and permission == "upload":
            raw_rule = {
                "minimum_role": legacy_interact_minimum_role,
                "enabled": legacy_file_transfer.get("upload_enabled") if isinstance(legacy_file_transfer.get("upload_enabled"), bool) else True,
            }
        elif raw_rule is None and permission == "download":
            raw_rule = {
                "minimum_role": legacy_interact_minimum_role,
                "enabled": legacy_file_transfer.get("download_enabled") if isinstance(legacy_file_transfer.get("download_enabled"), bool) else True,
            }
        normalized_permissions[permission] = _normalize_permission_rule(
            raw_rule,
            default_minimum_role=str(defaults["minimum_role"]),
        )

    return {"permissions": normalized_permissions}


def build_guacamole_principal_context(user: Any) -> dict[str, Any]:
    if user is None:
        return {
            "roles": ["viewer"],
            "subject": "",
            "group_ids": [],
        }
    return {
        "roles": list(getattr(user, "roles", []) or []),
        "subject": str(getattr(user, "subject", "") or "").strip(),
        "group_ids": [str(group_id or "").strip() for group_id in (getattr(user, "group_ids", []) or []) if str(group_id or "").strip()],
    }


def has_guacamole_permission(policy: dict[str, Any], user: Any, permission: str) -> bool:
    normalized_policy = normalize_guacamole_access_policy(policy)
    rules = normalized_policy.get("permissions") if isinstance(normalized_policy.get("permissions"), Mapping) else {}
    rule = rules.get(permission) if isinstance(rules.get(permission), Mapping) else None
    if rule is None:
        return False

    if not bool(rule.get("enabled")):
        return False

    principal_context = build_guacamole_principal_context(user)
    if has_minimum_role(principal_context["roles"], str(rule.get("minimum_role") or "admin")):
        return True

    subject = principal_context["subject"].casefold()
    if subject and subject in {entry.casefold() for entry in rule.get("users") or []}:
        return True

    allowed_groups = {entry.casefold() for entry in rule.get("groups") or []}
    if allowed_groups and any(group_id.casefold() in allowed_groups for group_id in principal_context["group_ids"]):
        return True

    return False


def attach_effective_permissions(policy: dict[str, Any], user: Any) -> dict[str, Any]:
    normalized_policy = normalize_guacamole_access_policy(policy)
    normalized_policy["effective_permissions"] = {
        permission: has_guacamole_permission(normalized_policy, user, permission)
        for permission in PERMISSION_DEFAULTS
    }
    return normalized_policy


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