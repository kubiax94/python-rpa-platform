from __future__ import annotations

import json
import os
import re
import time
from http.cookies import SimpleCookie
from datetime import datetime
from pathlib import Path
from typing import Any
from collections.abc import Callable
from posixpath import join as posix_join
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from vm_agent_server.src.guacamole.access_policy import extract_guacamole_access_policy, normalize_guacamole_access_policy
from vm_agent_server.src.guacamole.mapping import build_agent_guacamole_mapping


_settings_provider: Callable[[], Any] | None = None


def set_guacamole_settings_provider(provider: Callable[[], Any] | None) -> None:
    global _settings_provider
    _settings_provider = provider


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


def _ensure_guacamole_recording_filename(value: Any) -> str:
    clean_value = _clean_string(value)
    if not clean_value:
        return ""
    if clean_value.casefold().endswith(".guac"):
        return clean_value
    return f"{clean_value}.guac"


def _get_settings_snapshot() -> dict[str, Any]:
    if _settings_provider is None:
        return {}

    try:
        snapshot = _settings_provider()
    except Exception:
        return {}

    if hasattr(snapshot, "model_dump"):
        try:
            dumped = snapshot.model_dump(mode="python")
            return dumped if isinstance(dumped, dict) else {}
        except Exception:
            return {}

    return snapshot if isinstance(snapshot, dict) else {}


def _get_guacamole_settings_section() -> dict[str, Any]:
    snapshot = _get_settings_snapshot()
    section = snapshot.get("guacamole") if isinstance(snapshot, dict) else None
    return section if isinstance(section, dict) else {}


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


def _unique_strings(*values: Any) -> list[str]:
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


def _join_url(base_url: str, suffix: str) -> str:
    if not base_url:
        return ""
    return f"{base_url.rstrip('/')}/{suffix.lstrip('/')}"


def _extract_cookie_header(headers: Any) -> str:
    raw_cookie_headers: list[str] = []
    get_all = getattr(headers, "get_all", None)
    if callable(get_all):
        raw_cookie_headers = get_all("Set-Cookie") or []

    if not raw_cookie_headers:
        single_cookie = headers.get("Set-Cookie")
        if single_cookie:
            raw_cookie_headers = [single_cookie]

    if not raw_cookie_headers:
        return ""

    cookie = SimpleCookie()
    for raw_cookie in raw_cookie_headers:
        try:
            cookie.load(raw_cookie)
        except Exception:
            continue

    return "; ".join(f"{morsel.key}={morsel.value}" for morsel in cookie.values())


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


def _get_provisioning_config() -> dict[str, Any]:
    return {
        "enabled": _parse_bool(os.getenv("GUACAMOLE_AUTO_PROVISION"), True),
        "group_parent_identifier": _clean_string(os.getenv("GUACAMOLE_AGENT_GROUP_PARENT_IDENTIFIER")) or "ROOT",
        "protocol": _clean_string(os.getenv("GUACAMOLE_CONNECTION_PROTOCOL")) or "rdp",
        "rdp_port": _clean_string(os.getenv("GUACAMOLE_RDP_PORT")) or "3389",
        "parameter_template_json": _clean_string(os.getenv("GUACAMOLE_CONNECTION_PARAMETER_TEMPLATE_JSON")),
        "attribute_template_json": _clean_string(os.getenv("GUACAMOLE_CONNECTION_ATTRIBUTE_TEMPLATE_JSON")),
        "default_password": _clean_string(os.getenv("GUACAMOLE_CONNECTION_PASSWORD")),
        "default_secret": _clean_string(os.getenv("GUACAMOLE_CONNECTION_SECRET")),
    }


def _get_display_config() -> dict[str, Any]:
    settings_display = _get_guacamole_settings_section().get("display")
    settings_display = settings_display if isinstance(settings_display, dict) else {}

    width = settings_display.get("width") if isinstance(settings_display.get("width"), int) else _parse_int(os.getenv("GUACAMOLE_DISPLAY_WIDTH"))
    height = settings_display.get("height") if isinstance(settings_display.get("height"), int) else _parse_int(os.getenv("GUACAMOLE_DISPLAY_HEIGHT"))
    dpi = settings_display.get("dpi") if isinstance(settings_display.get("dpi"), int) else _parse_int(os.getenv("GUACAMOLE_DISPLAY_DPI"), 96)
    requested_mode = _clean_string(settings_display.get("mode")).casefold() or _clean_string(os.getenv("GUACAMOLE_DISPLAY_MODE")).casefold()

    mode = requested_mode if requested_mode in {"dynamic", "fixed"} else "dynamic"
    if mode == "fixed" and (not width or not height):
        mode = "dynamic"

    return {
        "mode": mode,
        "width": width if width and width > 0 else None,
        "height": height if height and height > 0 else None,
        "dpi": dpi if dpi and dpi > 0 else 96,
    }


def _get_recording_config() -> dict[str, Any]:
    settings_recording = _get_guacamole_settings_section().get("recording")
    settings_recording = settings_recording if isinstance(settings_recording, dict) else {}

    enabled = settings_recording.get("enabled") if isinstance(settings_recording.get("enabled"), bool) else _parse_bool(os.getenv("GUACAMOLE_SESSION_RECORDING_ENABLED"), False)
    browse_url = _clean_string(settings_recording.get("browse_url")) or _clean_string(os.getenv("GUACAMOLE_SESSION_RECORDING_BROWSE_URL"))
    path_template = _clean_string(settings_recording.get("path_template")) or _clean_string(os.getenv("GUACAMOLE_SESSION_RECORDING_PATH_TEMPLATE"))
    name_template = _clean_string(settings_recording.get("name_template")) or _clean_string(os.getenv("GUACAMOLE_SESSION_RECORDING_NAME_TEMPLATE")) or "{connection_name}-{timestamp}.guac"
    create_path = settings_recording.get("create_path") if isinstance(settings_recording.get("create_path"), bool) else _parse_bool(os.getenv("GUACAMOLE_SESSION_RECORDING_CREATE_PATH"), True)
    exclude_output = settings_recording.get("exclude_output") if isinstance(settings_recording.get("exclude_output"), bool) else _parse_bool(os.getenv("GUACAMOLE_SESSION_RECORDING_EXCLUDE_OUTPUT"), False)
    exclude_mouse = settings_recording.get("exclude_mouse") if isinstance(settings_recording.get("exclude_mouse"), bool) else _parse_bool(os.getenv("GUACAMOLE_SESSION_RECORDING_EXCLUDE_MOUSE"), False)
    exclude_touch = settings_recording.get("exclude_touch") if isinstance(settings_recording.get("exclude_touch"), bool) else _parse_bool(os.getenv("GUACAMOLE_SESSION_RECORDING_EXCLUDE_TOUCH"), False)
    include_keys = settings_recording.get("include_keys") if isinstance(settings_recording.get("include_keys"), bool) else _parse_bool(os.getenv("GUACAMOLE_SESSION_RECORDING_INCLUDE_KEYS"), True)

    return {
        "enabled": enabled,
        "browse_url": browse_url,
        "path_template": path_template,
        "name_template": _ensure_guacamole_recording_filename(name_template),
        "create_path": create_path,
        "exclude_output": exclude_output,
        "exclude_mouse": exclude_mouse,
        "exclude_touch": exclude_touch,
        "include_keys": include_keys,
        "configured": bool(enabled and path_template),
    }


def get_guacamole_config() -> dict[str, Any]:
    base_url = _clean_string(os.getenv("GUACAMOLE_BASE_URL")).rstrip("/")
    request_base_url = get_guacamole_request_base_url()
    default_connection_mode = _clean_string(os.getenv("GUACAMOLE_DEFAULT_CONNECTION_MODE")) or "hostname"
    allow_embed = _parse_bool(os.getenv("GUACAMOLE_ALLOW_EMBED"), True)
    connection_map = _load_connection_map()
    auth = _get_auth_config()
    display = _get_display_config()
    recording = _get_recording_config()
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
        notes.append("Deployment-created agents carry a Guacamole mapping profile in agent metadata. By default the group name follows agent_id and the connection name follows hostname.")
    if enabled:
        notes.append("GUACAMOLE_CONNECTION_PARAMETER_TEMPLATE_JSON can reference {username}, {password}, and {secret}. Password and secret values can be injected at deployment prep time without persisting them into agent metadata.")
    if enabled:
        notes.append("The React app uses guacamole-common-js and connects directly to the Guacamole tunnel using short-lived session data from FastAPI.")
    if base_url and request_base_url and request_base_url != base_url:
        notes.append("FastAPI uses a server-side Guacamole URL optimized for local loopback requests.")
    if display["mode"] == "fixed":
        notes.append(f"Remote desktops use a fixed server-controlled display profile: {display['width']}x{display['height']} @ {display['dpi']} DPI.")
    if recording["enabled"] and recording["configured"]:
        notes.append("Guacamole session recording is available for on-demand recorded sessions.")
    elif recording["enabled"]:
        notes.append("Guacamole session recording is enabled in config, but the recording profile is incomplete.")
    if recording["browse_url"]:
        notes.append("Recording inventory is available through the configured browse URL.")

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
        "recording": recording,
        "websocket_tunnel_url": tunnel_urls["websocket"],
        "http_tunnel_url": tunnel_urls["http"],
        "notes": notes,
    }


def _extract_agent_record(agent_state: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(agent_state, dict):
        return {}
    record = agent_state.get("__agent_record")
    return record if isinstance(record, dict) else {}


def _sanitize_recording_relative_path(relative_path: str) -> str:
    cleaned_parts: list[str] = []
    for raw_part in _clean_string(relative_path).replace("\\", "/").split("/"):
        part = raw_part.strip()
        if not part or part in {".", ".."}:
            continue
        cleaned_parts.append(part)
    return "/".join(cleaned_parts)


def _build_recording_target_url(base_url: str, relative_path: str = "") -> str:
    clean_base = _clean_string(base_url).rstrip("/")
    clean_relative = _sanitize_recording_relative_path(relative_path)
    if not clean_base:
        return ""
    if not clean_relative:
        return f"{clean_base}/"
    encoded_relative = "/".join(quote(segment, safe="") for segment in clean_relative.split("/"))
    return f"{clean_base}/{encoded_relative}"


def _build_recording_listing_url(base_url: str, relative_path: str = "") -> str:
    clean_base = _clean_string(base_url).rstrip("/")
    clean_relative = _sanitize_recording_relative_path(relative_path)
    if not clean_base:
        return ""
    if not clean_relative:
        return f"{clean_base}/"
    encoded_relative = "/".join(quote(segment, safe="") for segment in clean_relative.split("/"))
    return f"{clean_base}/{encoded_relative}/"


def _request_recording_listing(url: str) -> list[dict[str, Any]]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
        },
        method="GET",
    )
    with urlopen(request, timeout=10) as response:
        decoded = json.loads(response.read().decode("utf-8"))
    return decoded if isinstance(decoded, list) else []


def _parse_recording_mtime(value: Any) -> int | None:
    clean_value = _clean_string(value)
    if not clean_value:
        return None

    for parser in (
        lambda text: int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()),
        lambda text: int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%S%z").timestamp()),
    ):
        try:
            return parser(clean_value)
        except Exception:
            continue
    return None


def _normalize_recording_listing_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    return {
        "name": _clean_string(entry.get("name")),
        "type": _clean_string(entry.get("type")).casefold(),
        "size": _parse_int(str(entry.get("size")) if entry.get("size") is not None else None),
        "mtime": _parse_recording_mtime(entry.get("mtime")),
    }


def list_guacamole_recordings(public_base_url: str, *, agent_id: str = "", username: str = "") -> dict[str, Any]:
    recording = _get_recording_config()
    browse_url = _clean_string(recording.get("browse_url"))
    warnings: list[str] = []
    entries: list[dict[str, Any]] = []

    if not recording.get("enabled"):
        warnings.append("Recording is disabled.")
        return {
            "enabled": False,
            "configured": False,
            "browse_url": browse_url,
            "entry_count": 0,
            "entries": [],
            "warnings": warnings,
        }

    if not browse_url:
        warnings.append("Recording browse URL is not configured. Set GUACAMOLE_SESSION_RECORDING_BROWSE_URL or save a browse URL in settings.")
        return {
            "enabled": True,
            "configured": False,
            "browse_url": browse_url,
            "entry_count": 0,
            "entries": [],
            "warnings": warnings,
        }

    clean_agent_id = _clean_string(agent_id)
    clean_username = _clean_string(username)
    path_template = _clean_string(recording.get("path_template"))
    root_relative_path = ""

    directory_queue: list[tuple[str, int]] = [(root_relative_path, 0)]
    while directory_queue:
        current_relative_path, depth = directory_queue.pop(0)
        target_label = current_relative_path or "/"
        try:
            target_url = _build_recording_listing_url(browse_url, current_relative_path)
            listing = _request_recording_listing(target_url)
        except HTTPError as error:
            if error.code != 404 or current_relative_path == root_relative_path:
                warnings.append(f"Recording inventory request failed for {target_label} with HTTP {error.code}.")
            continue
        except URLError as error:
            warnings.append(f"Could not reach recording inventory for {target_label}: {error.reason}.")
            continue
        except (OSError, ValueError, json.JSONDecodeError) as error:
            warnings.append(f"Recording inventory failed for {target_label}: {error}.")
            continue

        for raw_entry in listing:
            entry = _normalize_recording_listing_entry(raw_entry)
            name = _clean_string(entry.get("name"))
            entry_type = _clean_string(entry.get("type"))
            if not name:
                continue
            next_relative_path = _sanitize_recording_relative_path(posix_join(current_relative_path, name))
            if entry_type == "directory":
                if depth < 4:
                    directory_queue.append((next_relative_path, depth + 1))
                continue
            if entry_type != "file":
                continue

            metadata = _extract_recording_inventory_metadata(
                next_relative_path,
                path_template=path_template,
                fallback_agent_id=clean_agent_id,
                fallback_username=clean_username,
            )
            if clean_agent_id and _clean_string(metadata.get("agent_id")).casefold() != clean_agent_id.casefold():
                continue
            if clean_username and _clean_string(metadata.get("username")).casefold() != clean_username.casefold():
                continue
            entries.append({
                "agent_id": metadata.get("agent_id", ""),
                "username": metadata.get("username", ""),
                "name": name,
                "relative_path": next_relative_path,
                "size_bytes": entry.get("size"),
                "modified_at": entry.get("mtime"),
                "download_url": f"{public_base_url.rstrip('/')}/api/guacamole/recordings/download?path={quote(next_relative_path, safe='')}",
            })

    entries.sort(key=lambda item: (-(item.get("modified_at") or 0), item.get("relative_path") or ""))
    return {
        "enabled": True,
        "configured": True,
        "browse_url": browse_url,
        "entry_count": len(entries),
        "entries": entries,
        "warnings": warnings,
    }


def open_guacamole_recording(relative_path: str):
    recording = _get_recording_config()
    browse_url = _clean_string(recording.get("browse_url"))
    clean_relative_path = _sanitize_recording_relative_path(relative_path)
    if not browse_url:
        raise RuntimeError("Recording browse URL is not configured")
    if not clean_relative_path:
        raise RuntimeError("Recording path is required")

    request = Request(
        _build_recording_target_url(browse_url, clean_relative_path),
        headers={
            "Accept": "application/octet-stream,*/*",
        },
        method="GET",
    )
    return urlopen(request, timeout=30)


def _extract_agent_metadata(agent_state: dict[str, Any] | None) -> dict[str, Any]:
    metadata = _extract_agent_record(agent_state).get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _extract_preferred_session_username(agent_state: dict[str, Any] | None) -> str:
    if not isinstance(agent_state, dict):
        return ""

    best_username = ""
    best_score = (-1, -1, -1)
    for session_key, session_data in agent_state.items():
        if session_key.startswith("__") or not isinstance(session_data, dict):
            continue

        username = _clean_string(session_data.get("username"))
        if not username or username.casefold() in {"unknown", "system", "nt authority\\system"}:
            continue

        status = _clean_string(session_data.get("status")).casefold()
        session_type = _clean_string(session_data.get("type")).casefold()
        try:
            session_id = int(session_data.get("session_id") or 0)
        except (TypeError, ValueError):
            session_id = 0

        score = (
            2 if status == "active" else 1 if status in {"connected", "up"} else 0,
            1 if session_type in {"interactive", "user_session"} else 0,
            1 if session_id > 0 else 0,
        )
        if score > best_score:
            best_score = score
            best_username = username

    return best_username


def _score_vm_session(session_data: dict[str, Any]) -> tuple[int, int, int, int]:
    status = _clean_string(session_data.get("status")).casefold()
    session_type = _clean_string(session_data.get("type")).casefold()
    try:
        session_id = int(session_data.get("session_id") or 0)
    except (TypeError, ValueError):
        session_id = 0
    try:
        process_count = int(session_data.get("process_count") or 0)
    except (TypeError, ValueError):
        process_count = 0

    return (
        2 if status == "active" else 1 if status in {"connected", "up"} else 0,
        1 if session_type in {"interactive", "user_session"} else 0,
        1 if session_id > 0 else 0,
        process_count,
    )


def _build_agent_group_name(agent_id: str, hostname: str, display_name: str, stored_group_name: str) -> str:
    return agent_id or stored_group_name or display_name or hostname


def _is_reserved_windows_identity(value: Any) -> bool:
    clean_value = _clean_string(value)
    if not clean_value:
        return False

    normalized = clean_value.replace("/", "\\").casefold()
    local_name = normalized.rsplit("\\", 1)[-1]
    return normalized in {
        "system",
        "unknown",
        "nt authority\\system",
        "nt authority\\local service",
        "nt authority\\network service",
    } or local_name in {"system", "local service", "network service"}


def _build_username_variants(value: Any) -> list[str]:
    clean_value = _clean_string(value)
    if not clean_value:
        return []

    variants = _unique_strings(clean_value)
    if "\\" in clean_value:
        variants = _unique_strings(*variants, clean_value.split("\\")[-1])
    if "@" in clean_value:
        variants = _unique_strings(*variants, clean_value.split("@", 1)[0])
    return variants


def _display_vm_username(value: Any, *local_identifiers: Any) -> str:
    clean_value = _clean_string(value)
    if not clean_value:
        return ""

    local_prefixes = {
        candidate.replace("/", "\\").casefold()
        for candidate in (_clean_string(item) for item in local_identifiers)
        if candidate
    }

    if "\\" in clean_value:
        prefix, suffix = clean_value.split("\\", 1)
        if prefix.casefold() in local_prefixes:
            return suffix
        return clean_value

    return clean_value


def _username_variants_match(left: Any, right: Any) -> bool:
    left_variants = {variant.casefold() for variant in _build_username_variants(left)}
    right_variants = {variant.casefold() for variant in _build_username_variants(right)}
    if not left_variants or not right_variants:
        return False
    return bool(left_variants & right_variants)


def _build_identity_summary(identity: Any) -> dict[str, Any]:
    if isinstance(identity, dict):
        get_value = identity.get
    else:
        get_value = lambda key, default=None: getattr(identity, key, default)

    claims = get_value("claims", {})
    safe_claims = claims if isinstance(claims, dict) else {}
    return {
        "subject": _clean_string(get_value("subject")),
        "username": _clean_string(get_value("username")),
        "display_name": _clean_string(get_value("display_name")),
        "email": _clean_string(get_value("email")),
        "avatar_url": _clean_string(get_value("avatar_url")),
        "avatar_initials": _clean_string(get_value("avatar_initials")),
        "auth_provider": _clean_string(get_value("auth_provider")),
        "preferred_username": _clean_string(safe_claims.get("preferred_username")),
        "upn": _clean_string(safe_claims.get("upn")),
    }


def _resolve_identity_for_vm_username(username: str, active_identities: list[Any] | None) -> dict[str, Any] | None:
    if not username or not active_identities:
        return None

    username_variants = {variant.casefold() for variant in _build_username_variants(username)}
    if not username_variants:
        return None

    for identity in active_identities:
        summary = _build_identity_summary(identity)
        identity_variants = {
            variant.casefold()
            for variant in _unique_strings(
                *_build_username_variants(summary.get("username")),
                *_build_username_variants(summary.get("email")),
                *_build_username_variants(summary.get("preferred_username")),
                *_build_username_variants(summary.get("upn")),
            )
        }
        if username_variants & identity_variants:
            return {
                "subject": summary.get("subject"),
                "username": summary.get("username"),
                "display_name": summary.get("display_name"),
                "email": summary.get("email"),
                "avatar_url": summary.get("avatar_url"),
                "avatar_initials": summary.get("avatar_initials"),
                "auth_provider": summary.get("auth_provider"),
            }

    return None


def _build_vm_user_connection_mapping(
    agent_id: str,
    hostname: str,
    display_name: str,
    base_mapping: dict[str, Any],
    session_entry: dict[str, Any],
) -> dict[str, Any]:
    username = _clean_string(session_entry.get("username"))
    connection_username = _display_vm_username(username, hostname, display_name, agent_id)
    session_name = _clean_string(session_entry.get("session_name"))
    session_id = _clean_string(session_entry.get("session_id"))
    connection_name = connection_username or session_name or f"{display_name or hostname or agent_id} session"

    mapping = build_agent_guacamole_mapping(
        agent_id=agent_id,
        hostname=hostname,
        display_name=display_name,
        target_host=_clean_string(base_mapping.get("target_host")) or hostname,
        username=username,
        group_name=_clean_string(base_mapping.get("group_name")),
        domain=_clean_string(base_mapping.get("domain")),
        connection_name=connection_name,
    )

    group_identifier = _clean_string(base_mapping.get("group_identifier"))
    if group_identifier:
        mapping["group_identifier"] = group_identifier

    mapping["group_candidates"] = _unique_strings(
        *list(base_mapping.get("group_candidates") or []),
        mapping.get("group_name"),
        display_name,
        hostname,
        agent_id,
    )
    mapping["connection_candidates"] = _unique_strings(
        connection_name,
        connection_username,
        username,
        session_name,
        f"{username}:{session_name}" if username and session_name else "",
        f"{username}:{session_id}" if username and session_id else "",
    )
    return mapping


def _extract_vm_user_session_entries(agent_state: dict[str, Any] | None, active_identities: list[Any] | None = None) -> list[dict[str, Any]]:
    if not isinstance(agent_state, dict):
        return []

    preferred_username = _extract_preferred_session_username(agent_state)
    sessions: list[dict[str, Any]] = []

    for session_key, session_data in agent_state.items():
        if session_key.startswith("__") or not isinstance(session_data, dict):
            continue

        username = _clean_string(session_data.get("username"))
        if not username or username.casefold() in {"unknown", "system", "nt authority\\system"}:
            continue

        session_status = _clean_string(session_data.get("status")) or "Unknown"
        session_type = _clean_string(session_data.get("type")) or "user_session"
        session_name = _clean_string(session_data.get("session_name")) or session_key

        try:
            session_id = int(session_data.get("session_id") or 0)
        except (TypeError, ValueError):
            session_id = 0

        try:
            process_count = int(session_data.get("process_count") or 0)
        except (TypeError, ValueError):
            process_count = 0

        sessions.append({
            "session_key": session_key,
            "session_id": session_id,
            "session_name": session_name,
            "username": username,
            "status": session_status,
            "type": session_type,
            "process_count": process_count,
            "is_preferred": username == preferred_username,
            "is_active": session_status.casefold() == "active",
            "identity": _resolve_identity_for_vm_username(username, active_identities),
            "guacamole": {
                "group_identifier": "",
                "group_name": "",
                "connection_id": "",
                "connection_name": "",
            },
            "is_in_use": False,
            "in_use_by": None,
        })

    sessions.sort(
        key=lambda item: (
            0 if item.get("is_preferred") else 1,
            0 if item.get("is_active") else 1,
            str(item.get("username") or "").casefold(),
            int(item.get("session_id") or 0),
        )
    )
    return sessions


def list_vm_user_sessions(
    agent_id: str,
    agent_state: dict[str, Any] | None,
    *,
    active_identities: list[Any] | None = None,
    tracked_sessions: list[dict[str, Any]] | None = None,
    maintain_connections: bool = False,
) -> list[dict[str, Any]]:
    metrics = agent_state.get("__agent_metrics", {}) if isinstance(agent_state, dict) else {}
    safe_metrics = metrics if isinstance(metrics, dict) else {}
    base_mapping = _extract_guacamole_mapping(agent_id, agent_state, safe_metrics)
    sessions = _extract_vm_user_session_entries(agent_state, active_identities)
    if not sessions:
        return []

    hostname = _clean_string(safe_metrics.get("hostname")) or _clean_string(base_mapping.get("target_host")) or agent_id
    agent_record = _extract_agent_record(agent_state)
    display_name = _clean_string(agent_record.get("display_name")) or hostname or agent_id
    provisioning = _get_provisioning_config()
    config = get_guacamole_config()
    auth = _get_auth_config()
    safe_tracked_sessions = tracked_sessions if isinstance(tracked_sessions, list) else []

    group_name = _build_agent_group_name(
        agent_id,
        hostname,
        display_name,
        _clean_string(base_mapping.get("group_name")),
    )
    base_mapping["group_name"] = group_name

    if not maintain_connections or not provisioning["enabled"] or not config["enabled"] or not auth["username"] or not auth["password"]:
        for session in sessions:
            session["guacamole"] = {
                "group_identifier": _clean_string(base_mapping.get("group_identifier")),
                "group_name": group_name,
                "connection_id": "",
                "connection_name": _display_vm_username(session.get("username"), hostname, display_name, agent_id),
            }
        return sessions

    try:
        auth_response = _request_guacamole_token(config["request_base_url"], auth["username"], auth["password"])
        auth_token = _clean_string(auth_response.get("authToken"))
        data_source = _clean_string(auth_response.get("dataSource")) or auth["provider"] or "default"
        if not auth_token:
            return sessions

        group_result = _upsert_guacamole_group(config["request_base_url"], auth_token, data_source, base_mapping)
        if group_result.get("identifier"):
            base_mapping["group_identifier"] = group_result["identifier"]
        if group_result.get("name"):
            base_mapping["group_name"] = group_result["name"]

        best_by_username: dict[str, dict[str, Any]] = {}
        for session in sessions:
            username_key = _clean_string(session.get("username")).casefold()
            if not username_key:
                continue
            current_best = best_by_username.get(username_key)
            if current_best is None or _score_vm_session(session) > _score_vm_session(current_best):
                best_by_username[username_key] = session

        resolved_connections: dict[str, dict[str, str]] = {}
        for username_key, preferred_session in best_by_username.items():
            user_mapping = _build_vm_user_connection_mapping(agent_id, hostname, display_name, base_mapping, preferred_session)
            connection_result = _upsert_guacamole_connection(
                config["request_base_url"],
                auth_token,
                data_source,
                agent_id,
                user_mapping,
                hostname,
            )
            resolved_connections[username_key] = {
                "group_identifier": _clean_string(base_mapping.get("group_identifier")),
                "group_name": _clean_string(base_mapping.get("group_name")),
                "connection_id": _clean_string(connection_result.get("identifier")),
                "connection_name": _clean_string(connection_result.get("name")) or _display_vm_username(preferred_session.get("username"), hostname, display_name, agent_id),
            }
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError):
        return sessions

    for session in sessions:
        connection = resolved_connections.get(_clean_string(session.get("username")).casefold())
        if connection:
            session["guacamole"] = connection
            connection_id = _clean_string(connection.get("connection_id"))
            matching_owners: list[dict[str, str]] = []
            seen_subjects: set[str] = set()
            for tracked_session in safe_tracked_sessions:
                tracked_connection_id = _clean_string(tracked_session.get("connection_id"))
                tracked_username = _clean_string(tracked_session.get("username"))
                if tracked_connection_id != connection_id and not _username_variants_match(tracked_username, session.get("username")):
                    continue
                owner = tracked_session.get("owner") if isinstance(tracked_session.get("owner"), dict) else None
                if not owner:
                    continue
                owner_subject = _clean_string(owner.get("subject"))
                dedupe_key = owner_subject or _clean_string(owner.get("username")) or _clean_string(owner.get("email"))
                if dedupe_key and dedupe_key in seen_subjects:
                    continue
                if dedupe_key:
                    seen_subjects.add(dedupe_key)
                matching_owners.append({key: _clean_string(value) for key, value in owner.items()})

            session["is_in_use"] = bool(matching_owners)
            session["in_use_by"] = matching_owners[0] if matching_owners else None
            session["in_use_by_users"] = matching_owners

    return sessions


def _extract_guacamole_mapping(agent_id: str, agent_state: dict[str, Any] | None, metrics: dict[str, Any]) -> dict[str, Any]:
    agent_record = _extract_agent_record(agent_state)
    agent_metadata = _extract_agent_metadata(agent_state)
    stored_mapping = agent_metadata.get("guacamole") if isinstance(agent_metadata.get("guacamole"), dict) else {}

    hostname = _clean_string(metrics.get("hostname")) or _clean_string(agent_record.get("hostname")) or agent_id
    display_name = _clean_string(agent_record.get("display_name")) or hostname or agent_id
    target_host = _clean_string(stored_mapping.get("target_host")) or hostname
    preferred_session_username = _extract_preferred_session_username(agent_state)
    stored_group_name = _clean_string(stored_mapping.get("group_name"))
    effective_group_name = _build_agent_group_name(agent_id, hostname, display_name, stored_group_name)

    mapping = build_agent_guacamole_mapping(
        agent_id=agent_id,
        hostname=hostname,
        display_name=display_name,
        target_host=target_host,
        username=_clean_string(stored_mapping.get("username")) or preferred_session_username,
        group_name=effective_group_name,
        domain=_clean_string(stored_mapping.get("domain")),
        connection_identifier=_clean_string(stored_mapping.get("connection_identifier")),
    )

    group_identifier = _clean_string(stored_mapping.get("group_identifier"))
    if group_identifier:
        mapping["group_identifier"] = group_identifier

    mapping["group_candidates"] = _unique_strings(
        *list(mapping.get("group_candidates") or []),
        *list(stored_mapping.get("group_candidates") or []),
    )
    mapping["connection_candidates"] = _unique_strings(
        *list(stored_mapping.get("connection_candidates") or []),
        *list(mapping.get("connection_candidates") or []),
    )
    mapping["source"] = "metadata" if stored_mapping else "derived"
    return mapping


def _reconcile_provisioned_target(agent_id: str, target: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    provisioning = _get_provisioning_config()
    auth = _get_auth_config()
    mapping = target.get("guacamole_mapping") if isinstance(target.get("guacamole_mapping"), dict) else {}
    resolved_fields = target.get("resolved_fields") if isinstance(target.get("resolved_fields"), dict) else {}
    hostname = _clean_string(resolved_fields.get("hostname"))

    if not provisioning["enabled"] or not target.get("enabled") or not mapping or not hostname:
        return target
    if not auth["username"] or not auth["password"]:
        return target

    try:
        refreshed_mapping, diagnostics = provision_guacamole_agent_target_with_diagnostics(
            agent_id,
            hostname,
            mapping,
        )
    except Exception as error:
        warnings.append(f"Guacamole provisioning reconciliation failed: {error}.")
        return target

    next_target = dict(target)
    next_target["guacamole_mapping"] = refreshed_mapping
    next_target["connection_id"] = _clean_string(refreshed_mapping.get("connection_identifier")) or _clean_string(next_target.get("connection_id"))
    next_target["connection_label"] = _clean_string(refreshed_mapping.get("connection_name")) or _clean_string(next_target.get("connection_label"))
    next_target["resolved_fields"] = {
        **resolved_fields,
        "guacamole_target_host": _clean_string(refreshed_mapping.get("target_host")) or _clean_string(resolved_fields.get("hostname")),
        "guacamole_group": _clean_string(refreshed_mapping.get("group_name")),
        "guacamole_connection_name": _clean_string(refreshed_mapping.get("connection_name")),
        "guacamole_username": _clean_string(refreshed_mapping.get("username")),
        "guacamole_domain": _clean_string(refreshed_mapping.get("domain")),
    }
    next_target["provisioning_diagnostics"] = diagnostics
    return next_target


def _resolve_connection_id(agent_id: str, metrics: dict[str, Any], guacamole_mapping: dict[str, Any]) -> tuple[str, str]:
    connection_map = _load_connection_map()
    hostname = _clean_string(metrics.get("hostname"))
    azure_vm_name = _clean_string(metrics.get("azure_vm_name"))
    public_ip = _clean_string(metrics.get("azure_public_ip"))
    private_ip = _clean_string(metrics.get("azure_private_ip"))
    target_host = _clean_string(guacamole_mapping.get("target_host"))
    mapping_connection_identifier = _clean_string(guacamole_mapping.get("connection_identifier"))
    mapping_connection_name = _clean_string(guacamole_mapping.get("connection_name"))

    if mapping_connection_identifier:
        return mapping_connection_identifier, "metadata:connection_identifier"
    if mapping_connection_name:
        return mapping_connection_name, "metadata:connection_name"

    for candidate, source in (
        (agent_id, "mapping:agent_id"),
        (target_host, "mapping:target_host"),
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
    guacamole_mapping = _extract_guacamole_mapping(agent_id, agent_state, safe_metrics)
    connection_id, source = _resolve_connection_id(agent_id, safe_metrics, guacamole_mapping)

    hostname = _clean_string(safe_metrics.get("hostname"))
    azure_vm_name = _clean_string(safe_metrics.get("azure_vm_name"))
    public_ip = _clean_string(safe_metrics.get("azure_public_ip"))
    private_ip = _clean_string(safe_metrics.get("azure_private_ip"))
    base_url = _clean_string(os.getenv("GUACAMOLE_BASE_URL")).rstrip("/")
    request_base_url = get_guacamole_request_base_url()
    auth = _get_auth_config()
    display = _get_display_config()
    recording = _get_recording_config()
    access_policy = extract_guacamole_access_policy(agent_state)
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
        "recording": {
            "enabled": bool(recording["enabled"]),
            "configured": bool(recording["configured"]),
            "create_path": bool(recording["create_path"]),
            "path_template": _clean_string(recording["path_template"]),
            "name_template": _clean_string(recording["name_template"]),
            "exclude_output": bool(recording["exclude_output"]),
            "exclude_mouse": bool(recording["exclude_mouse"]),
            "exclude_touch": bool(recording["exclude_touch"]),
            "include_keys": bool(recording["include_keys"]),
        },
        "access": access_policy,
        "guacamole_mapping": guacamole_mapping,
        "resolved_fields": {
            "hostname": hostname,
            "guacamole_target_host": _clean_string(guacamole_mapping.get("target_host")) or hostname,
            "azure_vm_name": azure_vm_name,
            "public_ip": public_ip,
            "private_ip": private_ip,
            "guacamole_group": _clean_string(guacamole_mapping.get("group_name")),
            "guacamole_connection_name": _clean_string(guacamole_mapping.get("connection_name")),
            "guacamole_username": _clean_string(guacamole_mapping.get("username")),
            "guacamole_domain": _clean_string(guacamole_mapping.get("domain")),
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
        decoded = json.loads(response.read().decode("utf-8"))
        if isinstance(decoded, dict):
            decoded["cookie_header"] = _extract_cookie_header(response.headers)
        return decoded


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


def _request_guacamole_connection_groups(base_url: str, auth_token: str, data_source: str) -> dict[str, Any]:
    decoded = _request_guacamole_json(
        base_url,
        auth_token,
        f"api/session/data/{quote(data_source, safe='')}/connectionGroups",
    )
    return decoded if isinstance(decoded, dict) else {}


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


def _request_guacamole_json_with_body(
    base_url: str,
    auth_token: str,
    path: str,
    method: str,
    payload: dict[str, Any],
) -> Any:
    request = Request(
        _join_url(base_url, path),
        data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json",
            "Guacamole-Token": auth_token,
        },
        method=method,
    )

    with urlopen(request, timeout=10) as response:
        raw_body = response.read().decode("utf-8")
        if not raw_body:
            return {}
        return json.loads(raw_body)


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


def _decode_template_json(raw_value: str) -> dict[str, Any]:
    if not raw_value:
        return {}
    try:
        decoded = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _render_template_value(value: Any, values: dict[str, str]) -> Any:
    if isinstance(value, str):
        return _render_template(value, values)
    if isinstance(value, dict):
        return {
            _clean_string(key): _render_template_value(item, values)
            for key, item in value.items()
            if _clean_string(key)
        }
    return value


def _sanitize_recording_template_value(value: str) -> str:
    cleaned = _clean_string(value)
    if not cleaned:
        return ""

    sanitized = re.sub(r"[\\/]+", "-", cleaned)
    for character in (":", "*", "?", '"', "<", ">", "|"):
        sanitized = sanitized.replace(character, "_")

    sanitized = " ".join(sanitized.split())
    return sanitized.strip(" .")


def _build_recording_template_values(values: dict[str, str], recording_owner: dict[str, Any] | None = None) -> dict[str, str]:
    sanitized_values = {
        key: _sanitize_recording_template_value(value)
        for key, value in values.items()
    }

    owner = recording_owner if isinstance(recording_owner, dict) else {}
    owner_username = _sanitize_recording_template_value(_clean_string(owner.get("username")))
    owner_display_name = _sanitize_recording_template_value(_clean_string(owner.get("display_name")))
    owner_email = _sanitize_recording_template_value(_clean_string(owner.get("email")))
    owner_subject = _sanitize_recording_template_value(_clean_string(owner.get("subject")))

    if owner_username:
        sanitized_values["vm_username"] = sanitized_values.get("username", "")
        sanitized_values["username"] = owner_username
    sanitized_values["owner_username"] = owner_username
    sanitized_values["owner_display_name"] = owner_display_name
    sanitized_values["owner_email"] = owner_email
    sanitized_values["owner_subject"] = owner_subject
    return sanitized_values


def _build_recording_entry_hint(
    agent_id: str,
    hostname: str,
    mapping: dict[str, Any],
    recording: dict[str, Any],
    recording_owner: dict[str, Any] | None = None,
) -> dict[str, str]:
    if not recording.get("enabled") or not recording.get("configured"):
        return {}

    template_values = _build_guacamole_template_values(agent_id, mapping, hostname)
    recording_values = _build_recording_template_values(template_values, recording_owner)
    relative_directory = _sanitize_recording_relative_path(_render_template(_clean_string(recording.get("path_template")), recording_values))
    recording_name = _ensure_guacamole_recording_filename(
        _render_template(_clean_string(recording.get("name_template")), recording_values)
    )
    relative_path = _sanitize_recording_relative_path(posix_join(relative_directory, recording_name))
    if not relative_path:
        return {}

    return {
        "agent_id": _clean_string(agent_id),
        "directory": relative_directory,
        "name": recording_name,
        "relative_path": relative_path,
    }


def _parse_recording_template_metadata(relative_path: str, path_template: str) -> dict[str, str]:
    clean_relative_path = _sanitize_recording_relative_path(relative_path)
    clean_template = _sanitize_recording_relative_path(path_template)
    if not clean_relative_path or not clean_template:
        return {}

    directory_parts = clean_relative_path.split("/")[:-1]
    template_parts = clean_template.split("/")
    first_dynamic_index = next((index for index, part in enumerate(template_parts) if "{" in part and "}" in part), len(template_parts))
    dynamic_template_parts = template_parts[first_dynamic_index:]
    if not dynamic_template_parts or len(directory_parts) < len(dynamic_template_parts):
        return {}

    candidate_parts = directory_parts[-len(dynamic_template_parts):]
    values: dict[str, str] = {}
    placeholder_pattern = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

    for template_part, candidate_part in zip(dynamic_template_parts, candidate_parts, strict=False):
        matches = list(placeholder_pattern.finditer(template_part))
        if not matches:
            if _clean_string(template_part) != _clean_string(candidate_part):
                return {}
            continue

        pattern_parts: list[str] = []
        last_index = 0
        for match_index, match in enumerate(matches):
            pattern_parts.append(re.escape(template_part[last_index:match.start()]))
            group_name = match.group(1)
            is_last = match_index == len(matches) - 1
            trailing_literal = template_part[match.end():matches[match_index + 1].start()] if not is_last else template_part[match.end():]
            pattern_parts.append(f"(?P<{group_name}>.+{'?' if trailing_literal else ''})")
            last_index = match.end()
        pattern_parts.append(re.escape(template_part[last_index:]))

        parsed_match = re.fullmatch("".join(pattern_parts), candidate_part)
        if not parsed_match:
            return {}

        for key, value in parsed_match.groupdict().items():
            if _clean_string(value):
                values[key] = _clean_string(value)

    return values


def _extract_recording_inventory_metadata(relative_path: str, *, path_template: str = "", fallback_agent_id: str = "", fallback_username: str = "") -> dict[str, str]:
    template_values = _parse_recording_template_metadata(relative_path, path_template)
    if template_values:
        return {
            "agent_id": _clean_string(template_values.get("agent_id")) or _clean_string(fallback_agent_id),
            "username": _clean_string(template_values.get("username")) or _clean_string(fallback_username),
        }

    path_parts = [part for part in _sanitize_recording_relative_path(relative_path).split("/") if part]
    if not path_parts:
        return {
            "agent_id": _clean_string(fallback_agent_id),
            "username": _clean_string(fallback_username),
        }

    agent_value = _clean_string(fallback_agent_id) or _clean_string(path_parts[0])
    username_value = _clean_string(fallback_username)
    if not username_value and len(path_parts) >= 3:
        username_value = _clean_string(path_parts[-2])

    return {
        "agent_id": agent_value,
        "username": username_value,
    }


def _normalize_string_dict(payload: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in payload.items():
        clean_key = _clean_string(key)
        clean_value = _clean_string(value)
        if clean_key and clean_value:
            result[clean_key] = clean_value
    return result


def _build_guacamole_template_values(
    agent_id: str,
    mapping: dict[str, Any],
    hostname: str,
    template_values: dict[str, str] | None = None,
) -> dict[str, str]:
    provisioning = _get_provisioning_config()
    provided_values = template_values or {}
    timestamp = str(int(time.time()))
    return {
        "agent_id": _clean_string(agent_id),
        "hostname": _clean_string(hostname),
        "target_host": _clean_string(mapping.get("target_host")) or _clean_string(hostname),
        "username": _clean_string(mapping.get("username")),
        "domain": _clean_string(mapping.get("domain")),
        "password": _clean_string(provided_values.get("password")) or provisioning["default_password"],
        "secret": _clean_string(provided_values.get("secret")) or provisioning["default_secret"],
        "group_name": _clean_string(mapping.get("group_name")),
        "connection_name": _clean_string(mapping.get("connection_name")),
        "timestamp": timestamp,
        "date": timestamp,
    }


def _split_guacamole_credentials(mapping: dict[str, Any]) -> tuple[str, str]:
    explicit_domain = _clean_string(mapping.get("domain"))
    username = _clean_string(mapping.get("username"))
    if not username or _is_reserved_windows_identity(username):
        return "", explicit_domain

    if explicit_domain:
        if "\\" in username:
            _, username = username.rsplit("\\", 1)
        elif "/" in username:
            _, username = username.rsplit("/", 1)
        clean_username = _clean_string(username)
        if _is_reserved_windows_identity(clean_username):
            return "", explicit_domain
        return clean_username, explicit_domain

    for separator in ("\\", "/"):
        if separator in username:
            domain, local_username = username.rsplit(separator, 1)
            clean_domain = _clean_string(domain)
            clean_username = _clean_string(local_username)
            if _is_reserved_windows_identity(f"{clean_domain}\\{clean_username}") or _is_reserved_windows_identity(clean_username):
                return "", ""
            return clean_username, clean_domain

    if _is_reserved_windows_identity(username):
        return "", ""

    return username, ""


def _normalize_attributes(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    return _normalize_string_dict(payload)


_CONNECTION_RECORDING_PARAMETER_KEYS = {
    "recording-path",
    "create-recording-path",
    "recording-name",
    "recording-exclude-output",
    "recording-exclude-mouse",
    "recording-exclude-touch",
    "recording-include-keys",
}


def _build_recorded_connection_name(connection_name: str) -> str:
    clean_name = _clean_string(connection_name)
    if not clean_name:
        return "Recorded Session"
    if clean_name.endswith(" (Recorded)"):
        return clean_name
    return f"{clean_name} (Recorded)"


def _build_recorded_connection_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    recorded_name = _build_recorded_connection_name(_clean_string(mapping.get("connection_name")))
    next_mapping = dict(mapping)
    next_mapping["connection_identifier"] = ""
    next_mapping["connection_name"] = recorded_name
    next_mapping["connection_candidates"] = _unique_strings(recorded_name)
    return next_mapping


def _request_guacamole_connection_group(base_url: str, auth_token: str, data_source: str, group_id: str) -> dict[str, Any]:
    decoded = _request_guacamole_json(
        base_url,
        auth_token,
        f"api/session/data/{quote(data_source, safe='')}/connectionGroups/{quote(group_id, safe='')}",
    )
    return decoded if isinstance(decoded, dict) else {}


def _build_guacamole_group_payload(mapping: dict[str, Any], existing_group: dict[str, Any] | None = None) -> dict[str, Any]:
    provisioning = _get_provisioning_config()
    existing_attributes = _normalize_attributes((existing_group or {}).get("attributes"))
    return {
        "name": _clean_string(mapping.get("group_name")),
        "type": "ORGANIZATIONAL",
        "parentIdentifier": _clean_string((existing_group or {}).get("parentIdentifier")) or provisioning["group_parent_identifier"],
        "attributes": existing_attributes,
    }


def _group_payload_matches(payload: dict[str, Any], existing_group: dict[str, Any]) -> bool:
    return (
        _clean_string(existing_group.get("name")) == _clean_string(payload.get("name"))
        and _clean_string(existing_group.get("type")) == _clean_string(payload.get("type"))
        and _clean_string(existing_group.get("parentIdentifier")) == _clean_string(payload.get("parentIdentifier"))
        and _normalize_attributes(existing_group.get("attributes")) == _normalize_attributes(payload.get("attributes"))
    )


def _connection_payload_matches(
    payload: dict[str, Any],
    existing_connection: dict[str, Any],
    existing_parameters: dict[str, str],
) -> bool:
    return (
        _clean_string(existing_connection.get("name")) == _clean_string(payload.get("name"))
        and _clean_string(existing_connection.get("protocol")) == _clean_string(payload.get("protocol"))
        and _clean_string(existing_connection.get("parentIdentifier")) == _clean_string(payload.get("parentIdentifier"))
        and _normalize_attributes(existing_connection.get("attributes")) == _normalize_attributes(payload.get("attributes"))
        and _normalize_string_dict(existing_parameters) == _normalize_string_dict(payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {})
    )


def _build_guacamole_connection_payload(
    agent_id: str,
    mapping: dict[str, Any],
    hostname: str,
    template_values: dict[str, str] | None = None,
    existing_connection: dict[str, Any] | None = None,
    existing_parameters: dict[str, str] | None = None,
    *,
    apply_recording: bool = False,
    recording_owner: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provisioning = _get_provisioning_config()
    recording = _get_recording_config()
    access_policy = normalize_guacamole_access_policy(mapping.get("access"))
    file_transfer = access_policy.get("file_transfer") if isinstance(access_policy.get("file_transfer"), dict) else {}
    values = _build_guacamole_template_values(agent_id, mapping, hostname, template_values)
    template_parameters = _render_template_value(
        _decode_template_json(provisioning["parameter_template_json"]),
        values,
    )
    template_attributes = _render_template_value(
        _decode_template_json(provisioning["attribute_template_json"]),
        values,
    )

    parameters = {
        **_normalize_string_dict(existing_parameters or {}),
        "hostname": _clean_string(mapping.get("target_host")) or _clean_string(hostname),
        "port": provisioning["rdp_port"],
        "resize-method": "display-update",
        "ignore-cert": "true",
    }
    username, domain = _split_guacamole_credentials(mapping)
    if username:
        parameters["username"] = username
    if domain:
        parameters["domain"] = domain
    parameters.update(_normalize_string_dict(template_parameters if isinstance(template_parameters, dict) else {}))

    upload_enabled = bool(file_transfer.get("upload_enabled", True))
    download_enabled = bool(file_transfer.get("download_enabled", True))
    if upload_enabled or download_enabled:
        parameters["enable-drive"] = "true"
        parameters["create-drive-path"] = "true"
        parameters["drive-path"] = _clean_string(parameters.get("drive-path")) or "/drive"
        parameters["disable-upload"] = "false" if upload_enabled else "true"
        parameters["disable-download"] = "false" if download_enabled else "true"
    else:
        parameters["enable-drive"] = "false"
        parameters["disable-upload"] = "true"
        parameters["disable-download"] = "true"
        parameters.pop("create-drive-path", None)
        parameters.pop("drive-path", None)

    for key in _CONNECTION_RECORDING_PARAMETER_KEYS:
        parameters.pop(key, None)

    if apply_recording and recording["enabled"] and recording["configured"]:
        recording_values = _build_recording_template_values(values, recording_owner)
        recording_path = _render_template(recording["path_template"], recording_values)
        recording_name = _ensure_guacamole_recording_filename(_render_template(recording["name_template"], recording_values))
        if recording_path:
            parameters["recording-path"] = recording_path
            parameters["create-recording-path"] = "true" if recording["create_path"] else "false"
            if recording_name:
                parameters["recording-name"] = recording_name
            parameters["recording-exclude-output"] = "true" if recording["exclude_output"] else "false"
            parameters["recording-exclude-mouse"] = "true" if recording["exclude_mouse"] else "false"
            parameters["recording-exclude-touch"] = "true" if recording["exclude_touch"] else "false"
            parameters["recording-include-keys"] = "true" if recording["include_keys"] else "false"

    attributes = {
        **_normalize_attributes((existing_connection or {}).get("attributes")),
        **_normalize_attributes(template_attributes),
    }

    return {
        "name": _clean_string(mapping.get("connection_name")) or _clean_string(hostname),
        "parentIdentifier": _clean_string(mapping.get("group_identifier")) or provisioning["group_parent_identifier"],
        "protocol": provisioning["protocol"],
        "parameters": parameters,
        "attributes": attributes,
    }


def _upsert_guacamole_group(base_url: str, auth_token: str, data_source: str, mapping: dict[str, Any]) -> dict[str, str]:
    group_id = _clean_string(mapping.get("group_identifier"))
    group_name = _clean_string(mapping.get("group_name"))
    existing_group: dict[str, Any] = {}

    def _resolve_group_after_stale_identifier() -> tuple[str, str]:
        return _resolve_connection_group_identifier(
            base_url,
            auth_token,
            data_source,
            _unique_strings(*list(mapping.get("group_candidates") or []), group_name),
        )

    if not group_id:
        group_id, resolved_name = _resolve_connection_group_identifier(
            base_url,
            auth_token,
            data_source,
            list(mapping.get("group_candidates") or []),
        )
        if resolved_name:
            group_name = resolved_name

    if group_id:
        try:
            existing_group = _request_guacamole_connection_group(base_url, auth_token, data_source, group_id)
        except HTTPError as error:
            if error.code != 404:
                raise
            group_id = ""
            existing_group = {}
            resolved_group_id, resolved_group_name = _resolve_group_after_stale_identifier()
            if resolved_group_id:
                group_id = resolved_group_id
                if resolved_group_name:
                    group_name = resolved_group_name
                existing_group = _request_guacamole_connection_group(base_url, auth_token, data_source, group_id)
        if _clean_string(existing_group.get("name")):
            group_name = _clean_string(existing_group.get("name"))

    payload = _build_guacamole_group_payload({**mapping, "group_name": group_name, "group_identifier": group_id}, existing_group)

    if group_id:
        if _group_payload_matches(payload, existing_group):
            return {"identifier": group_id, "name": group_name, "action": "reused"}
        try:
            _request_guacamole_json_with_body(
                base_url,
                auth_token,
                f"api/session/data/{quote(data_source, safe='')}/connectionGroups/{quote(group_id, safe='')}",
                "PUT",
                payload,
            )
            return {"identifier": group_id, "name": group_name, "action": "updated"}
        except HTTPError as error:
            if error.code != 404:
                raise
            group_id = ""
            resolved_group_id, resolved_group_name = _resolve_group_after_stale_identifier()
            if resolved_group_id:
                group_id = resolved_group_id
                if resolved_group_name:
                    group_name = resolved_group_name
                existing_group = _request_guacamole_connection_group(base_url, auth_token, data_source, group_id)
                if _group_payload_matches(payload, existing_group):
                    return {"identifier": group_id, "name": group_name, "action": "reused"}
                _request_guacamole_json_with_body(
                    base_url,
                    auth_token,
                    f"api/session/data/{quote(data_source, safe='')}/connectionGroups/{quote(group_id, safe='')}",
                    "PUT",
                    payload,
                )
                return {"identifier": group_id, "name": group_name, "action": "updated"}

    created = _request_guacamole_json_with_body(
        base_url,
        auth_token,
        f"api/session/data/{quote(data_source, safe='')}/connectionGroups",
        "POST",
        payload,
    )
    created_id = _clean_string(created.get("identifier")) if isinstance(created, dict) else _clean_string(created)
    return {"identifier": created_id, "name": group_name, "action": "created"}


def _upsert_guacamole_connection(
    base_url: str,
    auth_token: str,
    data_source: str,
    agent_id: str,
    mapping: dict[str, Any],
    hostname: str,
    template_values: dict[str, str] | None = None,
    *,
    apply_recording: bool = False,
    recording_owner: dict[str, Any] | None = None,
) -> dict[str, str]:
    connection_id = _clean_string(mapping.get("connection_identifier"))
    connection_name = _clean_string(mapping.get("connection_name")) or _clean_string(hostname)
    parent_identifier = _clean_string(mapping.get("group_identifier"))
    existing_connection: dict[str, Any] = {}
    existing_parameters: dict[str, str] = {}

    def _resolve_connection_after_stale_identifier() -> tuple[str, str]:
        return _resolve_connection_identifier(
            base_url,
            auth_token,
            data_source,
            _unique_strings(*list(mapping.get("connection_candidates") or []), connection_name),
            parent_identifier=parent_identifier,
        )

    if not connection_id:
        connection_id, resolved_name = _resolve_connection_identifier(
            base_url,
            auth_token,
            data_source,
            list(mapping.get("connection_candidates") or []),
            parent_identifier=parent_identifier,
        )
        if resolved_name:
            connection_name = resolved_name

    if connection_id:
        try:
            existing_connection = _request_guacamole_connection(base_url, auth_token, data_source, connection_id)
            existing_parameters = _request_guacamole_connection_parameters(base_url, auth_token, data_source, connection_id)
        except HTTPError as error:
            if error.code != 404:
                raise
            connection_id = ""
            existing_connection = {}
            existing_parameters = {}
            resolved_connection_id, resolved_connection_name = _resolve_connection_after_stale_identifier()
            if resolved_connection_id:
                connection_id = resolved_connection_id
                if resolved_connection_name:
                    connection_name = resolved_connection_name
                existing_connection = _request_guacamole_connection(base_url, auth_token, data_source, connection_id)
                existing_parameters = _request_guacamole_connection_parameters(base_url, auth_token, data_source, connection_id)
        if _clean_string(existing_connection.get("name")):
            connection_name = _clean_string(existing_connection.get("name"))

    payload = _build_guacamole_connection_payload(
        agent_id,
        {**mapping, "connection_name": connection_name, "connection_identifier": connection_id},
        hostname,
        template_values,
        existing_connection,
        existing_parameters,
        apply_recording=apply_recording,
        recording_owner=recording_owner,
    )

    if connection_id:
        if _connection_payload_matches(payload, existing_connection, existing_parameters):
            return {"identifier": connection_id, "name": connection_name or payload["name"], "action": "reused"}
        try:
            _request_guacamole_json_with_body(
                base_url,
                auth_token,
                f"api/session/data/{quote(data_source, safe='')}/connections/{quote(connection_id, safe='')}",
                "PUT",
                payload,
            )
            return {"identifier": connection_id, "name": connection_name or payload["name"], "action": "updated"}
        except HTTPError as error:
            if error.code != 404:
                raise
            connection_id = ""
            resolved_connection_id, resolved_connection_name = _resolve_connection_after_stale_identifier()
            if resolved_connection_id:
                connection_id = resolved_connection_id
                if resolved_connection_name:
                    connection_name = resolved_connection_name
                existing_connection = _request_guacamole_connection(base_url, auth_token, data_source, connection_id)
                existing_parameters = _request_guacamole_connection_parameters(base_url, auth_token, data_source, connection_id)
                if _connection_payload_matches(payload, existing_connection, existing_parameters):
                    return {"identifier": connection_id, "name": connection_name or payload["name"], "action": "reused"}
                _request_guacamole_json_with_body(
                    base_url,
                    auth_token,
                    f"api/session/data/{quote(data_source, safe='')}/connections/{quote(connection_id, safe='')}",
                    "PUT",
                    payload,
                )
                return {"identifier": connection_id, "name": connection_name or payload["name"], "action": "updated"}

    created = _request_guacamole_json_with_body(
        base_url,
        auth_token,
        f"api/session/data/{quote(data_source, safe='')}/connections",
        "POST",
        payload,
    )
    created_id = _clean_string(created.get("identifier")) if isinstance(created, dict) else _clean_string(created)
    return {"identifier": created_id, "name": connection_name or payload["name"], "action": "created"}


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
    target = _reconcile_provisioned_target(agent_id, target, warnings)
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
        mapping = target.get("guacamole_mapping") if isinstance(target.get("guacamole_mapping"), dict) else {}
        resolved_group_id = _clean_string(mapping.get("group_identifier"))

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

        if not resolved_group_id:
            step_started_at = time.perf_counter()
            resolved_group_id, resolved_group_name = _resolve_connection_group_identifier(
                target["request_base_url"],
                auth_token,
                data_source,
                list(mapping.get("group_candidates") or []),
            )
            record_timing("resolve_group", step_started_at)
            if resolved_group_id:
                mapping["group_identifier"] = resolved_group_id
                if resolved_group_name:
                    mapping["group_name"] = resolved_group_name

        step_started_at = time.perf_counter()
        resolved_connection_id, resolved_connection_name = _resolve_connection_identifier(
            target["request_base_url"],
            auth_token,
            data_source,
            _unique_strings(
                *list(mapping.get("connection_candidates") or []),
                target["connection_id"],
                target["connection_label"],
                _clean_string(target.get("resolved_fields", {}).get("guacamole_target_host")),
                _clean_string(target.get("resolved_fields", {}).get("hostname")),
                agent_id,
            ),
            parent_identifier=resolved_group_id,
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


def _resolve_connection_group_identifier(
    base_url: str,
    auth_token: str,
    data_source: str,
    candidates: list[str],
) -> tuple[str, str]:
    decoded = _request_guacamole_connection_groups(base_url, auth_token, data_source)
    if not isinstance(decoded, dict):
        return "", ""

    normalized_candidates = [candidate.strip().casefold() for candidate in candidates if candidate and candidate.strip()]
    if not normalized_candidates:
        return "", ""

    normalized_groups: list[tuple[set[str], str, str]] = []
    for identifier, payload in decoded.items():
        clean_identifier = _clean_string(identifier)
        item = payload if isinstance(payload, dict) else {}
        item_identifier = _clean_string(item.get("identifier")) or clean_identifier
        item_name = _clean_string(item.get("name"))
        normalized_groups.append((
            {item_identifier.casefold(), item_name.casefold(), clean_identifier.casefold()},
            item_identifier,
            item_name,
        ))

    for candidate in normalized_candidates:
        for values, item_identifier, item_name in normalized_groups:
            if candidate in values:
                return item_identifier, item_name

    return "", ""


def _resolve_connection_identifier(
    base_url: str,
    auth_token: str,
    data_source: str,
    candidates: list[str],
    parent_identifier: str = "",
) -> tuple[str, str]:
    decoded = _request_guacamole_connections(base_url, auth_token, data_source)
    if not isinstance(decoded, dict):
        return "", ""

    normalized_candidates = [candidate.strip().casefold() for candidate in candidates if candidate and candidate.strip()]
    if not normalized_candidates:
        return "", ""

    normalized_connections: list[tuple[set[str], str, str]] = []
    for identifier, payload in decoded.items():
        clean_identifier = _clean_string(identifier)
        item = payload if isinstance(payload, dict) else {}
        item_identifier = _clean_string(item.get("identifier")) or clean_identifier
        item_name = _clean_string(item.get("name"))
        item_parent_identifier = _clean_string(item.get("parentIdentifier"))
        if parent_identifier and item_parent_identifier != parent_identifier:
            continue
        normalized_connections.append((
            {item_identifier.casefold(), item_name.casefold(), clean_identifier.casefold()},
            item_identifier,
            item_name,
        ))

    for candidate in normalized_candidates:
        for values, item_identifier, item_name in normalized_connections:
            if candidate in values:
                return item_identifier, item_name

    return "", ""


def provision_guacamole_agent_target(agent_id: str, hostname: str, mapping: dict[str, Any]) -> dict[str, Any]:
    next_mapping, _ = provision_guacamole_agent_target_with_diagnostics(agent_id, hostname, mapping)
    return next_mapping


def provision_guacamole_agent_target_with_diagnostics(
    agent_id: str,
    hostname: str,
    mapping: dict[str, Any],
    *,
    template_values: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    config = get_guacamole_config()
    auth = _get_auth_config()
    provisioning = _get_provisioning_config()
    base_diagnostics = {
        "enabled": bool(provisioning["enabled"] and config["enabled"]),
        "data_source": "",
        "group": {"action": "skipped", "identifier": _clean_string(mapping.get("group_identifier")), "name": _clean_string(mapping.get("group_name"))},
        "connection": {
            "action": "skipped",
            "identifier": _clean_string(mapping.get("connection_identifier")),
            "name": _clean_string(mapping.get("connection_name")),
        },
        "detail": "",
    }

    if not provisioning["enabled"]:
        base_diagnostics["detail"] = "Guacamole auto provisioning is disabled."
        return dict(mapping), base_diagnostics
    if not config["enabled"]:
        base_diagnostics["detail"] = "Guacamole bridge is disabled."
        return dict(mapping), base_diagnostics
    if not auth["username"] or not auth["password"]:
        raise RuntimeError("Guacamole auto provisioning requires GUACAMOLE_AUTH_USERNAME and GUACAMOLE_AUTH_PASSWORD.")

    auth_response = _request_guacamole_token(config["request_base_url"], auth["username"], auth["password"])
    auth_token = _clean_string(auth_response.get("authToken"))
    auth_cookie_header = _clean_string(auth_response.get("cookie_header"))
    data_source = _clean_string(auth_response.get("dataSource")) or auth["provider"] or "default"
    if not auth_token:
        raise RuntimeError("Guacamole auto provisioning could not obtain an auth token.")

    next_mapping = dict(mapping)
    base_diagnostics["data_source"] = data_source
    group_result = _upsert_guacamole_group(config["request_base_url"], auth_token, data_source, next_mapping)
    next_mapping["group_identifier"] = group_result.get("identifier", "")
    if group_result.get("name"):
        next_mapping["group_name"] = group_result["name"]
    base_diagnostics["group"] = {
        "action": _clean_string(group_result.get("action")) or "updated",
        "identifier": _clean_string(group_result.get("identifier")),
        "name": _clean_string(group_result.get("name")),
    }

    connection_result = _upsert_guacamole_connection(
        config["request_base_url"],
        auth_token,
        data_source,
        agent_id,
        next_mapping,
        hostname,
        template_values,
    )
    next_mapping["connection_identifier"] = connection_result.get("identifier", "")
    if connection_result.get("name"):
        next_mapping["connection_name"] = connection_result["name"]
    base_diagnostics["connection"] = {
        "action": _clean_string(connection_result.get("action")) or "updated",
        "identifier": _clean_string(connection_result.get("identifier")),
        "name": _clean_string(connection_result.get("name")),
    }

    next_mapping["group_candidates"] = _unique_strings(
        *list(next_mapping.get("group_candidates") or []),
        next_mapping.get("group_name"),
        agent_id,
    )
    next_mapping["connection_candidates"] = _unique_strings(
        *list(next_mapping.get("connection_candidates") or []),
        next_mapping.get("connection_identifier"),
        next_mapping.get("connection_name"),
        hostname,
        agent_id,
    )
    return next_mapping, base_diagnostics


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
    *,
    connection_id: str = "",
    vm_username: str = "",
    recording_owner: dict[str, Any] | None = None,
    recorded: bool = False,
) -> dict[str, Any]:
    target = _resolve_target(agent_id, agent_state)
    auth = _get_auth_config()
    warnings = list(target["warnings"])

    requested_connection_id = _clean_string(connection_id)
    requested_vm_username = _clean_string(vm_username)
    if not requested_connection_id and not requested_vm_username:
        target = _reconcile_provisioned_target(agent_id, target, warnings)

    if requested_connection_id or requested_vm_username:
        try:
            session_inventory = list_vm_user_sessions(
                agent_id,
                agent_state,
                maintain_connections=True,
            )
        except Exception as error:
            warnings.append(f"Per-user Guacamole reconciliation failed: {error}.")
            session_inventory = []
        matched_entry = None
        requested_username_variants = {variant.casefold() for variant in _build_username_variants(requested_vm_username)}
        if requested_username_variants:
            for entry in session_inventory:
                entry_username_variants = {variant.casefold() for variant in _build_username_variants(entry.get("username"))}
                if requested_username_variants & entry_username_variants:
                    matched_entry = entry
                    break

        if matched_entry is None and requested_connection_id:
            for entry in session_inventory:
                guacamole_entry = entry.get("guacamole") if isinstance(entry.get("guacamole"), dict) else {}
                entry_connection_id = _clean_string(guacamole_entry.get("connection_id"))
                if entry_connection_id == requested_connection_id:
                    matched_entry = entry
                    break

        if matched_entry:
            guacamole_entry = matched_entry.get("guacamole") if isinstance(matched_entry.get("guacamole"), dict) else {}
            target["connection_id"] = _clean_string(guacamole_entry.get("connection_id")) or requested_connection_id or target["connection_id"]
            target["connection_label"] = _clean_string(guacamole_entry.get("connection_name")) or _clean_string(matched_entry.get("username")) or target["connection_label"]
            mapping = target.get("guacamole_mapping") if isinstance(target.get("guacamole_mapping"), dict) else {}
            mapping["group_identifier"] = _clean_string(guacamole_entry.get("group_identifier")) or _clean_string(mapping.get("group_identifier"))
            mapping["group_name"] = _clean_string(guacamole_entry.get("group_name")) or _clean_string(mapping.get("group_name"))
            mapping["connection_identifier"] = _clean_string(guacamole_entry.get("connection_id")) or _clean_string(mapping.get("connection_identifier"))
            mapping["connection_name"] = _clean_string(guacamole_entry.get("connection_name")) or _clean_string(mapping.get("connection_name"))
            mapping["username"] = _clean_string(matched_entry.get("username")) or _clean_string(mapping.get("username"))
            target["guacamole_mapping"] = mapping
            resolved_fields = target.get("resolved_fields") if isinstance(target.get("resolved_fields"), dict) else {}
            resolved_fields["guacamole_group"] = _clean_string(guacamole_entry.get("group_name")) or _clean_string(resolved_fields.get("guacamole_group"))
            resolved_fields["guacamole_connection_name"] = _clean_string(guacamole_entry.get("connection_name")) or _clean_string(resolved_fields.get("guacamole_connection_name"))
            resolved_fields["guacamole_username"] = _clean_string(matched_entry.get("username")) or _clean_string(resolved_fields.get("guacamole_username"))
            target["resolved_fields"] = resolved_fields
        elif requested_connection_id and not requested_vm_username:
            target["connection_id"] = requested_connection_id

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
    auth_cookie_header = _clean_string(auth_response.get("cookie_header"))
    data_source = _clean_string(auth_response.get("dataSource")) or auth["provider"] or "default"
    mapping = target.get("guacamole_mapping") if isinstance(target.get("guacamole_mapping"), dict) else {}
    recording = target.get("recording") if isinstance(target.get("recording"), dict) else {}

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
    resolved_group_id = _clean_string(mapping.get("group_identifier"))
    recorded_connection_ready = False
    recording_entry_hint: dict[str, str] = {}

    if recorded:
        if not recording.get("enabled"):
            warnings.append("On-demand recording is disabled in Guacamole settings.")
            return {
                **target,
                "status": "needs_configuration",
                "client_session": None,
                "warnings": warnings,
            }
        if not recording.get("configured"):
            warnings.append("On-demand recording is not fully configured. Check the recording path template.")
            return {
                **target,
                "status": "needs_configuration",
                "client_session": None,
                "warnings": warnings,
            }

        hostname = (
            _clean_string(target.get("resolved_fields", {}).get("guacamole_target_host"))
            or _clean_string(target.get("resolved_fields", {}).get("hostname"))
            or _clean_string(mapping.get("target_host"))
            or agent_id
        )

        try:
            group_result = _upsert_guacamole_group(target["request_base_url"], auth_token, data_source, mapping)
            if group_result.get("identifier"):
                resolved_group_id = _clean_string(group_result.get("identifier"))
                mapping["group_identifier"] = resolved_group_id
            if group_result.get("name"):
                mapping["group_name"] = _clean_string(group_result.get("name"))

            recorded_mapping = _build_recorded_connection_mapping(mapping)
            if resolved_group_id:
                recorded_mapping["group_identifier"] = resolved_group_id
            recorded_result = _upsert_guacamole_connection(
                target["request_base_url"],
                auth_token,
                data_source,
                agent_id,
                recorded_mapping,
                hostname,
                apply_recording=True,
                recording_owner=recording_owner,
            )
            resolved_connection_id = _clean_string(recorded_result.get("identifier")) or resolved_connection_id
            resolved_connection_name = _clean_string(recorded_result.get("name")) or _clean_string(recorded_mapping.get("connection_name")) or resolved_connection_name
            recorded_connection_ready = bool(resolved_connection_id)
            recording_entry_hint = _build_recording_entry_hint(agent_id, hostname, recorded_mapping, recording, recording_owner)
        except HTTPError as error:
            warnings.append(f"Could not provision recorded Guacamole connection: HTTP {error.code}.")
        except URLError as error:
            warnings.append(f"Could not provision recorded Guacamole connection: {error.reason}.")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            warnings.append(f"Could not provision recorded Guacamole connection: {error}.")

        if not recorded_connection_ready:
            return {
                **target,
                "status": "needs_configuration",
                "client_session": None,
                "warnings": warnings,
            }

    if not recorded_connection_ready:
        try:
            if not resolved_group_id:
                group_lookup_id, group_lookup_name = _resolve_connection_group_identifier(
                    target["request_base_url"],
                    auth_token,
                    data_source,
                    list(mapping.get("group_candidates") or []),
                )
                if group_lookup_id:
                    resolved_group_id = group_lookup_id
                    mapping["group_identifier"] = group_lookup_id
                    if group_lookup_name:
                        mapping["group_name"] = group_lookup_name

            lookup_id, lookup_name = _resolve_connection_identifier(
                target["request_base_url"],
                auth_token,
                data_source,
                _unique_strings(
                    *list(mapping.get("connection_candidates") or []),
                    target["connection_id"],
                    target["connection_label"],
                    _clean_string(target.get("resolved_fields", {}).get("guacamole_target_host")),
                    _clean_string(target.get("resolved_fields", {}).get("hostname")),
                    agent_id,
                ),
                parent_identifier=resolved_group_id,
            )
            if lookup_id:
                resolved_connection_id = lookup_id
            if lookup_name:
                resolved_connection_name = lookup_name
            elif not lookup_id:
                warnings.append(
                    "No Guacamole connection matched the stored agent mapping. Verify the agent group, connection name, or the explicit GUACAMOLE_CONNECTION_MAP_JSON override."
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
            "auth_cookie_header": auth_cookie_header,
            "data_source": data_source,
            "connection_id": resolved_connection_id,
            "connection_type": auth["connection_type"],
            "display": target["display"],
            "tunnels": tunnel_urls or target["tunnels"],
        },
        "recording_entry": recording_entry_hint,
        "warnings": warnings,
    }


def build_guacamole_session(agent_id: str, agent_state: dict[str, Any] | None) -> dict[str, Any]:
    return _resolve_target(agent_id, agent_state)