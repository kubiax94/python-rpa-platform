from __future__ import annotations

import json
import logging
import os
import time

import aiosqlite

from vm_agent_server.src.users.models import RecentUserIdentity, UserIdentity

logger = logging.getLogger(__name__)

RECENT_USERS_DB_PATH = os.getenv("VM_AGENT_RECENT_USERS_DB_PATH", "recent_users.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS recent_users (
    subject TEXT PRIMARY KEY,
    username TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    avatar_url TEXT NOT NULL DEFAULT '',
    avatar_initials TEXT NOT NULL DEFAULT '',
    auth_provider TEXT NOT NULL DEFAULT '',
    roles_json TEXT NOT NULL DEFAULT '[]',
    group_ids_json TEXT NOT NULL DEFAULT '[]',
    group_names_json TEXT NOT NULL DEFAULT '[]',
    last_seen_at INTEGER NOT NULL DEFAULT 0
);
"""


class RecentUsersDB:
    def __init__(self, db_path: str = RECENT_USERS_DB_PATH):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        logger.info("RecentUsersDB started: %s", self._db_path)

    async def stop(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
        logger.info("RecentUsersDB stopped")

    async def record_identity(self, identity: UserIdentity) -> None:
        if self._db is None:
            raise RuntimeError("RecentUsersDB is not started")

        now = int(time.time())
        await self._db.execute(
            """
            INSERT INTO recent_users (
                subject, username, display_name, email, avatar_url, avatar_initials,
                auth_provider, roles_json, group_ids_json, group_names_json, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(subject) DO UPDATE SET
                username = excluded.username,
                display_name = excluded.display_name,
                email = excluded.email,
                avatar_url = excluded.avatar_url,
                avatar_initials = excluded.avatar_initials,
                auth_provider = excluded.auth_provider,
                roles_json = excluded.roles_json,
                group_ids_json = excluded.group_ids_json,
                group_names_json = excluded.group_names_json,
                last_seen_at = excluded.last_seen_at
            """,
            (
                identity.subject,
                identity.username,
                identity.display_name,
                identity.email,
                identity.avatar_url,
                identity.avatar_initials,
                identity.auth_provider,
                json.dumps(identity.roles),
                json.dumps(identity.group_ids),
                json.dumps(identity.group_names),
                now,
            ),
        )
        await self._db.commit()

    async def list_recent(self, limit: int = 100) -> list[RecentUserIdentity]:
        if self._db is None:
            raise RuntimeError("RecentUsersDB is not started")

        rows: list[RecentUserIdentity] = []
        async with self._db.execute(
            "SELECT subject, username, display_name, email, avatar_url, avatar_initials, auth_provider, roles_json, group_ids_json, group_names_json, last_seen_at FROM recent_users ORDER BY last_seen_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            async for row in cursor:
                rows.append(
                    RecentUserIdentity(
                        subject=row[0],
                        username=row[1],
                        display_name=row[2],
                        email=row[3],
                        avatar_url=row[4],
                        avatar_initials=row[5],
                        auth_provider=row[6],
                        roles=json.loads(row[7] or "[]"),
                        group_ids=json.loads(row[8] or "[]"),
                        group_names=json.loads(row[9] or "[]"),
                        last_seen_at=int(row[10] or 0),
                    )
                )
        return rows