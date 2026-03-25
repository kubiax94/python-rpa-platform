from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _load_connection_map() -> dict[str, str]:
    raw_json = _clean_string(os.getenv("GUACAMOLE_CONNECTION_MAP_JSON"))
    file_path = _clean_string(os.getenv("GUACAMOLE_CONNECTION_MAP_FILE"))
    payload = ""

    if raw_json:
        payload = raw_json
    elif file_path:
        try:
            payload = Path(file_path).read_text(encoding="utf-8")
        except OSError:
            return {}

    if not payload:
        return {}

    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return {}

    if not isinstance(decoded, dict):
        return {}

    result: dict[str, str] = {}
    for key, value in decoded.items():
        clean_key = _clean_string(key)
        clean_value = _clean_string(value)
        if clean_key and clean_value:
            result[clean_key] = clean_value
    return result


def get_guacamole_config() -> dict[str, Any]:
    base_url = _clean_string(os.getenv("GUACAMOLE_BASE_URL")).rstrip("/")
    embed_template = _clean_string(os.getenv("GUACAMOLE_EMBED_URL_TEMPLATE"))
    launch_template = _clean_string(os.getenv("GUACAMOLE_LAUNCH_URL_TEMPLATE"))
    default_connection_mode = _clean_string(os.getenv("GUACAMOLE_DEFAULT_CONNECTION_MODE")) or "hostname"
    allow_embed = _parse_bool(os.getenv("GUACAMOLE_ALLOW_EMBED"), True)
    connection_map = _load_connection_map()

    enabled = bool(base_url or embed_template or launch_template or connection_map)
    configured = bool((base_url or embed_template or launch_template) and (connection_map or default_connection_mode))

    notes: list[str] = []
    if not enabled:
        notes.append("Set GUACAMOLE_BASE_URL and a URL template to enable the bridge.")
    if enabled and not (embed_template or launch_template):
        notes.append("Add GUACAMOLE_EMBED_URL_TEMPLATE or GUACAMOLE_LAUNCH_URL_TEMPLATE to generate launch links.")
    if enabled and not connection_map and not default_connection_mode:
        notes.append("Configure GUACAMOLE_CONNECTION_MAP_JSON or GUACAMOLE_DEFAULT_CONNECTION_MODE to resolve agent mappings.")
    if allow_embed:
        notes.append("Embedding may still be blocked by Guacamole or proxy X-Frame-Options headers.")

    return {
        "enabled": enabled,
        "configured": configured,
        "base_url": base_url,
        "allow_embed": allow_embed,
        "default_connection_mode": default_connection_mode,
        "mapping_count": len(connection_map),
        "embed_template_configured": bool(embed_template),
        "launch_template_configured": bool(launch_template),
        "notes": notes,
    }


def _resolve_connection_id(agent_id: str, metrics: dict[str, Any]) -> tuple[str, str]:
    connection_map = _load_connection_map()
    hostname = _clean_string(metrics.get("hostname"))
    azure_vm_name = _clean_string(metrics.get("azure_vm_name"))
    public_ip = _clean_string(metrics.get("azure_public_ip"))
    private_ip = _clean_string(metrics.get("azure_private_ip"))

    for candidate, source in (
        (agent_id, "mapping:agent_id"),
        (hostname, "mapping:hostname"),
        (azure_vm_name, "mapping:azure_vm_name"),
        (public_ip, "mapping:public_ip"),
        (private_ip, "mapping:private_ip"),
    ):
        if candidate and candidate in connection_map:
            return connection_map[candidate], source

    mode = _clean_string(os.getenv("GUACAMOLE_DEFAULT_CONNECTION_MODE")) or "hostname"
    if mode == "agent_id" and agent_id:
        return agent_id, "default:agent_id"
    if mode == "azure_vm_name" and azure_vm_name:
        return azure_vm_name, "default:azure_vm_name"
    if mode == "public_ip" and public_ip:
        return public_ip, "default:public_ip"
    if mode == "private_ip" and private_ip:
        return private_ip, "default:private_ip"
    if hostname:
        return hostname, "default:hostname"
    if agent_id:
        return agent_id, "fallback:agent_id"
    return "", "unresolved"


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


def build_guacamole_session(agent_id: str, agent_state: dict[str, Any] | None) -> dict[str, Any]:
    metrics = agent_state.get("__agent_metrics", {}) if isinstance(agent_state, dict) else {}
    config = get_guacamole_config()
    connection_id, source = _resolve_connection_id(agent_id, metrics if isinstance(metrics, dict) else {})

    hostname = _clean_string(metrics.get("hostname"))
    azure_vm_name = _clean_string(metrics.get("azure_vm_name"))
    public_ip = _clean_string(metrics.get("azure_public_ip"))
    private_ip = _clean_string(metrics.get("azure_private_ip"))
    base_url = _clean_string(os.getenv("GUACAMOLE_BASE_URL")).rstrip("/")
    embed_template = _clean_string(os.getenv("GUACAMOLE_EMBED_URL_TEMPLATE"))
    launch_template = _clean_string(os.getenv("GUACAMOLE_LAUNCH_URL_TEMPLATE"))

    values = {
        "agent_id": agent_id,
        "hostname": hostname,
        "azure_vm_name": azure_vm_name,
        "public_ip": public_ip,
        "private_ip": private_ip,
        "connection_id": connection_id,
        "connection_name": connection_id,
        "base_url": base_url,
    }

    embed_url = _render_template(embed_template, values)
    launch_url = _render_template(launch_template or embed_template, values)
    warnings: list[str] = []

    if not config["enabled"]:
        warnings.append("Guacamole bridge is disabled on the server.")
    if config["enabled"] and not connection_id:
        warnings.append("No connection mapping could be resolved for this agent.")
    if config["enabled"] and connection_id and not launch_url:
        warnings.append("A connection was resolved, but no launch URL template is configured.")

    status = "ready" if config["enabled"] and connection_id and launch_url else "needs_configuration"

    return {
        "enabled": config["enabled"],
        "configured": config["configured"],
        "status": status,
        "agent_id": agent_id,
        "source": source,
        "connection_id": connection_id,
        "connection_label": connection_id or hostname or agent_id,
        "base_url": base_url,
        "embed_url": embed_url,
        "launch_url": launch_url,
        "allow_embed": config["allow_embed"],
        "resolved_fields": {
            "hostname": hostname,
            "azure_vm_name": azure_vm_name,
            "public_ip": public_ip,
            "private_ip": private_ip,
        },
        "warnings": warnings,
    }