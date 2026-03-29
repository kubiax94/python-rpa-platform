from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _candidate_paths() -> list[Path]:
    candidates: list[Path] = []

    executable_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
    candidates.append(executable_dir / "agent.bootstrap.json")
    candidates.append(Path.cwd() / "agent.bootstrap.json")
    return candidates


def get_agent_runtime_config_path() -> Path:
    return _candidate_paths()[0]


def load_agent_runtime_config() -> dict[str, Any]:
    payload: dict[str, Any] = {}

    for path in _candidate_paths():
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            break

    if not isinstance(payload, dict):
        payload = {}

    # Normalize legacy key name to the newer access_token naming.
    if payload.get("secret") and not payload.get("access_token"):
        payload["access_token"] = payload.get("secret")
    payload.pop("secret", None)

    if os.getenv("VM_AGENT_SERVER_URL"):
        payload["server_url"] = os.getenv("VM_AGENT_SERVER_URL")
    if os.getenv("VM_AGENT_ACCESS_TOKEN"):
        payload["access_token"] = os.getenv("VM_AGENT_ACCESS_TOKEN")
    elif os.getenv("VM_AGENT_SECRET"):
        payload["access_token"] = os.getenv("VM_AGENT_SECRET")
    if os.getenv("VM_AGENT_BOOTSTRAP_TOKEN"):
        payload["bootstrap_token"] = os.getenv("VM_AGENT_BOOTSTRAP_TOKEN")
    if os.getenv("VM_AGENT_ID"):
        payload["agent_id"] = os.getenv("VM_AGENT_ID")

    return payload


def persist_agent_runtime_config(payload: dict[str, Any]):
    target_path = get_agent_runtime_config_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_payload = dict(payload)
    if normalized_payload.get("secret") and not normalized_payload.get("access_token"):
        normalized_payload["access_token"] = normalized_payload.get("secret")
    normalized_payload.pop("secret", None)
    target_path.write_text(json.dumps(normalized_payload, indent=2), encoding="utf-8")