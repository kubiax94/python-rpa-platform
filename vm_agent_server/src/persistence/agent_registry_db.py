from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from typing import Any, Optional

import aiosqlite

from shared.security.agent_jwt import AgentJwtError, looks_like_jwt
from vm_agent_server.src.agent_auth import issue_agent_access_token, verify_agent_access_token

logger = logging.getLogger(__name__)
BOOTSTRAP_RECOVERY_WINDOW_SECONDS = int(os.getenv("VM_AGENT_BOOTSTRAP_RECOVERY_WINDOW_SECONDS", str(24 * 60 * 60)))

AGENT_REGISTRY_DB_PATH = os.getenv("VM_AGENT_AGENT_REGISTRY_DB_PATH", "agents.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id                  TEXT PRIMARY KEY,
    hostname            TEXT NOT NULL DEFAULT '',
    display_name        TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'registered',
    connection_status   TEXT NOT NULL DEFAULT 'offline',
    current_version     TEXT NOT NULL DEFAULT '',
    last_deployment_id  TEXT REFERENCES agent_deployments(id),
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    created_at          INTEGER NOT NULL,
    updated_at          INTEGER NOT NULL,
    last_seen_at        INTEGER
);

CREATE INDEX IF NOT EXISTS idx_agents_hostname ON agents(hostname);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status, connection_status);

CREATE TABLE IF NOT EXISTS agent_credentials (
    agent_id                TEXT PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
    bootstrap_token_hash    TEXT,
    bootstrap_expires_at    INTEGER,
    bootstrap_used_at       INTEGER,
    secret_hash             TEXT,
    secret_rotated_at       INTEGER,
    token_version           INTEGER NOT NULL DEFAULT 0,
    created_at              INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    updated_at              INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_deployments (
    id                  TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    release_id          TEXT REFERENCES agent_releases(id),
    hostname            TEXT NOT NULL,
    requested_by        TEXT NOT NULL DEFAULT 'user',
    status              TEXT NOT NULL DEFAULT 'queued',
    task_id             TEXT,
    commit_sha          TEXT NOT NULL DEFAULT '',
    tag_name            TEXT NOT NULL DEFAULT '',
    artifact_dir        TEXT NOT NULL DEFAULT '',
    artifact_exe_path   TEXT NOT NULL DEFAULT '',
    package_zip_path    TEXT NOT NULL DEFAULT '',
    bootstrap_path      TEXT NOT NULL DEFAULT '',
    install_script_path TEXT NOT NULL DEFAULT '',
    installer_copy_path TEXT NOT NULL DEFAULT '',
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    error               TEXT,
    build_log           TEXT NOT NULL DEFAULT '',
    created_at          INTEGER NOT NULL,
    started_at          INTEGER,
    completed_at        INTEGER
);

CREATE INDEX IF NOT EXISTS idx_deployments_agent ON agent_deployments(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_deployments_status ON agent_deployments(status, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_releases (
    id                  TEXT PRIMARY KEY,
    version             TEXT NOT NULL,
    tag_name            TEXT NOT NULL DEFAULT '',
    commit_sha          TEXT NOT NULL,
    artifact_url        TEXT NOT NULL,
    artifact_sha256     TEXT NOT NULL,
    workflow_run_id     TEXT,
    created_at          INTEGER NOT NULL,
    published_at        INTEGER,
    metadata_json       TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_releases_version ON agent_releases(version);
CREATE INDEX IF NOT EXISTS idx_releases_published ON agent_releases(published_at DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_update_jobs (
    id                  TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    deployment_id       TEXT REFERENCES agent_deployments(id),
    from_release_id     TEXT REFERENCES agent_releases(id),
    to_release_id       TEXT REFERENCES agent_releases(id),
    status              TEXT NOT NULL DEFAULT 'queued',
    requested_by        TEXT NOT NULL DEFAULT 'user',
    task_id             TEXT,
    error               TEXT,
    created_at          INTEGER NOT NULL,
    started_at          INTEGER,
    completed_at        INTEGER
);

CREATE INDEX IF NOT EXISTS idx_update_jobs_agent ON agent_update_jobs(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_update_jobs_status ON agent_update_jobs(status, created_at DESC);


"""


def _serialize_metadata(metadata: dict[str, Any] | None) -> str:
    return json.dumps(metadata or {}, ensure_ascii=True)


def _deserialize_metadata(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _merge_metadata(existing: dict[str, Any] | None, incoming: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _merge_metadata(merged.get(key), value)
        else:
            merged[key] = value
    return merged


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AgentRegistryDB:
    def __init__(self, db_path: str = AGENT_REGISTRY_DB_PATH):
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def start(self):
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(SCHEMA)
        await self._migrate_agent_deployments_schema()
        await self._ensure_column("agents", "last_deployment_id", "TEXT")
        await self._ensure_column("agent_deployments", "release_id", "TEXT")
        await self._ensure_column("agent_deployments", "task_id", "TEXT")
        await self._ensure_column("agent_deployments", "tag_name", "TEXT NOT NULL DEFAULT ''")
        await self._ensure_column("agent_deployments", "artifact_dir", "TEXT NOT NULL DEFAULT ''")
        await self._ensure_column("agent_deployments", "artifact_exe_path", "TEXT NOT NULL DEFAULT ''")
        await self._ensure_column("agent_deployments", "installer_copy_path", "TEXT NOT NULL DEFAULT ''")
        await self._ensure_column("agent_deployments", "package_zip_path", "TEXT NOT NULL DEFAULT ''")
        await self._ensure_column("agent_deployments", "metadata_json", "TEXT NOT NULL DEFAULT '{}' ")
        await self._ensure_column("agent_deployments", "build_log", "TEXT NOT NULL DEFAULT ''")
        await self._ensure_column("agent_credentials", "token_version", "INTEGER NOT NULL DEFAULT 0")
        await self._ensure_column("agent_releases", "tag_name", "TEXT NOT NULL DEFAULT ''")
        await self._db.commit()
        logger.info("AgentRegistryDB started: %s", self._db_path)

    async def _ensure_column(self, table: str, column: str, column_type: str):
        if not self._db:
            return

        async with self._db.execute(f"PRAGMA table_info({table})") as cursor:
            existing = {row[1] async for row in cursor}
        if column not in existing:
            await self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    async def _get_table_columns(self, table: str) -> set[str]:
        if not self._db:
            return set()

        async with self._db.execute(f"PRAGMA table_info({table})") as cursor:
            return {row[1] async for row in cursor}

    async def _migrate_agent_deployments_schema(self) -> None:
        if not self._db:
            return

        existing = await self._get_table_columns("agent_deployments")
        if not existing or ("repo_url" not in existing and "source_ref" not in existing):
            return

        desired_columns: tuple[tuple[str, str], ...] = (
            ("id", "id"),
            ("agent_id", "agent_id"),
            ("release_id", "release_id"),
            ("hostname", "hostname"),
            ("requested_by", "requested_by"),
            ("status", "status"),
            ("task_id", "task_id"),
            ("commit_sha", "commit_sha"),
            ("tag_name", "tag_name"),
            ("artifact_dir", "artifact_dir"),
            ("artifact_exe_path", "artifact_exe_path"),
            ("package_zip_path", "package_zip_path"),
            ("bootstrap_path", "bootstrap_path"),
            ("install_script_path", "install_script_path"),
            ("installer_copy_path", "installer_copy_path"),
            ("metadata_json", "metadata_json"),
            ("error", "error"),
            ("build_log", "build_log"),
            ("created_at", "created_at"),
            ("started_at", "started_at"),
            ("completed_at", "completed_at"),
        )
        defaults = {
            "release_id": "NULL",
            "task_id": "NULL",
            "commit_sha": "''",
            "tag_name": "''",
            "artifact_dir": "''",
            "artifact_exe_path": "''",
            "package_zip_path": "''",
            "bootstrap_path": "''",
            "install_script_path": "''",
            "installer_copy_path": "''",
            "metadata_json": "'{}'",
            "error": "NULL",
            "build_log": "''",
            "started_at": "NULL",
            "completed_at": "NULL",
        }
        select_parts = [column if column in existing else defaults.get(column, "NULL") for column, _ in desired_columns]
        insert_columns = ", ".join(column for column, _ in desired_columns)
        select_clause = ", ".join(select_parts)

        await self._db.execute("PRAGMA foreign_keys=OFF")
        await self._db.execute(
            """
            CREATE TABLE agent_deployments_new (
                id                  TEXT PRIMARY KEY,
                agent_id            TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                release_id          TEXT REFERENCES agent_releases(id),
                hostname            TEXT NOT NULL,
                requested_by        TEXT NOT NULL DEFAULT 'user',
                status              TEXT NOT NULL DEFAULT 'queued',
                task_id             TEXT,
                commit_sha          TEXT NOT NULL DEFAULT '',
                tag_name            TEXT NOT NULL DEFAULT '',
                artifact_dir        TEXT NOT NULL DEFAULT '',
                artifact_exe_path   TEXT NOT NULL DEFAULT '',
                package_zip_path    TEXT NOT NULL DEFAULT '',
                bootstrap_path      TEXT NOT NULL DEFAULT '',
                install_script_path TEXT NOT NULL DEFAULT '',
                installer_copy_path TEXT NOT NULL DEFAULT '',
                metadata_json       TEXT NOT NULL DEFAULT '{}',
                error               TEXT,
                build_log           TEXT NOT NULL DEFAULT '',
                created_at          INTEGER NOT NULL,
                started_at          INTEGER,
                completed_at        INTEGER
            )
            """
        )
        await self._db.execute(
            f"INSERT INTO agent_deployments_new ({insert_columns}) SELECT {select_clause} FROM agent_deployments"
        )
        await self._db.execute("DROP TABLE agent_deployments")
        await self._db.execute("ALTER TABLE agent_deployments_new RENAME TO agent_deployments")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_deployments_agent ON agent_deployments(agent_id, created_at DESC)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_deployments_status ON agent_deployments(status, created_at DESC)")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.commit()

    async def stop(self):
        if self._db:
            await self._db.close()
        logger.info("AgentRegistryDB stopped")

    async def upsert_agent(
        self,
        agent_id: str,
        hostname: str = "",
        display_name: str = "",
        *,
        status: str | None = None,
        connection_status: str | None = None,
        metadata: dict[str, Any] | None = None,
        last_seen_at: int | None = None,
        current_version: str | None = None,
        last_deployment_id: str | None = None,
    ):
        if not self._db:
            return

        now = int(time.time())
        existing = await self.get_agent(agent_id)

        merged_hostname = hostname or (existing.get("hostname", "") if existing else "")
        merged_display_name = display_name or (existing.get("display_name", "") if existing else "")
        merged_status = status or (existing.get("status", "registered") if existing else "registered")
        merged_connection = connection_status or (existing.get("connection_status", "offline") if existing else "offline")
        merged_version = current_version or (existing.get("current_version", "") if existing else "")
        merged_last_deployment = last_deployment_id or (existing.get("last_deployment_id") if existing else None)
        merged_last_seen = last_seen_at if last_seen_at is not None else (existing.get("last_seen_at") if existing else None)
        merged_metadata = _merge_metadata(existing.get("metadata") if existing else {}, metadata)

        await self._db.execute(
            """
            INSERT INTO agents (id, hostname, display_name, status, connection_status, current_version, last_deployment_id, metadata_json, created_at, updated_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                hostname = excluded.hostname,
                display_name = excluded.display_name,
                status = excluded.status,
                connection_status = excluded.connection_status,
                current_version = excluded.current_version,
                last_deployment_id = excluded.last_deployment_id,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at,
                last_seen_at = excluded.last_seen_at
            """,
            (
                agent_id,
                merged_hostname,
                merged_display_name,
                merged_status,
                merged_connection,
                merged_version,
                merged_last_deployment,
                _serialize_metadata(merged_metadata),
                existing.get("created_at", now) if existing else now,
                now,
                merged_last_seen,
            ),
        )
        await self._db.commit()

    async def set_bootstrap_token(self, agent_id: str, token_hash: str, expires_at: int):
        if not self._db:
            return

        now = int(time.time())
        await self._db.execute(
            """
            INSERT INTO agent_credentials (agent_id, bootstrap_token_hash, bootstrap_expires_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                bootstrap_token_hash = excluded.bootstrap_token_hash,
                bootstrap_expires_at = excluded.bootstrap_expires_at,
                bootstrap_used_at = NULL,
                updated_at = excluded.updated_at
            """,
            (agent_id, token_hash, expires_at, now),
        )
        await self._db.commit()

    async def get_agent_credentials(self, agent_id: str) -> Optional[dict[str, Any]]:
        if not self._db:
            return None
        async with self._db.execute("SELECT * FROM agent_credentials WHERE agent_id = ?", (agent_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            columns = [d[0] for d in cursor.description]
            return dict(zip(columns, row))

    async def rotate_agent_token_version(self, agent_id: str) -> Optional[dict[str, Any]]:
        if not self._db:
            return None

        agent = await self.get_agent(agent_id)
        if not agent:
            return None

        credentials = await self.get_agent_credentials(agent_id) or {}
        next_version = max(int(credentials.get("token_version") or 0), 0) + 1
        now = int(time.time())

        await self._db.execute(
            """
            INSERT INTO agent_credentials (agent_id, token_version, secret_rotated_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                secret_hash = NULL,
                token_version = excluded.token_version,
                secret_rotated_at = excluded.secret_rotated_at,
                updated_at = excluded.updated_at
            """,
            (agent_id, next_version, now, now),
        )
        await self._db.commit()
        return {"agent_id": agent_id, "token_version": next_version, "rotated_at": now}

    async def authorize_agent(self, agent_id: str, token: str | None) -> dict[str, Any]:
        credentials = await self.get_agent_credentials(agent_id)
        if not credentials:
            return {"authorized": True, "mode": "legacy", "issued_secret": None}

        bootstrap_token_hash = credentials.get("bootstrap_token_hash")
        bootstrap_expires_at = credentials.get("bootstrap_expires_at")
        bootstrap_used_at = credentials.get("bootstrap_used_at")
        secret_hash = credentials.get("secret_hash")
        secret_rotated_at = credentials.get("secret_rotated_at")
        token_version = int(credentials.get("token_version") or 0)

        if not token:
            if bootstrap_token_hash or secret_hash or token_version > 0:
                return {"authorized": False, "reason": "missing bearer token"}
            return {"authorized": True, "mode": "legacy", "issued_secret": None}

        token_hash = hash_token(token)
        now = int(time.time())

        if looks_like_jwt(token):
            if token_version <= 0:
                return {"authorized": False, "reason": "invalid bearer token"}
            try:
                verify_agent_access_token(token, agent_id, expected_version=token_version)
            except AgentJwtError:
                return {"authorized": False, "reason": "invalid bearer token"}

            if not bootstrap_used_at and self._db:
                await self._db.execute(
                    """
                    UPDATE agent_credentials
                    SET bootstrap_used_at = ?,
                        updated_at = ?
                    WHERE agent_id = ?
                    """,
                    (now, now, agent_id),
                )
                await self._db.commit()
            return {"authorized": True, "mode": "jwt", "issued_secret": None}

        if secret_hash and token_hash == secret_hash:
            if not bootstrap_used_at and self._db:
                await self._db.execute(
                    """
                    UPDATE agent_credentials
                    SET bootstrap_used_at = ?,
                        updated_at = ?
                    WHERE agent_id = ?
                    """,
                    (now, now, agent_id),
                )
                await self._db.commit()
            return {"authorized": True, "mode": "secret", "issued_secret": None}

        if (
            bootstrap_token_hash
            and token_hash == bootstrap_token_hash
            and not bootstrap_used_at
            and (bootstrap_expires_at is None or bootstrap_expires_at >= now)
        ):
            next_token_version = max(token_version, 0) + 1
            issued_secret = issue_agent_access_token(agent_id, token_version=next_token_version)
            if self._db:
                await self._db.execute(
                    """
                    UPDATE agent_credentials
                    SET secret_hash = NULL,
                        secret_rotated_at = ?,
                        token_version = ?,
                        updated_at = ?
                    WHERE agent_id = ?
                    """,
                    (now, next_token_version, now, agent_id),
                )
                await self._db.commit()
            return {"authorized": True, "mode": "bootstrap", "issued_secret": issued_secret}

        if (
            bootstrap_token_hash
            and token_hash == bootstrap_token_hash
            and bootstrap_used_at
            and token_version > 0
            and secret_rotated_at
            and now - secret_rotated_at <= BOOTSTRAP_RECOVERY_WINDOW_SECONDS
        ):
            next_token_version = token_version + 1
            issued_secret = issue_agent_access_token(agent_id, token_version=next_token_version)
            logger.warning(
                "Recovering bootstrap credentials for agent %s within %ss window",
                agent_id,
                BOOTSTRAP_RECOVERY_WINDOW_SECONDS,
            )
            if self._db:
                await self._db.execute(
                    """
                    UPDATE agent_credentials
                    SET secret_hash = NULL,
                        secret_rotated_at = ?,
                        token_version = ?,
                        updated_at = ?
                    WHERE agent_id = ?
                    """,
                    (now, next_token_version, now, agent_id),
                )
                await self._db.commit()
            return {"authorized": True, "mode": "bootstrap-recovery", "issued_secret": issued_secret}

        if bootstrap_token_hash and bootstrap_expires_at and bootstrap_expires_at < now and not bootstrap_used_at:
            return {"authorized": False, "reason": "bootstrap token expired"}

        if bootstrap_token_hash and bootstrap_used_at and token_hash == bootstrap_token_hash:
            return {"authorized": False, "reason": "bootstrap token already used"}

        return {"authorized": False, "reason": "invalid bearer token"}

    async def create_deployment(
        self,
        deployment_id: str,
        agent_id: str,
        hostname: str,
        requested_by: str,
        task_id: str,
        *,
        release_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        if not self._db:
            return

        now = int(time.time())
        await self._db.execute(
            """
            INSERT INTO agent_deployments (id, release_id, agent_id, hostname, requested_by, task_id, status, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)
            """,
            (deployment_id, release_id, agent_id, hostname, requested_by, task_id, _serialize_metadata(metadata), now),
        )
        await self._db.commit()
        await self.upsert_agent(agent_id, hostname=hostname, last_deployment_id=deployment_id)

    async def update_deployment(
        self,
        deployment_id: str,
        release_id: str | None = None,
        *,
        status: str | None = None,
        task_id: str | None = None,
        commit_sha: str | None = None,
        tag_name: str | None = None,
        artifact_dir: str | None = None,
        artifact_exe_path: str | None = None,
        package_zip_path: str | None = None,
        bootstrap_path: str | None = None,
        install_script_path: str | None = None,
        installer_copy_path: str | None = None,
        error: str | None = None,
        build_log: str | None = None,
        started_at: int | None = None,
        completed_at: int | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        if not self._db:
            return

        fields: list[str] = []
        params: list[Any] = []
        for name, value in (
            ("status", status),
            ("task_id", task_id),
            ("release_id", release_id),
            ("commit_sha", commit_sha),
            ("tag_name", tag_name),
            ("artifact_dir", artifact_dir),
            ("artifact_exe_path", artifact_exe_path),
            ("package_zip_path", package_zip_path),
            ("bootstrap_path", bootstrap_path),
            ("install_script_path", install_script_path),
            ("installer_copy_path", installer_copy_path),
            ("error", error),
            ("build_log", build_log),
            ("started_at", started_at),
            ("completed_at", completed_at),
        ):
            if value is not None:
                fields.append(f"{name} = ?")
                params.append(value)

        if metadata is not None:
            existing = await self.get_deployment(deployment_id)
            merged_metadata = _merge_metadata(existing.get("metadata") if existing else {}, metadata)
            fields.append("metadata_json = ?")
            params.append(_serialize_metadata(merged_metadata))

        if not fields:
            return

        params.append(deployment_id)
        await self._db.execute(f"UPDATE agent_deployments SET {', '.join(fields)} WHERE id = ?", params)
        await self._db.commit()

    async def upsert_release_from_source(
        self,
        *,
        version: str,
        commit_sha: str,
        artifact_url: str,
        artifact_sha256: str,
        tag_name: str = "",
        workflow_run_id: str | None = None,
        published_at: int | None = None,
        metadata: dict[str, Any] | None = None,
        release_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not self._db:
            return None

        now = int(time.time())
        existing = None
        if release_id:
            existing = await self.get_release(release_id)
        if existing is None and tag_name:
            existing = await self.get_release_by_tag(tag_name)
        if existing is None:
            existing = await self.get_release_by_version(version)

        resolved_release_id = release_id or (existing.get("id") if existing else None) or uuid.uuid4().hex
        created_at = int(existing.get("created_at") or now) if existing else now
        merged_metadata = _merge_metadata(existing.get("metadata") if existing else {}, metadata)

        await self._db.execute(
            """
            INSERT INTO agent_releases (
                id,
                version,
                tag_name,
                commit_sha,
                artifact_url,
                artifact_sha256,
                workflow_run_id,
                created_at,
                published_at,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                version = excluded.version,
                tag_name = excluded.tag_name,
                commit_sha = excluded.commit_sha,
                artifact_url = excluded.artifact_url,
                artifact_sha256 = excluded.artifact_sha256,
                workflow_run_id = excluded.workflow_run_id,
                published_at = excluded.published_at,
                metadata_json = excluded.metadata_json
            """,
            (
                resolved_release_id,
                version,
                tag_name,
                commit_sha,
                artifact_url,
                artifact_sha256,
                workflow_run_id,
                created_at,
                published_at,
                _serialize_metadata(merged_metadata),
            ),
        )
        await self._db.commit()
        return await self.get_release(resolved_release_id)

    async def get_release(self, release_id: str) -> Optional[dict[str, Any]]:
        if not self._db:
            return None
        async with self._db.execute("SELECT * FROM agent_releases WHERE id = ?", (release_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            columns = [d[0] for d in cursor.description]
            result = dict(zip(columns, row))
            result["metadata"] = _deserialize_metadata(result.pop("metadata_json", "{}"))
            return result

    async def get_release_by_version(self, version: str) -> Optional[dict[str, Any]]:
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT * FROM agent_releases WHERE version = ? ORDER BY published_at DESC, created_at DESC LIMIT 1",
            (version,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            columns = [d[0] for d in cursor.description]
            result = dict(zip(columns, row))
            result["metadata"] = _deserialize_metadata(result.pop("metadata_json", "{}"))
            return result

    async def get_release_by_tag(self, tag_name: str) -> Optional[dict[str, Any]]:
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT * FROM agent_releases WHERE tag_name = ? ORDER BY published_at DESC, created_at DESC LIMIT 1",
            (tag_name,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            columns = [d[0] for d in cursor.description]
            result = dict(zip(columns, row))
            result["metadata"] = _deserialize_metadata(result.pop("metadata_json", "{}"))
            return result

    async def get_latest_release(self) -> Optional[dict[str, Any]]:
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT * FROM agent_releases ORDER BY published_at DESC, created_at DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            columns = [d[0] for d in cursor.description]
            result = dict(zip(columns, row))
            result["metadata"] = _deserialize_metadata(result.pop("metadata_json", "{}"))
            return result

    async def get_releases(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self._db:
            return []

        rows: list[dict[str, Any]] = []
        async with self._db.execute(
            "SELECT * FROM agent_releases ORDER BY published_at DESC, created_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            columns = [d[0] for d in cursor.description]
            async for row in cursor:
                result = dict(zip(columns, row))
                result["metadata"] = _deserialize_metadata(result.pop("metadata_json", "{}"))
                rows.append(result)
        return rows

    async def create_update_job(
        self,
        *,
        agent_id: str,
        requested_by: str,
        deployment_id: str | None = None,
        from_release_id: str | None = None,
        to_release_id: str | None = None,
        task_id: str | None = None,
        status: str = "queued",
        error: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not self._db:
            return None

        now = int(time.time())
        resolved_job_id = job_id or uuid.uuid4().hex
        await self._db.execute(
            """
            INSERT INTO agent_update_jobs (
                id,
                agent_id,
                deployment_id,
                from_release_id,
                to_release_id,
                status,
                requested_by,
                task_id,
                error,
                created_at,
                started_at,
                completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            """,
            (
                resolved_job_id,
                agent_id,
                deployment_id,
                from_release_id,
                to_release_id,
                status,
                requested_by,
                task_id,
                error,
                now,
            ),
        )
        await self._db.commit()
        return await self.get_update_job(resolved_job_id)

    async def update_update_job(
        self,
        job_id: str,
        *,
        deployment_id: str | None = None,
        from_release_id: str | None = None,
        to_release_id: str | None = None,
        status: str | None = None,
        requested_by: str | None = None,
        task_id: str | None = None,
        error: str | None = None,
        started_at: int | None = None,
        completed_at: int | None = None,
    ) -> None:
        if not self._db:
            return

        fields: list[str] = []
        params: list[Any] = []
        for name, value in (
            ("deployment_id", deployment_id),
            ("from_release_id", from_release_id),
            ("to_release_id", to_release_id),
            ("status", status),
            ("requested_by", requested_by),
            ("task_id", task_id),
            ("error", error),
            ("started_at", started_at),
            ("completed_at", completed_at),
        ):
            if value is not None:
                fields.append(f"{name} = ?")
                params.append(value)

        if not fields:
            return

        params.append(job_id)
        await self._db.execute(f"UPDATE agent_update_jobs SET {', '.join(fields)} WHERE id = ?", params)
        await self._db.commit()

    async def get_update_job(self, job_id: str) -> Optional[dict[str, Any]]:
        if not self._db:
            return None
        async with self._db.execute("SELECT * FROM agent_update_jobs WHERE id = ?", (job_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            columns = [d[0] for d in cursor.description]
            return dict(zip(columns, row))

    async def get_update_jobs(self, agent_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if not self._db:
            return []

        query = "SELECT * FROM agent_update_jobs WHERE 1=1"
        params: list[Any] = []
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows: list[dict[str, Any]] = []
        async with self._db.execute(query, params) as cursor:
            columns = [d[0] for d in cursor.description]
            async for row in cursor:
                rows.append(dict(zip(columns, row)))
        return rows

    async def get_agent(self, agent_id: str) -> Optional[dict[str, Any]]:
        if not self._db:
            return None
        async with self._db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            columns = [d[0] for d in cursor.description]
            result = dict(zip(columns, row))
            result["metadata"] = _deserialize_metadata(result.pop("metadata_json", "{}"))
            return result

    async def get_agents(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self._db:
            return []
        rows: list[dict[str, Any]] = []
        async with self._db.execute("SELECT * FROM agents ORDER BY updated_at DESC LIMIT ?", (limit,)) as cursor:
            columns = [d[0] for d in cursor.description]
            async for row in cursor:
                result = dict(zip(columns, row))
                result["metadata"] = _deserialize_metadata(result.pop("metadata_json", "{}"))
                rows.append(result)
        return rows

    async def get_deployment(self, deployment_id: str) -> Optional[dict[str, Any]]:
        if not self._db:
            return None
        async with self._db.execute("SELECT * FROM agent_deployments WHERE id = ?", (deployment_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            columns = [d[0] for d in cursor.description]
            result = dict(zip(columns, row))
            result["metadata"] = _deserialize_metadata(result.pop("metadata_json", "{}"))
            return result

    async def get_deployments(self, agent_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if not self._db:
            return []
        query = "SELECT * FROM agent_deployments WHERE 1=1"
        params: list[Any] = []
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows: list[dict[str, Any]] = []
        async with self._db.execute(query, params) as cursor:
            columns = [d[0] for d in cursor.description]
            async for row in cursor:
                result = dict(zip(columns, row))
                result["metadata"] = _deserialize_metadata(result.pop("metadata_json", "{}"))
                rows.append(result)
        return rows

    async def get_active_deployment(self) -> Optional[dict[str, Any]]:
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT * FROM agent_deployments WHERE status IN ('queued', 'building', 'preparing') ORDER BY created_at ASC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            columns = [d[0] for d in cursor.description]
            result = dict(zip(columns, row))
            result["metadata"] = _deserialize_metadata(result.pop("metadata_json", "{}"))
            return result

    async def get_active_deployments(self) -> list[dict[str, Any]]:
        if not self._db:
            return []

        rows: list[dict[str, Any]] = []
        async with self._db.execute(
            "SELECT * FROM agent_deployments WHERE status IN ('queued', 'building', 'preparing') ORDER BY created_at ASC"
        ) as cursor:
            columns = [d[0] for d in cursor.description]
            async for row in cursor:
                result = dict(zip(columns, row))
                result["metadata"] = _deserialize_metadata(result.pop("metadata_json", "{}"))
                rows.append(result)
        return rows

    async def get_latest_deployment_for_agent(self, agent_id: str) -> Optional[dict[str, Any]]:
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT * FROM agent_deployments WHERE agent_id = ? ORDER BY created_at DESC LIMIT 1",
            (agent_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            columns = [d[0] for d in cursor.description]
            result = dict(zip(columns, row))
            result["metadata"] = _deserialize_metadata(result.pop("metadata_json", "{}"))
            return result

    async def get_expected_hostname_for_agent(self, agent_id: str) -> str:
        agent = await self.get_agent(agent_id)
        hostname = str((agent or {}).get("hostname") or "").strip()
        if hostname:
            return hostname

        deployment = await self.get_latest_deployment_for_agent(agent_id)
        return str((deployment or {}).get("hostname") or "").strip()
    
    async def delete_agent(self, agent_id: str):
        if not self._db:
            return
        await self._db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        await self._db.commit()
    
