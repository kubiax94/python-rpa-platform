"""
Telemetry storage — ring buffer in memory + SQLite for aggregated metrics and events.

Architecture:
  heartbeat → ring_buffer (in-memory, last 5 min)
  every 60s → aggregate ring_buffer → INSERT INTO metrics (batch)
  events (start/stop/fail/restart) → INSERT INTO events (immediate)

Retention:
  - metrics (1-min granularity): 7 days
  - metrics_hourly: 90 days
  - events: no limit (manual cleanup)
"""

import time
import asyncio
import logging
import os
from collections import defaultdict
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("VM_AGENT_TELEMETRY_DB_PATH", "telemetry.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
    ts         INTEGER NOT NULL,
    agent_id   TEXT NOT NULL,
    session_id INTEGER,
    pid        INTEGER NOT NULL,
    exe        TEXT,
    cpu_avg    REAL,
    cpu_max    REAL,
    mem_ws     INTEGER,
    mem_pb     INTEGER,
    handles    INTEGER,
    io_read_bps REAL,
    io_write_bps REAL,
    PRIMARY KEY (ts, agent_id, pid)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS metrics_hourly (
    ts         INTEGER NOT NULL,
    agent_id   TEXT NOT NULL,
    session_id INTEGER,
    pid        INTEGER NOT NULL,
    exe        TEXT,
    cpu_avg    REAL,
    cpu_max    REAL,
    mem_ws_avg INTEGER,
    mem_pb_avg INTEGER,
    handles_avg INTEGER,
    io_read_bps_avg REAL,
    io_write_bps_avg REAL,
    PRIMARY KEY (ts, agent_id, pid)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         INTEGER NOT NULL,
    agent_id   TEXT NOT NULL,
    session_id INTEGER,
    pid        INTEGER,
    type       TEXT NOT NULL,
    exe        TEXT,
    detail     TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent_id, ts);
CREATE INDEX IF NOT EXISTS idx_metrics_agent ON metrics(agent_id, ts);
CREATE INDEX IF NOT EXISTS idx_metrics_hourly_agent ON metrics_hourly(agent_id, ts);
"""

# Retention
METRICS_RETENTION_DAYS = 7
HOURLY_RETENTION_DAYS = 90


class RingBuffer:
    """Per-process ring buffer holding raw samples from heartbeats."""

    def __init__(self, max_age_sec: int = 300):
        self._max_age = max_age_sec
        # key: (agent_id, pid) → list of {ts, cpu, mem_ws, mem_pb, handles, exe, session_id}
        self._samples: dict[tuple, list[dict]] = defaultdict(list)

    def push(self, agent_id: str, session_id: int, pid: int, exe: str,
             cpu: float, mem_ws: int, mem_pb: int, handles: int,
             io_read_bps: float = 0.0, io_write_bps: float = 0.0):
        key = (agent_id, pid)
        now = int(time.time())
        self._samples[key].append({
            "ts": now,
            "cpu": cpu or 0.0,
            "mem_ws": mem_ws or 0,
            "mem_pb": mem_pb or 0,
            "handles": handles or 0,
            "io_read_bps": io_read_bps or 0.0,
            "io_write_bps": io_write_bps or 0.0,
            "exe": exe,
            "session_id": session_id,
        })

    def flush(self) -> list[dict]:
        """Aggregate per-process samples into 1-minute rows. Atomically swaps buffer."""
        now = int(time.time())
        ts_minute = (now // 60) * 60  # round down to minute

        # Atomic swap — new heartbeats go into fresh buffer, no data loss
        snapshot = self._samples
        self._samples = defaultdict(list)

        rows = []
        for (agent_id, pid), samples in snapshot.items():
            if not samples:
                continue
            cpu_vals = [s["cpu"] for s in samples]
            io_read_vals = [s["io_read_bps"] for s in samples]
            io_write_vals = [s["io_write_bps"] for s in samples]
            rows.append({
                "ts": ts_minute,
                "agent_id": agent_id,
                "session_id": samples[-1]["session_id"],
                "pid": pid,
                "exe": samples[-1]["exe"],
                "cpu_avg": sum(cpu_vals) / len(cpu_vals) if cpu_vals else 0,
                "cpu_max": max(cpu_vals) if cpu_vals else 0,
                "mem_ws": samples[-1]["mem_ws"],
                "mem_pb": samples[-1]["mem_pb"],
                "handles": samples[-1]["handles"],
                "io_read_bps": sum(io_read_vals) / len(io_read_vals) if io_read_vals else 0,
                "io_write_bps": sum(io_write_vals) / len(io_write_vals) if io_write_vals else 0,
            })

        return rows

    def clear(self):
        """Clear the buffer (no longer needed with atomic swap, kept for compat)."""
        self._samples = defaultdict(list)

    def evict_old(self):
        """Remove samples older than max_age."""
        cutoff = int(time.time()) - self._max_age
        for key in list(self._samples.keys()):
            self._samples[key] = [s for s in self._samples[key] if s["ts"] >= cutoff]
            if not self._samples[key]:
                del self._samples[key]


class TelemetryDB:
    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None
        self._ring = RingBuffer()
        self._flush_task: Optional[asyncio.Task] = None

    async def start(self):
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(SCHEMA)
        await self._ensure_column("metrics", "io_read_bps", "REAL")
        await self._ensure_column("metrics", "io_write_bps", "REAL")
        await self._ensure_column("metrics_hourly", "io_read_bps_avg", "REAL")
        await self._ensure_column("metrics_hourly", "io_write_bps_avg", "REAL")
        await self._db.commit()
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info(f"TelemetryDB started: {self._db_path}")

    async def _ensure_column(self, table: str, column: str, column_type: str):
        if not self._db:
            return

        async with self._db.execute(f"PRAGMA table_info({table})") as cursor:
            existing = {row[1] async for row in cursor}
        if column not in existing:
            await self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    async def stop(self):
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        # Final flush
        await self._flush_to_db()
        if self._db:
            await self._db.close()
        logger.info("TelemetryDB stopped")

    # --- Ingest from heartbeat ---

    def ingest_heartbeat(self, agent_id: str, agent_status: dict):
        """Called from merge_heartbeat. Pushes raw samples into ring buffer."""
        for session_key, session_data in agent_status.items():
            if session_key.startswith("__"):
                continue
            if not isinstance(session_data, dict):
                continue
            session_id = session_data.get("session_id", 0)
            processes = session_data.get("processes", {})
            for pid_str, pdata in processes.items():
                if not isinstance(pdata, dict):
                    continue
                mem = pdata.get("memory_usage", {})
                io = pdata.get("io_counters", {})
                self._ring.push(
                    agent_id=agent_id,
                    session_id=session_id,
                    pid=int(pid_str),
                    exe=pdata.get("exe", "unknown"),
                    cpu=pdata.get("cpu_usage", 0.0),
                    mem_ws=mem.get("working_set_size", 0) if isinstance(mem, dict) else 0,
                    mem_pb=mem.get("private_bytes", 0) if isinstance(mem, dict) else 0,
                    handles=pdata.get("handle_count", 0),
                    io_read_bps=io.get("read_bps", 0.0) if isinstance(io, dict) else 0.0,
                    io_write_bps=io.get("write_bps", 0.0) if isinstance(io, dict) else 0.0,
                )

    # --- Events ---

    async def record_event(self, agent_id: str, event_type: str,
                           session_id: int = None, pid: int = None,
                           exe: str = None, detail: str = None):
        if not self._db:
            return
        await self._db.execute(
            "INSERT INTO events (ts, agent_id, session_id, pid, type, exe, detail) VALUES (?,?,?,?,?,?,?)",
            (int(time.time()), agent_id, session_id, pid, event_type, exe, detail)
        )
        await self._db.commit()

    # --- Flush loop ---

    async def _flush_loop(self):
        """Every 60s: flush ring buffer → metrics table, cleanup old data."""
        while True:
            await asyncio.sleep(60)
            try:
                await self._flush_to_db()
                await self._cleanup_old()
            except Exception as e:
                logger.error(f"Flush error: {e}")

    async def _flush_to_db(self):
        rows = self._ring.flush()
        if not rows or not self._db:
            return

        await self._db.executemany(
            """INSERT OR REPLACE INTO metrics 
               (ts, agent_id, session_id, pid, exe, cpu_avg, cpu_max, mem_ws, mem_pb, handles, io_read_bps, io_write_bps)
               VALUES (:ts, :agent_id, :session_id, :pid, :exe, :cpu_avg, :cpu_max, :mem_ws, :mem_pb, :handles, :io_read_bps, :io_write_bps)""",
            rows
        )
        await self._db.commit()
        logger.debug(f"Flushed {len(rows)} metric rows")

    async def _cleanup_old(self):
        now = int(time.time())
        # Aggregate minute → hourly for data older than 24h
        cutoff_hourly = now - 86400  # 24h ago
        await self._db.execute("""
             INSERT OR REPLACE INTO metrics_hourly (ts, agent_id, session_id, pid, exe, cpu_avg, cpu_max, mem_ws_avg, mem_pb_avg, handles_avg, io_read_bps_avg, io_write_bps_avg)
            SELECT (ts / 3600) * 3600, agent_id, session_id, pid, exe,
                 AVG(cpu_avg), MAX(cpu_max), AVG(mem_ws), AVG(mem_pb), AVG(handles), AVG(io_read_bps), AVG(io_write_bps)
            FROM metrics
            WHERE ts < ?
            GROUP BY (ts / 3600) * 3600, agent_id, pid
        """, (cutoff_hourly,))

        # Delete minute-level older than retention
        cutoff_min = now - (METRICS_RETENTION_DAYS * 86400)
        await self._db.execute("DELETE FROM metrics WHERE ts < ?", (cutoff_min,))

        # Delete hourly older than retention
        cutoff_hr = now - (HOURLY_RETENTION_DAYS * 86400)
        await self._db.execute("DELETE FROM metrics_hourly WHERE ts < ?", (cutoff_hr,))

        await self._db.commit()

    # --- Query API ---

    async def get_metrics(self, agent_id: str, pid: int = None,
                          from_ts: int = None, to_ts: int = None,
                          limit: int = 1000) -> list[dict]:
        """Get metrics for an agent (optionally filtered by pid and time range)."""
        if not self._db:
            return []

        now = int(time.time())
        from_ts = from_ts or (now - 3600)  # default: last hour
        to_ts = to_ts or now

        # If range > 24h, use hourly table
        use_hourly = (to_ts - from_ts) > 86400
        table = "metrics_hourly" if use_hourly else "metrics"

        if use_hourly:
            query = f"SELECT ts, agent_id, session_id, pid, exe, cpu_avg, cpu_max, mem_ws_avg as mem_ws, mem_pb_avg as mem_pb, handles_avg as handles, io_read_bps_avg as io_read_bps, io_write_bps_avg as io_write_bps FROM {table} WHERE agent_id = ? AND ts >= ? AND ts <= ?"
        else:
            query = f"SELECT ts, agent_id, session_id, pid, exe, cpu_avg, cpu_max, mem_ws, mem_pb, handles, io_read_bps, io_write_bps FROM {table} WHERE agent_id = ? AND ts >= ? AND ts <= ?"
        params = [agent_id, from_ts, to_ts]

        if pid:
            query += " AND pid = ?"
            params.append(pid)

        query += " ORDER BY ts ASC LIMIT ?"
        params.append(limit)

        rows = []
        async with self._db.execute(query, params) as cursor:
            cols = [d[0] for d in cursor.description] if cursor.description else []
            async for row in cursor:
                rows.append(dict(zip(cols, row)))
        return rows

    async def get_events(self, agent_id: str = None, event_type: str = None,
                         from_ts: int = None, to_ts: int = None,
                         limit: int = 200) -> list[dict]:
        """Get events, optionally filtered."""
        if not self._db:
            return []

        now = int(time.time())
        conditions = []
        params = []

        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        if event_type:
            conditions.append("type = ?")
            params.append(event_type)
        if from_ts:
            conditions.append("ts >= ?")
            params.append(from_ts)
        if to_ts:
            conditions.append("ts <= ?")
            params.append(to_ts)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"SELECT id, ts, agent_id, session_id, pid, type, exe, detail FROM events{where} ORDER BY ts DESC LIMIT ?"
        params.append(limit)

        rows = []
        async with self._db.execute(query, params) as cursor:
            cols = [d[0] for d in cursor.description] if cursor.description else []
            async for row in cursor:
                rows.append(dict(zip(cols, row)))
        return rows

    async def get_agents_summary(self) -> list[dict]:
        """Get latest metrics per agent (last 5 minutes)."""
        if not self._db:
            return []
        cutoff = int(time.time()) - 300
        rows = []
        async with self._db.execute("""
            SELECT agent_id, COUNT(DISTINCT pid) as process_count,
                   AVG(cpu_avg) as avg_cpu, SUM(mem_ws) as total_mem_ws,
                   MAX(ts) as last_seen
            FROM metrics WHERE ts >= ?
            GROUP BY agent_id
        """, (cutoff,)) as cursor:
            cols = [d[0] for d in cursor.description] if cursor.description else []
            async for row in cursor:
                rows.append(dict(zip(cols, row)))
        return rows
