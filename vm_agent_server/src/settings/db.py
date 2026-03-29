from __future__ import annotations

import json
import logging
import time

import aiosqlite

from vm_agent_server.src.settings.models import ServerSettings

logger = logging.getLogger(__name__)

SERVER_SETTINGS_DB_PATH = "server_settings.db"
SERVER_SETTINGS_ROW_ID = "server-settings"

SCHEMA = """
CREATE TABLE IF NOT EXISTS server_settings (
    id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
"""


class ServerSettingsDB:
    def __init__(self, db_path: str = SERVER_SETTINGS_DB_PATH):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        logger.info("ServerSettingsDB started: %s", self._db_path)

    async def stop(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
        logger.info("ServerSettingsDB stopped")

    async def load(self) -> ServerSettings:
        if self._db is None:
            raise RuntimeError("ServerSettingsDB is not started")

        async with self._db.execute(
            "SELECT payload_json FROM server_settings WHERE id = ?",
            (SERVER_SETTINGS_ROW_ID,),
        ) as cursor:
            row = await cursor.fetchone()

        if not row or not row[0]:
            return ServerSettings()

        try:
            payload = json.loads(row[0])
        except json.JSONDecodeError:
            logger.warning("Failed to decode server settings JSON, using defaults")
            return ServerSettings()

        try:
            return ServerSettings.model_validate(payload)
        except Exception as error:
            logger.warning("Failed to validate server settings payload, using defaults: %s", error)
            return ServerSettings()

    async def save(self, settings: ServerSettings) -> None:
        if self._db is None:
            raise RuntimeError("ServerSettingsDB is not started")

        now = int(time.time())
        payload_json = json.dumps(settings.model_dump(mode="json"), ensure_ascii=True)
        await self._db.execute(
            """
            INSERT INTO server_settings (id, payload_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (SERVER_SETTINGS_ROW_ID, payload_json, now),
        )
        await self._db.commit()