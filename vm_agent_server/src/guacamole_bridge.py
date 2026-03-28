from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: str | None, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return default


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


def _join_url(base_url: str, suffix: str) -> str:
    if not base_url:
        return ""
    return f"{base_url.rstrip('/')}/{suffix.lstrip('/')}"


def _replace_url_hostname(url: str, hostname: str) -> str:
    parsed = urlparse(url)
    if not parsed.netloc:
        return url

    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo = f"{userinfo}:{parsed.password}"
        userinfo = f"{userinfo}@"

    port = f":{parsed.port}" if parsed.port else ""
    return urlunparse(parsed._replace(netloc=f"{userinfo}{hostname}{port}"))


def get_guacamole_request_base_url() -> str:
    override = _clean_string(os.getenv("GUACAMOLE_SERVER_BASE_URL")).rstrip("/")
    base_url = override or _clean_string(os.getenv("GUACAMOLE_BASE_URL")).rstrip("/")
    parsed = urlparse(base_url)

    if not override and parsed.hostname == "localhost":
        return _replace_url_hostname(base_url, "127.0.0.1")

    return base_url


def _to_websocket_url(url: str) -> str:
    if not url:
        return ""

    parsed = urlparse(url)
    if parsed.scheme == "https":
        return urlunparse(parsed._replace(scheme="wss"))
    if parsed.scheme == "http":
        return urlunparse(parsed._replace(scheme="ws"))
    return url


def _get_tunnel_urls(base_url: str) -> dict[str, str]:
    http_tunnel = _join_url(base_url, "tunnel")
    return {
        "websocket": _to_websocket_url(_join_url(base_url, "websocket-tunnel")),
        "http": http_tunnel,
        "token": _join_url(base_url, "api/tokens"),
    }


def build_guacamole_proxy_tunnel_urls(proxy_base_url: str) -> dict[str, str]:
    proxy_base_url = _clean_string(proxy_base_url).rstrip("/")
    return {
        "websocket": _to_websocket_url(_join_url(proxy_base_url, "/api/guacamole/websocket-tunnel")),
        "http": _join_url(proxy_base_url, "/api/guacamole/tunnel"),
    }


def _get_auth_config() -> dict[str, str]:
    return {
        "username": _clean_string(os.getenv("GUACAMOLE_AUTH_USERNAME")),
        "password": _clean_string(os.getenv("GUACAMOLE_AUTH_PASSWORD")),
        "provider": _clean_string(os.getenv("GUACAMOLE_AUTH_PROVIDER")),
        "connection_type": _clean_string(os.getenv("GUACAMOLE_CONNECTION_TYPE")) or "c",
    }


def _get_display_config() -> dict[str, Any]:
    width = _parse_int(os.getenv("GUACAMOLE_DISPLAY_WIDTH"))
    height = _parse_int(os.getenv("GUACAMOLE_DISPLAY_HEIGHT"))
    dpi = _parse_int(os.getenv("GUACAMOLE_DISPLAY_DPI"), 96)
    requested_mode = _clean_string(os.getenv("GUACAMOLE_DISPLAY_MODE")).casefold()

    mode = requested_mode if requested_mode in {"dynamic", "fixed"} else "dynamic"
    if mode == "fixed" and (not width or not height):
        mode = "dynamic"

    return {
        "mode": mode,
        "width": width if width and width > 0 else None,
        "height": height if height and height > 0 else None,
        "dpi": dpi if dpi and dpi > 0 else 96,
    }


def get_guacamole_config() -> dict[str, Any]:
    base_url = _clean_string(os.getenv("GUACAMOLE_BASE_URL")).rstrip("/")
    request_base_url = get_guacamole_request_base_url()
    default_connection_mode = _clean_string(os.getenv("GUACAMOLE_DEFAULT_CONNECTION_MODE")) or "hostname"
    allow_embed = _parse_bool(os.getenv("GUACAMOLE_ALLOW_EMBED"), True)
    connection_map = _load_connection_map()
    auth = _get_auth_config()
    display = _get_display_config()
    tunnel_urls = _get_tunnel_urls(base_url)

    enabled = bool(base_url)
    configured = bool(base_url and auth["username"] and auth["password"] and (connection_map or default_connection_mode))

    notes: list[str] = []
    if not enabled:
        notes.append("Set GUACAMOLE_BASE_URL to the Guacamole web application, for example http://localhost:8088/guacamole.")
    if enabled and (not auth["username"] or not auth["password"]):
        notes.append("Set GUACAMOLE_AUTH_USERNAME and GUACAMOLE_AUTH_PASSWORD so FastAPI can mint Guacamole session tokens for the frontend.")
    if enabled and not connection_map and not default_connection_mode:
        notes.append("Configure GUACAMOLE_CONNECTION_MAP_JSON or GUACAMOLE_DEFAULT_CONNECTION_MODE to resolve agent mappings.")
    if enabled:
        notes.append("The React app uses guacamole-common-js and connects directly to the Guacamole tunnel using short-lived session data from FastAPI.")
    if base_url and request_base_url and request_base_url != base_url:
        notes.append("FastAPI uses a server-side Guacamole URL optimized for local loopback requests.")
    if display["mode"] == "fixed":
        notes.append(f"Remote desktops use a fixed server-controlled display profile: {display['width']}x{display['height']} @ {display['dpi']} DPI.")

    return {
        "enabled": enabled,
        "configured": configured,
        "base_url": base_url,
        "request_base_url": request_base_url,
        "display": display,
        "allow_embed": allow_embed,
        "default_connection_mode": default_connection_mode,
        "mapping_count": len(connection_map),
        "embed_template_configured": False,
        "launch_template_configured": False,
        "auth_username_configured": bool(auth["username"]),
        "auth_password_configured": bool(auth["password"]),
        "auth_provider": auth["provider"] or "default",
        "connection_type": auth["connection_type"],
        "websocket_tunnel_url": tunnel_urls["websocket"],
        "http_tunnel_url": tunnel_urls["http"],
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


def _resolve_target(agent_id: str, agent_state: dict[str, Any] | None) -> dict[str, Any]:
    metrics = agent_state.get("__agent_metrics", {}) if isinstance(agent_state, dict) else {}
    safe_metrics = metrics if isinstance(metrics, dict) else {}
    config = get_guacamole_config()
    connection_id, source = _resolve_connection_id(agent_id, safe_metrics)

    hostname = _clean_string(safe_metrics.get("hostname"))
    azure_vm_name = _clean_string(safe_metrics.get("azure_vm_name"))
    public_ip = _clean_string(safe_metrics.get("azure_public_ip"))
    private_ip = _clean_string(safe_metrics.get("azure_private_ip"))
    base_url = _clean_string(os.getenv("GUACAMOLE_BASE_URL")).rstrip("/")
    request_base_url = get_guacamole_request_base_url()
    auth = _get_auth_config()
    display = _get_display_config()
    tunnel_urls = _get_tunnel_urls(base_url)

    warnings: list[str] = []
    if not config["enabled"]:
        warnings.append("Guacamole bridge is disabled on the server.")
    if config["enabled"] and not connection_id:
        warnings.append("No connection mapping could be resolved for this agent.")
    if config["enabled"] and (not auth["username"] or not auth["password"]):
        warnings.append("FastAPI is missing Guacamole API credentials.")

    status = "ready" if config["enabled"] and connection_id else "needs_configuration"

    return {
        "enabled": config["enabled"],
        "configured": config["configured"],
        "status": status,
        "agent_id": agent_id,
        "source": source,
        "connection_id": connection_id,
        "connection_label": connection_id or hostname or agent_id,
        "base_url": base_url,
        "request_base_url": request_base_url,
        "display": display,
        "allow_embed": config["allow_embed"],
        "connection_type": auth["connection_type"],
        "resolved_fields": {
            "hostname": hostname,
            "azure_vm_name": azure_vm_name,
            "public_ip": public_ip,
            "private_ip": private_ip,
        },
        "tunnels": {
            "websocket": tunnel_urls["websocket"],
            "http": tunnel_urls["http"],
        },
        "warnings": warnings,
    }


def _request_guacamole_token(base_url: str, username: str, password: str) -> dict[str, Any]:
    token_url = _get_tunnel_urls(base_url)["token"]
    payload = urlencode({
        "username": username,
        "password": password,
    }).encode("utf-8")
    request = Request(
        token_url,
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json",
        },
        method="POST",
    )

    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_guacamole_connections(base_url: str, auth_token: str, data_source: str) -> dict[str, Any]:
    connections_url = _join_url(
        base_url,
        f"api/session/data/{quote(data_source, safe='')}/connections",
    )
    request = Request(
        connections_url,
        headers={
            "Accept": "application/json",
            "Guacamole-Token": auth_token,
        },
        method="GET",
    )

    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_guacamole_json(base_url: str, auth_token: str, path: str) -> Any:
    request = Request(
        _join_url(base_url, path),
        headers={
            "Accept": "application/json",
            "Guacamole-Token": auth_token,
        },
        method="GET",
    )

    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_guacamole_connection(base_url: str, auth_token: str, data_source: str, connection_id: str) -> dict[str, Any]:
    decoded = _request_guacamole_json(
        base_url,
        auth_token,
        f"api/session/data/{quote(data_source, safe='')}/connections/{quote(connection_id, safe='')}",
    )
    return decoded if isinstance(decoded, dict) else {}


def _request_guacamole_connection_parameters(base_url: str, auth_token: str, data_source: str, connection_id: str) -> dict[str, str]:
    decoded = _request_guacamole_json(
        base_url,
        auth_token,
        f"api/session/data/{quote(data_source, safe='')}/connections/{quote(connection_id, safe='')}/parameters",
    )
    if not isinstance(decoded, dict):
        return {}

    parameters: dict[str, str] = {}
    for key, value in decoded.items():
        clean_key = _clean_string(key)
        if clean_key:
            parameters[clean_key] = _clean_string(value)
    return parameters


def _redact_connection_parameters(parameters: dict[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    sensitive_markers = ("password", "secret", "token", "private-key", "passphrase")

    for key, value in parameters.items():
        lowered = key.casefold()
        redacted[key] = "<redacted>" if any(marker in lowered for marker in sensitive_markers) else value

    return redacted


def _is_truthy_parameter(value: str | None) -> bool:
    return _clean_string(value).casefold() in {"true", "1", "yes", "on"}


def _analyze_rdp_parameters(parameters: dict[str, str]) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    positives: list[dict[str, str]] = []

    def add_finding(parameter: str, severity: str, message: str, recommendation: str) -> None:
        findings.append({
            "parameter": parameter,
            "severity": severity,
            "value": parameters.get(parameter, ""),
            "message": message,
            "recommendation": recommendation,
        })

    def add_positive(parameter: str, message: str) -> None:
        positives.append({
            "parameter": parameter,
            "value": parameters.get(parameter, ""),
            "message": message,
        })

    expensive_visual_flags = {
        "enable-wallpaper": "Wallpaper adds avoidable graphical churn over RDP.",
        "enable-theming": "Desktop theming adds extra redraw cost.",
        "enable-font-smoothing": "Font smoothing increases rendering cost and bandwidth.",
        "enable-full-window-drag": "Full window drag increases repaint volume while moving windows.",
        "enable-desktop-composition": "Desktop composition can add latency and extra frame traffic.",
        "enable-menu-animations": "Menu animations add extra frame traffic with little value in remote sessions.",
    }

    for parameter, message in expensive_visual_flags.items():
        if _is_truthy_parameter(parameters.get(parameter)):
            add_finding(parameter, "high", message, f"Set {parameter}=false unless you explicitly need that visual effect.")
        elif parameter in parameters:
            add_positive(parameter, f"{parameter} is disabled, which is better for responsiveness.")

    if _is_truthy_parameter(parameters.get("disable-bitmap-caching")):
        add_finding(
            "disable-bitmap-caching",
            "high",
            "Bitmap caching is disabled, so repeated UI elements must be resent more often.",
            "Set disable-bitmap-caching=false to let RDP reuse cached bitmaps.",
        )
    elif "disable-bitmap-caching" in parameters:
        add_positive("disable-bitmap-caching", "Bitmap caching remains enabled.")

    if _is_truthy_parameter(parameters.get("disable-offscreen-caching")):
        add_finding(
            "disable-offscreen-caching",
            "medium",
            "Offscreen caching is disabled, which can increase redraw traffic.",
            "Set disable-offscreen-caching=false unless you have a protocol-specific reason not to.",
        )
    elif "disable-offscreen-caching" in parameters:
        add_positive("disable-offscreen-caching", "Offscreen caching remains enabled.")

    if _is_truthy_parameter(parameters.get("force-lossless")):
        add_finding(
            "force-lossless",
            "medium",
            "Lossless encoding can increase bandwidth and interactive latency for general desktop work.",
            "Set force-lossless=false unless exact pixel fidelity is more important than responsiveness.",
        )

    color_depth = _clean_string(parameters.get("color-depth"))
    if color_depth:
        try:
            color_depth_value = int(color_depth)
        except ValueError:
            color_depth_value = 0

        if color_depth_value >= 32:
            add_finding(
                "color-depth",
                "medium",
                "32-bit color increases bandwidth compared with 16-bit color.",
                "Try color-depth=16 if responsiveness matters more than perfect color fidelity.",
            )
        elif color_depth_value and color_depth_value <= 16:
            add_positive("color-depth", "Color depth is already tuned toward lower bandwidth usage.")

    if _is_truthy_parameter(parameters.get("enable-audio")) or _clean_string(parameters.get("audio-servername")):
        add_finding(
            "enable-audio",
            "low",
            "Audio redirection adds another data stream and is often unnecessary for admin work.",
            "Disable audio redirection if you do not need remote sound.",
        )

    resize_method = _clean_string(parameters.get("resize-method"))
    if resize_method == "reconnect":
        add_finding(
            "resize-method",
            "low",
            "Reconnect-on-resize can make viewport changes feel disruptive.",
            "Prefer resize-method=display-update for a smoother browser-side experience.",
        )
    elif resize_method == "display-update":
        add_positive("resize-method", "Display-update resize is the smoother choice for live sessions.")

    return {
        "findings": findings,
        "positives": positives,
        "finding_count": len(findings),
        "likely_upstream_bottleneck": any(item["severity"] in {"high", "medium"} for item in findings),
    }


def inspect_guacamole_connection(agent_id: str, agent_state: dict[str, Any] | None) -> dict[str, Any]:
    target = _resolve_target(agent_id, agent_state)
    auth = _get_auth_config()
    warnings = list(target["warnings"])
    timings: dict[str, float] = {}
    started_at = time.perf_counter()

    def record_timing(label: str, started_step: float) -> None:
        timings[label] = round((time.perf_counter() - started_step) * 1000, 2)

    if not target["enabled"] or not target["connection_id"]:
        return {
            **target,
            "status": "needs_configuration",
            "connection": None,
            "parameters": {},
            "analysis": {
                "findings": [],
                "positives": [],
                "finding_count": 0,
                "likely_upstream_bottleneck": False,
            },
            "timings_ms": {
                **timings,
                "total": round((time.perf_counter() - started_at) * 1000, 2),
            },
            "warnings": warnings,
        }

    if not auth["username"] or not auth["password"]:
        warnings.append("Server-side Guacamole credentials are not configured.")
        return {
            **target,
            "status": "needs_configuration",
            "connection": None,
            "parameters": {},
            "analysis": {
                "findings": [],
                "positives": [],
                "finding_count": 0,
                "likely_upstream_bottleneck": False,
            },
            "timings_ms": {
                **timings,
                "total": round((time.perf_counter() - started_at) * 1000, 2),
            },
            "warnings": warnings,
        }

    try:
        step_started_at = time.perf_counter()
        auth_response = _request_guacamole_token(target["request_base_url"], auth["username"], auth["password"])
        record_timing("token", step_started_at)
        auth_token = _clean_string(auth_response.get("authToken"))
        data_source = _clean_string(auth_response.get("dataSource")) or auth["provider"] or "default"

        if not auth_token:
            warnings.append("Guacamole authentication succeeded without returning an auth token.")
            return {
                **target,
                "status": "auth_failed",
                "connection": None,
                "parameters": {},
                "analysis": {
                    "findings": [],
                    "positives": [],
                    "finding_count": 0,
                    "likely_upstream_bottleneck": False,
                },
                "timings_ms": {
                    **timings,
                    "total": round((time.perf_counter() - started_at) * 1000, 2),
                },
                "warnings": warnings,
            }

        step_started_at = time.perf_counter()
        resolved_connection_id, resolved_connection_name = _resolve_connection_identifier(
            target["request_base_url"],
            auth_token,
            data_source,
            [
                target["connection_id"],
                target["connection_label"],
                _clean_string(target.get("resolved_fields", {}).get("hostname")),
                agent_id,
            ],
        )
        record_timing("resolve_connection", step_started_at)
        if resolved_connection_id:
            target["connection_id"] = resolved_connection_id
            target["connection_label"] = resolved_connection_name or target["connection_label"]

        step_started_at = time.perf_counter()
        connection = _request_guacamole_connection(target["request_base_url"], auth_token, data_source, target["connection_id"])
        record_timing("get_connection", step_started_at)

        step_started_at = time.perf_counter()
        parameters = _request_guacamole_connection_parameters(target["request_base_url"], auth_token, data_source, target["connection_id"])
        record_timing("get_parameters", step_started_at)
        analysis = _analyze_rdp_parameters(parameters) if _clean_string(connection.get("protocol")) == "rdp" else {
            "findings": [],
            "positives": [],
            "finding_count": 0,
            "likely_upstream_bottleneck": False,
        }

        if _clean_string(connection.get("protocol")) != "rdp":
            warnings.append(f"Resolved connection uses protocol '{_clean_string(connection.get('protocol')) or 'unknown'}', not RDP.")

        return {
            **target,
            "status": "ready",
            "data_source": data_source,
            "connection": {
                "identifier": _clean_string(connection.get("identifier")) or target["connection_id"],
                "name": _clean_string(connection.get("name")) or target["connection_label"],
                "protocol": _clean_string(connection.get("protocol")),
                "parent_identifier": _clean_string(connection.get("parentIdentifier")),
                "active_connections": connection.get("activeConnections"),
                "last_active": connection.get("lastActive"),
                "attributes": connection.get("attributes") if isinstance(connection.get("attributes"), dict) else {},
            },
            "parameters": _redact_connection_parameters(parameters),
            "analysis": analysis,
            "timings_ms": {
                **timings,
                "total": round((time.perf_counter() - started_at) * 1000, 2),
            },
            "warnings": warnings,
        }
    except HTTPError as error:
        warnings.append(f"Guacamole diagnostics request failed with HTTP {error.code}.")
    except URLError as error:
        warnings.append(f"Could not reach Guacamole: {error.reason}.")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        warnings.append(f"Guacamole diagnostics request failed: {error}.")

    return {
        **target,
        "status": "error",
        "connection": None,
        "parameters": {},
        "analysis": {
            "findings": [],
            "positives": [],
            "finding_count": 0,
            "likely_upstream_bottleneck": False,
        },
        "timings_ms": {
            **timings,
            "total": round((time.perf_counter() - started_at) * 1000, 2),
        },
        "warnings": warnings,
    }


def invalidate_guacamole_token(base_url: str, auth_token: str) -> bool:
    base_url = _clean_string(base_url).rstrip("/")
    auth_token = _clean_string(auth_token)
    if not base_url or not auth_token:
        return False

    request = Request(
        _join_url(base_url, f"api/tokens/{quote(auth_token, safe='')}"),
        headers={
            "Accept": "application/json",
        },
        method="DELETE",
    )

    with urlopen(request, timeout=10):
        return True


def _resolve_connection_identifier(
    base_url: str,
    auth_token: str,
    data_source: str,
    candidates: list[str],
) -> tuple[str, str]:
    decoded = _request_guacamole_connections(base_url, auth_token, data_source)
    if not isinstance(decoded, dict):
        return "", ""

    normalized_candidates = [candidate.strip().casefold() for candidate in candidates if candidate and candidate.strip()]
    if not normalized_candidates:
        return "", ""

    for identifier, payload in decoded.items():
        clean_identifier = _clean_string(identifier)
        item = payload if isinstance(payload, dict) else {}
        item_identifier = _clean_string(item.get("identifier")) or clean_identifier
        item_name = _clean_string(item.get("name"))
        values = {item_identifier.casefold(), item_name.casefold(), clean_identifier.casefold()}

        if any(candidate in values for candidate in normalized_candidates):
            return item_identifier, item_name

    return "", ""


def list_guacamole_connections() -> dict[str, Any]:
    config = get_guacamole_config()
    auth = _get_auth_config()
    warnings: list[str] = []

    if not config["enabled"]:
        warnings.append("Guacamole bridge is disabled on the server.")
        return {
            "enabled": config["enabled"],
            "configured": config["configured"],
            "base_url": config["base_url"],
            "connections": [],
            "warnings": warnings,
        }

    if not auth["username"] or not auth["password"]:
        warnings.append("Server-side Guacamole credentials are not configured.")
        return {
            "enabled": config["enabled"],
            "configured": config["configured"],
            "base_url": config["base_url"],
            "connections": [],
            "warnings": warnings,
        }

    try:
        auth_response = _request_guacamole_token(config["request_base_url"], auth["username"], auth["password"])
    except HTTPError as error:
        warnings.append(f"Guacamole token request failed with HTTP {error.code}.")
        return {
            "enabled": config["enabled"],
            "configured": config["configured"],
            "base_url": config["base_url"],
            "connections": [],
            "warnings": warnings,
        }
    except URLError as error:
        warnings.append(f"Could not reach Guacamole: {error.reason}.")
        return {
            "enabled": config["enabled"],
            "configured": config["configured"],
            "base_url": config["base_url"],
            "connections": [],
            "warnings": warnings,
        }
    except (OSError, ValueError, json.JSONDecodeError) as error:
        warnings.append(f"Guacamole token request failed: {error}.")
        return {
            "enabled": config["enabled"],
            "configured": config["configured"],
            "base_url": config["base_url"],
            "connections": [],
            "warnings": warnings,
        }

    auth_token = _clean_string(auth_response.get("authToken"))
    default_data_source = _clean_string(auth_response.get("dataSource")) or auth["provider"] or "default"
    available_sources_raw = auth_response.get("availableDataSources")
    available_sources = []
    if isinstance(available_sources_raw, list):
        available_sources = [_clean_string(item) for item in available_sources_raw if _clean_string(item)]

    data_sources: list[str] = []
    for source in [default_data_source, *available_sources]:
        if source and source not in data_sources:
            data_sources.append(source)

    if not auth_token:
        warnings.append("Guacamole authentication succeeded without returning an auth token.")
        return {
            "enabled": config["enabled"],
            "configured": config["configured"],
            "base_url": config["base_url"],
            "connections": [],
            "warnings": warnings,
        }

    connections: list[dict[str, Any]] = []
    for data_source in data_sources:
        try:
            decoded = _request_guacamole_connections(config["request_base_url"], auth_token, data_source)
        except HTTPError as error:
            warnings.append(f"Could not list connections for data source '{data_source}': HTTP {error.code}.")
            continue
        except URLError as error:
            warnings.append(f"Could not list connections for data source '{data_source}': {error.reason}.")
            continue
        except (OSError, ValueError, json.JSONDecodeError) as error:
            warnings.append(f"Could not list connections for data source '{data_source}': {error}.")
            continue

        if not isinstance(decoded, dict):
            warnings.append(f"Unexpected connections payload for data source '{data_source}'.")
            continue

        for identifier, payload in decoded.items():
            item = payload if isinstance(payload, dict) else {}
            clean_identifier = _clean_string(item.get("identifier")) or _clean_string(identifier)
            connections.append({
                "data_source": data_source,
                "identifier": clean_identifier,
                "name": _clean_string(item.get("name")),
                "protocol": _clean_string(item.get("protocol")),
                "parent_identifier": _clean_string(item.get("parentIdentifier")),
                "active_connections": item.get("activeConnections"),
            })

    connections.sort(key=lambda item: (str(item.get("data_source") or ""), str(item.get("name") or ""), str(item.get("identifier") or "")))

    return {
        "enabled": config["enabled"],
        "configured": config["configured"],
        "base_url": config["base_url"],
        "default_data_source": default_data_source,
        "available_data_sources": data_sources,
        "connection_count": len(connections),
        "connections": connections,
        "warnings": warnings,
    }


def create_guacamole_client_session(
    agent_id: str,
    agent_state: dict[str, Any] | None,
    tunnel_urls: dict[str, str] | None = None,
) -> dict[str, Any]:
    target = _resolve_target(agent_id, agent_state)
    auth = _get_auth_config()
    warnings = list(target["warnings"])

    if not target["enabled"] or not target["connection_id"]:
        return {
            **target,
            "status": "needs_configuration",
            "client_session": None,
            "warnings": warnings,
        }

    if not auth["username"] or not auth["password"]:
        warnings.append("Server-side Guacamole credentials are not configured.")
        return {
            **target,
            "status": "needs_configuration",
            "client_session": None,
            "warnings": warnings,
        }

    try:
        auth_response = _request_guacamole_token(target["request_base_url"], auth["username"], auth["password"])
    except HTTPError as error:
        warnings.append(f"Guacamole token request failed with HTTP {error.code}.")
        return {
            **target,
            "status": "auth_failed",
            "client_session": None,
            "warnings": warnings,
        }
    except URLError as error:
        warnings.append(f"Could not reach Guacamole: {error.reason}.")
        return {
            **target,
            "status": "auth_failed",
            "client_session": None,
            "warnings": warnings,
        }
    except (OSError, ValueError, json.JSONDecodeError) as error:
        warnings.append(f"Guacamole token request failed: {error}.")
        return {
            **target,
            "status": "auth_failed",
            "client_session": None,
            "warnings": warnings,
        }

    auth_token = _clean_string(auth_response.get("authToken"))
    data_source = _clean_string(auth_response.get("dataSource")) or auth["provider"] or "default"

    if not auth_token:
        warnings.append("Guacamole authentication succeeded without returning an auth token.")
        return {
            **target,
            "status": "auth_failed",
            "client_session": None,
            "warnings": warnings,
        }

    resolved_connection_id = target["connection_id"]
    resolved_connection_name = target["connection_label"]

    try:
        lookup_id, lookup_name = _resolve_connection_identifier(
            target["request_base_url"],
            auth_token,
            data_source,
            [
                target["connection_id"],
                target["connection_label"],
                _clean_string(target.get("resolved_fields", {}).get("hostname")),
                agent_id,
            ],
        )
        if lookup_id:
            resolved_connection_id = lookup_id
        if lookup_name:
            resolved_connection_name = lookup_name
        elif not lookup_id:
            warnings.append(
                "No Guacamole connection identifier matched the resolved agent mapping. Use GUACAMOLE_CONNECTION_MAP_JSON or name the Guacamole connection exactly like the agent hostname."
            )
            return {
                **target,
                "status": "needs_configuration",
                "client_session": None,
                "warnings": warnings,
            }
    except HTTPError as error:
        warnings.append(f"Could not list Guacamole connections: HTTP {error.code}.")
    except URLError as error:
        warnings.append(f"Could not list Guacamole connections: {error.reason}.")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        warnings.append(f"Could not list Guacamole connections: {error}.")

    return {
        **target,
        "status": "ready",
        "connection_id": resolved_connection_id,
        "connection_label": resolved_connection_name or resolved_connection_id or target["connection_label"],
        "tunnels": tunnel_urls or target["tunnels"],
        "client_session": {
            "auth_token": auth_token,
            "data_source": data_source,
            "connection_id": resolved_connection_id,
            "connection_type": auth["connection_type"],
            "display": target["display"],
            "tunnels": tunnel_urls or target["tunnels"],
        },
        "warnings": warnings,
    }


def build_guacamole_session(agent_id: str, agent_state: dict[str, Any] | None) -> dict[str, Any]:
    return _resolve_target(agent_id, agent_state)