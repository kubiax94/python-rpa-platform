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

    if os.getenv("VM_AGENT_SERVER_URL"):
        payload["server_url"] = os.getenv("VM_AGENT_SERVER_URL")
    if os.getenv("VM_AGENT_SECRET"):
        payload["secret"] = os.getenv("VM_AGENT_SECRET")
    if os.getenv("VM_AGENT_BOOTSTRAP_TOKEN"):
        payload["bootstrap_token"] = os.getenv("VM_AGENT_BOOTSTRAP_TOKEN")
    if os.getenv("VM_AGENT_ID"):
        payload["agent_id"] = os.getenv("VM_AGENT_ID")

    return payload