import asyncio
import copy
import time
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket

from shared.network.events.example_event import HeartbeatData

if TYPE_CHECKING:
    from vm_agent_server.src.persistence.telemetry_db import TelemetryDB

HEARTBEAT_TIMEOUT_SECONDS = 15


class AgentRuntime:
    def __init__(self):
        self.latest_stats: dict[str, dict[str, Any]] = {}
        self.active_agents: dict[str, WebSocket] = {}
        self._prev_process_states: dict[str, dict[str, dict[str, Any]]] = {}

    def mark_agent_connection_state(self, agent_id: str, connected: bool):
        agent_state = self.latest_stats.setdefault(agent_id, {})
        agent_state["__agent_connection"] = {
            "connected": connected,
            "last_seen": int(time.time()),
        }

    async def register_agent(self, agent_id: str, ws: WebSocket):
        previous = self.active_agents.get(agent_id)
        self.active_agents[agent_id] = ws
        self.mark_agent_connection_state(agent_id, True)
        if previous is not None and previous is not ws:
            try:
                await previous.close()
            except Exception:
                pass

    async def unregister_agent(self, agent_id: str | None, ws: WebSocket | None = None) -> bool:
        if not agent_id:
            return False

        current = self.active_agents.get(agent_id)
        if ws is not None and current is not None and current is not ws:
            return False

        if current is not None:
            self.active_agents.pop(agent_id, None)

        self.reset_agent_runtime_state(agent_id)
        return True

    async def timeout_agent(self, agent_id: str) -> bool:
        current = self.active_agents.pop(agent_id, None)
        if current is None:
            return False

        try:
            await current.close()
        except Exception:
            pass

        self.reset_agent_runtime_state(agent_id)
        return True

    async def close_all_connections(self) -> int:
        closed_count = 0
        for agent_id, socket in list(self.active_agents.items()):
            self.active_agents.pop(agent_id, None)
            try:
                await socket.close(code=1001, reason="Server shutdown")
            except Exception:
                pass
            self.reset_agent_runtime_state(agent_id)
            closed_count += 1
        return closed_count

    def get_agent_socket(self, agent_id: str) -> WebSocket | None:
        return self.active_agents.get(agent_id)

    def active_agent_count(self) -> int:
        return len(self.active_agents)

    def get_default_target_agent_id(self) -> str | None:
        if len(self.active_agents) == 1:
            return next(iter(self.active_agents))
        return None

    def build_frontend_snapshot(self) -> dict[str, dict[str, Any]]:
        snapshot: dict[str, dict[str, Any]] = {}
        for agent_id, agent_state in self.latest_stats.items():
            summary: dict[str, Any] = {}

            if "__agent_metrics" in agent_state:
                summary["__agent_metrics"] = copy.deepcopy(agent_state["__agent_metrics"])
            if "__agent_connection" in agent_state:
                summary["__agent_connection"] = copy.deepcopy(agent_state["__agent_connection"])

            for session_key, session_data in agent_state.items():
                if session_key.startswith("__") or not isinstance(session_data, dict):
                    continue

                processes = session_data.get("processes", {})
                session_summary = {
                    key: copy.deepcopy(value)
                    for key, value in session_data.items()
                    if key != "processes"
                }
                session_summary["process_count"] = len(processes) if isinstance(processes, dict) else 0
                session_summary["processes"] = {}
                summary[session_key] = session_summary

            snapshot[agent_id] = summary

        return snapshot

    def get_agent_state(self, agent_id: str) -> dict[str, Any] | None:
        agent_state = self.latest_stats.get(agent_id)
        if agent_state is None:
            return None
        return copy.deepcopy(agent_state)

    def get_timed_out_agents(self, timeout_seconds: int = HEARTBEAT_TIMEOUT_SECONDS) -> list[str]:
        cutoff = int(time.time()) - timeout_seconds
        timed_out: list[str] = []
        for agent_id, agent_state in self.latest_stats.items():
            connection = agent_state.get("__agent_connection")
            if not isinstance(connection, dict):
                continue
            if connection.get("connected") is not True:
                continue
            if int(connection.get("last_seen", 0)) <= cutoff:
                timed_out.append(agent_id)
        return timed_out

    def reset_agent_runtime_state(self, agent_id: str):
        agent_state = self.latest_stats.get(agent_id)
        if agent_state is None:
            self._prev_process_states.pop(agent_id, None)
            return

        preserved_metrics = agent_state.get("__agent_metrics")
        preserved_connection = copy.deepcopy(agent_state.get("__agent_connection"))
        if preserved_connection is not None:
            preserved_connection["connected"] = False
            preserved_connection["last_seen"] = int(time.time())

        self.latest_stats[agent_id] = {
            "__agent_metrics": preserved_metrics,
            "__agent_connection": preserved_connection,
        } if preserved_metrics is not None or preserved_connection is not None else {}
        self._prev_process_states.pop(agent_id, None)

    def remove_agent(self, agent_id: str) -> None:
        self.active_agents.pop(agent_id, None)
        self.latest_stats.pop(agent_id, None)
        self._prev_process_states.pop(agent_id, None)

    def merge_heartbeat(self, payload: HeartbeatData, telemetry_db: "TelemetryDB"):
        agent_id = payload.client_id or "unknown_agent"
        agent_status = payload.agent_status or {}
        is_sync = payload.sync

        self.mark_agent_connection_state(agent_id, True)
        agent_state = self.latest_stats.setdefault(agent_id, {})

        if payload.system_metrics is not None:
            agent_state["__agent_metrics"] = payload.system_metrics

        if is_sync:
            incoming_session_keys = {
                session_key for session_key, session_data in agent_status.items()
                if isinstance(session_data, dict)
            }
            stale_session_keys = [
                session_key for session_key in agent_state.keys()
                if not session_key.startswith("__") and session_key not in incoming_session_keys
            ]
            for session_key in stale_session_keys:
                del agent_state[session_key]

        for session_key, session_data in agent_status.items():
            if not isinstance(session_data, dict):
                continue

            target = agent_state.setdefault(session_key, {})
            for key, value in session_data.items():
                if key != "processes":
                    target[key] = value

            incoming_procs = session_data.get("processes", {})
            if is_sync:
                target["processes"] = {
                    str(pid): proc_info for pid, proc_info in incoming_procs.items()
                }
            else:
                current_procs = target.setdefault("processes", {})
                for pid, proc_info in incoming_procs.items():
                    pid_str = str(pid)
                    if isinstance(proc_info, dict) and proc_info.get("is_running") is False:
                        current_procs.pop(pid_str, None)
                        continue
                    if pid_str not in current_procs:
                        current_procs[pid_str] = proc_info
                    else:
                        current_procs[pid_str].update(proc_info)

        telemetry_db.ingest_heartbeat(agent_id, agent_state)
        self._detect_events(agent_id, agent_state, telemetry_db)

    def _detect_events(self, agent_id: str, merged_state: dict[str, Any], telemetry_db: "TelemetryDB"):
        if agent_id not in self._prev_process_states:
            self._prev_process_states[agent_id] = {}
        prev = self._prev_process_states[agent_id]
        current: dict[str, dict[str, Any]] = {}

        for session_key, session_data in merged_state.items():
            if not isinstance(session_data, dict) or session_key.startswith("__"):
                continue
            session_id = session_data.get("session_id", 0)
            for pid_str, pdata in session_data.get("processes", {}).items():
                if not isinstance(pdata, dict):
                    continue
                is_running = pdata.get("is_running", False)
                exe = pdata.get("exe", "unknown")
                current[pid_str] = {"running": is_running, "exe": exe, "session_id": session_id}

                was = prev.get(pid_str)
                if was is None and is_running:
                    asyncio.create_task(telemetry_db.record_event(
                        agent_id, "start", session_id, int(pid_str), exe
                    ))
                elif was is not None and was["running"] and not is_running:
                    exit_code = pdata.get("exit_code", -1)
                    event_type = "stop" if exit_code == 0 else "fail"
                    asyncio.create_task(telemetry_db.record_event(
                        agent_id, event_type, session_id, int(pid_str), exe,
                        detail=f"exit_code={exit_code}"
                    ))

        for pid_str, was in prev.items():
            if pid_str not in current and was["running"]:
                asyncio.create_task(telemetry_db.record_event(
                    agent_id, "disappeared", was.get("session_id"), int(pid_str), was.get("exe")
                ))

        self._prev_process_states[agent_id] = current
