from __future__ import annotations

import asyncio
from typing import Any

from vm_agent_server.src.settings.db import ServerSettingsDB
from vm_agent_server.src.settings.models import ServerSettings, ServerSettingsPatch


def _deep_merge(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for key, value in patch.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class ServerSettingsService:
    def __init__(self, store: ServerSettingsDB):
        self._store = store
        self._settings = ServerSettings()
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self._settings = await self._store.load()

    def get_snapshot(self) -> ServerSettings:
        return self._settings.model_copy(deep=True)

    async def update(self, patch: ServerSettingsPatch) -> ServerSettings:
        async with self._lock:
            patch_payload = patch.model_dump(exclude_none=True)
            if not patch_payload:
                return self.get_snapshot()

            current_payload = self._settings.model_dump(mode="python")
            next_payload = _deep_merge(current_payload, patch_payload)
            next_settings = ServerSettings.model_validate(next_payload)
            await self._store.save(next_settings)
            self._settings = next_settings
            return self.get_snapshot()

    async def replace(self, settings: ServerSettings) -> ServerSettings:
        async with self._lock:
            await self._store.save(settings)
            self._settings = settings
            return self.get_snapshot()