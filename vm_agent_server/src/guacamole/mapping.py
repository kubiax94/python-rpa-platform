from __future__ import annotations

import os
from typing import Any


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


class _SafeTemplateDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


def _render_template(template: str, values: dict[str, str]) -> str:
    if not template:
        return ""
    try:
        return template.format_map(_SafeTemplateDict(values))
    except Exception:
        return ""


def _unique_strings(*values: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean_value = _clean_string(value)
        if not clean_value:
            continue
        lowered = clean_value.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(clean_value)
    return result


def build_agent_guacamole_mapping(
    *,
    agent_id: str,
    hostname: str,
    display_name: str = "",
    target_host: str = "",
    username: str = "",
    domain: str = "",
    group_name: str = "",
    connection_name: str = "",
    connection_identifier: str = "",
) -> dict[str, Any]:
    clean_agent_id = _clean_string(agent_id)
    clean_hostname = _clean_string(hostname)
    clean_display_name = _clean_string(display_name)
    clean_target_host = _clean_string(target_host)
    clean_username = _clean_string(username)
    clean_domain = _clean_string(domain)

    values = {
        "agent_id": clean_agent_id,
        "hostname": clean_hostname,
        "target_host": clean_target_host or clean_hostname,
        "display_name": clean_display_name or clean_hostname or clean_agent_id,
        "username": clean_username,
        "domain": clean_domain,
    }

    rendered_group_name = _render_template(
        _clean_string(os.getenv("GUACAMOLE_AGENT_GROUP_TEMPLATE")) or "{username}",
        values,
    )
    rendered_connection_name = _render_template(
        _clean_string(os.getenv("GUACAMOLE_CONNECTION_NAME_TEMPLATE")) or "{hostname}",
        values,
    )
    rendered_connection_identifier = _render_template(
        _clean_string(os.getenv("GUACAMOLE_CONNECTION_IDENTIFIER_TEMPLATE")),
        values,
    )
    rendered_username = _render_template(
        _clean_string(os.getenv("GUACAMOLE_USERNAME_TEMPLATE")),
        values,
    )

    effective_group_name = _clean_string(group_name) or rendered_group_name or clean_username or clean_agent_id
    effective_connection_name = _clean_string(connection_name) or rendered_connection_name or clean_hostname or clean_agent_id
    effective_connection_identifier = _clean_string(connection_identifier) or rendered_connection_identifier
    effective_username = clean_username or rendered_username

    return {
        "version": 1,
        "mapping_strategy": "agent_group",
        "group_name": effective_group_name,
        "group_identifier": "",
        "connection_name": effective_connection_name,
        "connection_identifier": effective_connection_identifier,
        "target_host": clean_target_host or clean_hostname,
        "username": effective_username,
        "domain": clean_domain,
        "group_candidates": _unique_strings(effective_group_name, clean_username, clean_agent_id),
        "connection_candidates": _unique_strings(
            effective_connection_identifier,
            effective_connection_name,
            clean_target_host,
            clean_hostname,
            clean_display_name,
            clean_agent_id,
        ),
    }