"""
Task & Pipeline storage — SQLite for task metadata + audit trail, disk for logs.

ITGC compliance:
  - Full audit trail: who requested, when, what script, from where
  - Immutable log files on disk (append-only)
  - Task status transitions recorded with timestamps
  - Pipeline step ordering preserved

Storage:
  - tasks table: metadata, status, ITGC fields
  - pipelines table: pipeline definitions (templates)
  - pipeline_runs table: execution instances of pipelines
  - audit_log table: every state transition with actor + timestamp
  - Disk: logs/tasks/{task_id}.log (raw stdout/stderr)
"""

import os
import time
import asyncio
import logging
import json
from pathlib import Path
from typing import Optional

import aiosqlite

from vm_agent_server.src.task_models import TASK_KIND_AGENT, TaskComponent, TaskSpec

logger = logging.getLogger(__name__)

TASK_DB_PATH = "tasks.db"
TASK_LOGS_DIR = "logs/tasks"

TASK_SCHEMA = """
-- Task definitions / runs
CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    pipeline_run_id TEXT,                -- NULL = standalone task
    step_index      INTEGER DEFAULT 0,
    agent_id        TEXT NOT NULL,
    session         TEXT DEFAULT '',     -- target user session
    name            TEXT DEFAULT '',
    script          TEXT NOT NULL,
    cwd             TEXT DEFAULT '',
    timeout_sec     INTEGER DEFAULT 300,
    config_id       TEXT,                -- FK to future task_configs table
    status          TEXT NOT NULL DEFAULT 'queued',  -- queued/running/completed/failed/cancelled/timeout
    pid             INTEGER,
    exit_code       INTEGER,
    error           TEXT,
    -- ITGC fields
    requested_by    TEXT DEFAULT 'system',   -- who initiated (user/system/pipeline)
    requested_from  TEXT DEFAULT '',         -- IP or source identifier
    created_at      INTEGER NOT NULL,
    started_at      INTEGER,
    completed_at    INTEGER,
    kind            TEXT NOT NULL DEFAULT 'agent',
    payload_json    TEXT NOT NULL DEFAULT '{}',
    components_json TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(agent_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_pipeline_run ON tasks(pipeline_run_id, step_index);

-- Pipeline templates (reusable definitions)
CREATE TABLE IF NOT EXISTS pipelines (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_by  TEXT DEFAULT 'system',
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);

-- Pipeline steps (ordered list of task templates within a pipeline)
CREATE TABLE IF NOT EXISTS pipeline_steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_id TEXT NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    step_index  INTEGER NOT NULL,
    name        TEXT DEFAULT '',
    script      TEXT NOT NULL,
    cwd         TEXT DEFAULT '',
    timeout_sec INTEGER DEFAULT 300,
    on_fail     TEXT DEFAULT 'stop',    -- stop / continue / retry
    retry_count INTEGER DEFAULT 0,
    UNIQUE(pipeline_id, step_index)
);

-- Pipeline execution runs
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          TEXT PRIMARY KEY,
    pipeline_id TEXT NOT NULL REFERENCES pipelines(id),
    agent_id    TEXT NOT NULL,
    session     TEXT DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'queued',  -- queued/running/completed/failed/cancelled
    current_step INTEGER DEFAULT 0,
    requested_by TEXT DEFAULT 'system',
    requested_from TEXT DEFAULT '',
    created_at  INTEGER NOT NULL,
    started_at  INTEGER,
    completed_at INTEGER
);

-- ITGC audit log — immutable record of every action
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    entity_type TEXT NOT NULL,       -- task / pipeline / pipeline_run
    entity_id   TEXT NOT NULL,
    action      TEXT NOT NULL,       -- created / started / completed / failed / cancelled / output
    actor       TEXT DEFAULT 'system',
    detail      TEXT,
    ip_address  TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);

-- Future: task config templates
CREATE TABLE IF NOT EXISTS task_configs (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    script      TEXT NOT NULL,
    cwd         TEXT DEFAULT '',
    timeout_sec INTEGER DEFAULT 300,
    env_json    TEXT DEFAULT '{}',
    created_by  TEXT DEFAULT 'system',
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);
"""


class TaskDB:
    def __init__(self, db_path: str = TASK_DB_PATH, logs_dir: str = TASK_LOGS_DIR):
        self._db_path = db_path
        self._logs_dir = Path(logs_dir)
        self._db: Optional[aiosqlite.Connection] = None

    async def start(self):
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(TASK_SCHEMA)
        await self._ensure_column("tasks", "pid", "INTEGER")
        await self._ensure_column("tasks", "kind", "TEXT NOT NULL DEFAULT 'agent'")
        await self._ensure_column("tasks", "payload_json", "TEXT NOT NULL DEFAULT '{}'")
        await self._ensure_column("tasks", "components_json", "TEXT NOT NULL DEFAULT '[]'")
        await self._db.commit()
        logger.info(f"TaskDB started: {self._db_path}, logs: {self._logs_dir}")

    async def _ensure_column(self, table: str, column: str, column_type: str):
        if not self._db:
            return

        async with self._db.execute(f"PRAGMA table_info({table})") as cursor:
            existing = {row[1] async for row in cursor}
        if column not in existing:
            await self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    async def stop(self):
        if self._db:
            await self._db.close()
        logger.info("TaskDB stopped")

    # ── Task CRUD ──────────────────────────────────────────────────

    async def create_task(self, task: TaskSpec) -> dict:
        now = int(time.time())
        await self._db.execute(
            """INSERT INTO tasks 
               (id, pipeline_run_id, step_index, agent_id, session, name, script, cwd,
                timeout_sec, status, requested_by, requested_from, created_at, kind,
                payload_json, components_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task.id,
                task.pipeline_run_id,
                task.step_index,
                task.agent_id,
                task.session,
                task.name,
                task.script,
                task.cwd,
                task.timeout_sec,
                "queued",
                task.requested_by,
                task.requested_from,
                now,
                task.kind,
                json.dumps(task.payload),
                json.dumps([component.to_dict() for component in task.components]),
            )
        )
        await self._db.commit()

        await self._audit(
            "task",
            task.id,
            "created",
            task.requested_by,
            f"kind={task.kind}, script_len={len(task.script)}, agent={task.agent_id}",
            task.requested_from,
        )

        return task.to_api_dict(status="queued", created_at=now)

    async def update_task_status(self, task_id: str, status: str,
                                  pid: int = None, exit_code: int = None, error: str = None,
                                  actor: str = "agent"):
        now = int(time.time())
        fields = ["status = ?"]
        params = [status]

        if status == "running":
            fields.append("started_at = ?")
            params.append(now)
        elif status in ("completed", "failed", "cancelled", "timeout"):
            fields.append("completed_at = ?")
            params.append(now)

        if pid is not None:
            fields.append("pid = ?")
            params.append(pid)
        if exit_code is not None:
            fields.append("exit_code = ?")
            params.append(exit_code)
        if error is not None:
            fields.append("error = ?")
            params.append(error)

        params.append(task_id)
        await self._db.execute(
            f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", params
        )
        await self._db.commit()

        detail_parts = []
        if pid is not None:
            detail_parts.append(f"pid={pid}")
        if exit_code is not None:
            detail_parts.append(f"exit_code={exit_code}")
        detail = " ".join(detail_parts)
        if error:
            detail += f" error={error[:200]}"
        await self._audit("task", task_id, status, actor, detail)

    async def get_task(self, task_id: str) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return self._map_task_row(cursor.description, row)

    async def get_tasks(self, agent_id: str = None, status: str = None,
                        limit: int = 50) -> list[dict]:
        query = "SELECT * FROM tasks WHERE 1=1"
        params = []
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = []
        async with self._db.execute(query, params) as cursor:
            async for row in cursor:
                rows.append(self._map_task_row(cursor.description, row))
        return rows

    # ── Pipeline CRUD ──────────────────────────────────────────────

    async def create_pipeline(self, pipeline_id: str, name: str,
                               steps: list[dict], description: str = "",
                               created_by: str = "system") -> dict:
        now = int(time.time())
        await self._db.execute(
            "INSERT INTO pipelines (id, name, description, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (pipeline_id, name, description, created_by, now, now)
        )
        for step in steps:
            await self._db.execute(
                """INSERT INTO pipeline_steps 
                   (pipeline_id, step_index, name, script, cwd, timeout_sec, on_fail, retry_count)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (pipeline_id, step.get("step_index", 0), step.get("name", ""),
                 step["script"], step.get("cwd", ""), step.get("timeout_sec", 300),
                 step.get("on_fail", "stop"), step.get("retry_count", 0))
            )
        await self._db.commit()
        await self._audit("pipeline", pipeline_id, "created", created_by, f"name={name}, steps={len(steps)}")
        return {"id": pipeline_id, "name": name, "steps": len(steps)}

    async def get_pipeline(self, pipeline_id: str) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM pipelines WHERE id = ?", (pipeline_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cursor.description]
            pipeline = dict(zip(cols, row))

        steps = []
        async with self._db.execute(
            "SELECT * FROM pipeline_steps WHERE pipeline_id = ? ORDER BY step_index",
            (pipeline_id,)
        ) as cursor:
            cols = [d[0] for d in cursor.description]
            async for row in cursor:
                steps.append(dict(zip(cols, row)))
        pipeline["steps"] = steps
        return pipeline

    async def get_pipelines(self, limit: int = 50) -> list[dict]:
        rows = []
        async with self._db.execute(
            "SELECT * FROM pipelines ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cursor:
            cols = [d[0] for d in cursor.description]
            async for row in cursor:
                rows.append(dict(zip(cols, row)))
        return rows

    # ── Pipeline Run ───────────────────────────────────────────────

    async def create_pipeline_run(self, run_id: str, pipeline_id: str,
                                   agent_id: str, session: str = "",
                                   requested_by: str = "system",
                                   requested_from: str = "") -> dict:
        now = int(time.time())
        await self._db.execute(
            """INSERT INTO pipeline_runs 
               (id, pipeline_id, agent_id, session, status, requested_by, requested_from, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (run_id, pipeline_id, agent_id, session, "queued", requested_by, requested_from, now)
        )
        await self._db.commit()
        await self._audit("pipeline_run", run_id, "created", requested_by,
                          f"pipeline={pipeline_id}, agent={agent_id}", requested_from)
        return {"id": run_id, "status": "queued"}

    async def update_pipeline_run_status(self, run_id: str, status: str,
                                          current_step: int = None,
                                          actor: str = "system"):
        now = int(time.time())
        fields = ["status = ?"]
        params = [status]

        if status == "running":
            fields.append("started_at = ?")
            params.append(now)
        elif status in ("completed", "failed", "cancelled"):
            fields.append("completed_at = ?")
            params.append(now)

        if current_step is not None:
            fields.append("current_step = ?")
            params.append(current_step)

        params.append(run_id)
        await self._db.execute(
            f"UPDATE pipeline_runs SET {', '.join(fields)} WHERE id = ?", params
        )
        await self._db.commit()
        await self._audit("pipeline_run", run_id, status, actor,
                          f"step={current_step}" if current_step is not None else "")

    async def get_pipeline_run(self, run_id: str) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cursor.description]
            run = dict(zip(cols, row))

        # Attach tasks for this run
        tasks = []
        async with self._db.execute(
            "SELECT * FROM tasks WHERE pipeline_run_id = ? ORDER BY step_index",
            (run_id,)
        ) as cursor:
            async for row in cursor:
                tasks.append(self._map_task_row(cursor.description, row))
        run["tasks"] = tasks
        return run

    def _map_task_row(self, description, row) -> dict:
        cols = [d[0] for d in description]
        task = dict(zip(cols, row))
        task["kind"] = task.get("kind") or TASK_KIND_AGENT
        task["payload"] = self._decode_json(task.pop("payload_json", "{}"), default={})
        raw_components = self._decode_json(task.pop("components_json", "[]"), default=[])
        task["components"] = self._normalize_components(raw_components)
        return task

    @staticmethod
    def _decode_json(raw: object, *, default):
        if raw in (None, ""):
            return default
        if not isinstance(raw, str):
            return raw
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to decode task JSON payload")
            return default

    @staticmethod
    def _normalize_components(raw_components: object) -> list[dict]:
        if not isinstance(raw_components, list):
            return []

        components: list[dict] = []
        for raw_component in raw_components:
            try:
                components.append(TaskComponent.from_dict(raw_component).to_dict())
            except (TypeError, ValueError):
                continue
        return components

    # ── Disk log management ────────────────────────────────────────

    def get_log_path(self, task_id: str) -> Path:
        return self._logs_dir / f"{task_id}.log"

    def append_log(self, task_id: str, stream: str, data: str, seq: int):
        """Append output to disk log file (synchronous, called from event handler)."""
        log_path = self.get_log_path(task_id)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(data)
            if not data.endswith("\n"):
                f.write("\n")

    def read_log(self, task_id: str, offset: int = 0, limit: int = 0) -> dict:
        """Read log from disk. offset=byte offset, limit=max bytes (0=all)."""
        log_path = self.get_log_path(task_id)
        if not log_path.exists():
            return {"content": "", "offset": 0, "size": 0}

        size = log_path.stat().st_size
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            if offset > 0:
                f.seek(offset)
            content = f.read(limit) if limit > 0 else f.read()

        return {"content": content, "offset": offset, "size": size}

    # ── Audit log ──────────────────────────────────────────────────

    async def _audit(self, entity_type: str, entity_id: str, action: str,
                     actor: str = "system", detail: str = "", ip: str = ""):
        await self._db.execute(
            "INSERT INTO audit_log (ts, entity_type, entity_id, action, actor, detail, ip_address) VALUES (?,?,?,?,?,?,?)",
            (int(time.time()), entity_type, entity_id, action, actor, detail, ip)
        )
        # commit piggybacks on caller's commit

    async def get_audit_log(self, entity_type: str = None, entity_id: str = None,
                            limit: int = 100) -> list[dict]:
        query = "SELECT * FROM audit_log WHERE 1=1"
        params = []
        if entity_type:
            query += " AND entity_type = ?"
            params.append(entity_type)
        if entity_id:
            query += " AND entity_id = ?"
            params.append(entity_id)
        query += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)

        rows = []
        async with self._db.execute(query, params) as cursor:
            cols = [d[0] for d in cursor.description]
            async for row in cursor:
                rows.append(dict(zip(cols, row)))
        return rows
