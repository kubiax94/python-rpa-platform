import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
import uvicorn

from shared.network.events.example_event import CaptureProcessScreenshotEvent, CreateSessionEvent, ExecuteTaskEvent, ExecuteTaskData, CancelTaskEvent, CancelTaskData, HeartbeatData, SetWindowTrackingData, SetWindowTrackingEvent, StartMonitoredProcessEvent, StartProgramEvent
from vm_agent_server.src.agent_registry_db import AgentRegistryDB
from vm_agent_server.src.deployment_service import DeploymentService
from vm_agent_server.src.network_event_handler import NetworkEventHandler
from vm_agent_server.src.add_trust_rdp_host import add_trusted_rdp_host, disable_rdp_publisher_warning
from vm_agent_server.src.agent_runtime import AgentRuntime, HEARTBEAT_TIMEOUT_SECONDS
from vm_agent_server.src.guacamole_bridge import build_guacamole_session, get_guacamole_config
from vm_agent_server.src.telemetry_db import TelemetryDB
from vm_agent_server.src.task_db import TaskDB

telemetry_db = TelemetryDB()
task_db = TaskDB()
registry_db = AgentRegistryDB()
agent_runtime = AgentRuntime()
frontend_snapshot_event = asyncio.Event()
frontend_snapshot_broadcast_task: asyncio.Task | None = None
heartbeat_watchdog_task: asyncio.Task | None = None
logger = logging.getLogger(__name__)
repo_root = Path(__file__).resolve().parents[2]
deployment_service = DeploymentService(registry_db, repo_root)


async def _frontend_snapshot_broadcaster():
    while True:
        await frontend_snapshot_event.wait()
        await asyncio.sleep(0.15)
        frontend_snapshot_event.clear()
        if frontend_clients:
            await broadcast_to_frontends(agent_runtime.build_frontend_snapshot())


async def _heartbeat_watchdog():
    while True:
        await asyncio.sleep(max(1, HEARTBEAT_TIMEOUT_SECONDS // 3))
        timed_out_agents = agent_runtime.get_timed_out_agents()
        if not timed_out_agents:
            continue

        snapshot_changed = False
        for agent_id in timed_out_agents:
            logger.warning("Agent heartbeat timed out: %s", agent_id)
            if await agent_runtime.timeout_agent(agent_id):
                snapshot_changed = True

        if snapshot_changed:
            frontend_snapshot_event.set()

@asynccontextmanager
async def lifespan(app):
    global frontend_snapshot_broadcast_task, heartbeat_watchdog_task
    await telemetry_db.start()
    await task_db.start()
    await registry_db.start()
    frontend_snapshot_broadcast_task = asyncio.create_task(_frontend_snapshot_broadcaster())
    heartbeat_watchdog_task = asyncio.create_task(_heartbeat_watchdog())
    yield
    if heartbeat_watchdog_task:
        heartbeat_watchdog_task.cancel()
        try:
            await heartbeat_watchdog_task
        except asyncio.CancelledError:
            pass
    if frontend_snapshot_broadcast_task:
        frontend_snapshot_broadcast_task.cancel()
        try:
            await frontend_snapshot_broadcast_task
        except asyncio.CancelledError:
            pass
    await task_db.stop()
    await telemetry_db.stop()
    await registry_db.stop()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
frontend_clients = set()
process_manager_watchers: dict[str, set[WebSocket]] = {}
frontend_watched_agents: dict[WebSocket, set[str]] = {}

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()    
    await ws.send_text('{"type":"handshake","data":{"client_id":"server","capabilities":["ws"]}}')

    client_id = None
    try:
        while True:
            msg = await ws.receive_text()
            try:
                eh = NetworkEventHandler(None)
                ev = eh.parser(msg)

                match(ev.type):
                    case "handshake":
                        client_id = ev.data.client_id
                        logger.info("Handshake received from agent %s", client_id)
                        await agent_runtime.register_agent(client_id, ws)
                        await registry_db.upsert_agent(
                            client_id,
                            status="registered",
                            connection_status="online",
                            last_seen_at=int(time.time()),
                        )
                        if process_manager_watchers.get(client_id):
                            await _set_agent_window_tracking(client_id, True)
                        frontend_snapshot_event.set()
                    case "heartbeat":
                        agent_runtime.merge_heartbeat(ev.data, telemetry_db)
                        metrics = ev.data.system_metrics if hasattr(ev.data, "system_metrics") else {}
                        hostname = metrics.get("hostname", "") if isinstance(metrics, dict) else ""
                        if client_id:
                            await registry_db.upsert_agent(
                                client_id,
                                hostname=hostname,
                                status="active",
                                connection_status="online",
                                metadata=metrics if isinstance(metrics, dict) else {},
                                last_seen_at=int(time.time()),
                            )
                        frontend_snapshot_event.set()
                    case "task_output":
                        task_db.append_log(
                            ev.data.task_id, ev.data.stream, ev.data.data, ev.data.seq)
                        await broadcast_task_event(ev.data.task_id, {
                            "type": "task_output",
                            "task_id": ev.data.task_id,
                            "stream": ev.data.stream,
                            "data": ev.data.data,
                            "seq": ev.data.seq
                        })
                    case "task_status":
                        await task_db.update_task_status(
                            ev.data.task_id, ev.data.status,
                            pid=ev.data.pid, exit_code=ev.data.exit_code, error=ev.data.error,
                            actor=client_id or "agent")
                        await broadcast_task_event(ev.data.task_id, {
                            "type": "task_status",
                            "task_id": ev.data.task_id,
                            "status": ev.data.status,
                            "pid": ev.data.pid,
                            "exit_code": ev.data.exit_code,
                            "error": ev.data.error
                        })
                        # Pipeline step orchestration
                        if ev.data.status in ("completed", "failed", "timeout"):
                            await _advance_pipeline(ev.data.task_id, ev.data.status)
                    case "process_screenshot":
                        await broadcast_process_screenshot({
                            "type": "process_screenshot",
                            "agent_id": ev.data.agent_id or client_id or "",
                            "target_type": ev.data.target_type,
                            "pid": ev.data.pid,
                            "hwnd": ev.data.hwnd,
                            "session_id": ev.data.session_id,
                            "request_id": ev.data.request_id,
                            "status": ev.data.status,
                            "image_base64": ev.data.image_base64,
                            "image_format": ev.data.image_format,
                            "window_title": ev.data.window_title,
                            "error": ev.data.error,
                            "captured_at": ev.data.captured_at,
                        })
            except Exception as e:
                logger.exception("Error processing agent message: %s", e)
            
    except WebSocketDisconnect:
        logger.info("Agent websocket disconnected: %s", client_id)
    except Exception as e:
        logger.exception("Agent websocket error: %s", e)
    finally:
        if client_id:
            await registry_db.upsert_agent(client_id, status="registered", connection_status="offline", last_seen_at=int(time.time()))
        if await agent_runtime.unregister_agent(client_id, ws):
            frontend_snapshot_event.set()


@app.websocket("/frontend")
async def frontend_ws(ws: WebSocket):
    await ws.accept()
    frontend_clients.add(ws)
    frontend_watched_agents[ws] = set()
    if agent_runtime.latest_stats:
        await ws.send_json({"kind": "agents_snapshot", "data": agent_runtime.build_frontend_snapshot()})
    eh = NetworkEventHandler(None)
    try:
        while True:

            msg = await ws.receive_text()
            ev = eh.parser(msg) 

            match(ev.type):
                case "start_program":
                    spe = StartProgramEvent(data=ev.data)
                    await _forward_frontend_event("start_program", ev.data.agent_id, spe)

                case "start_monitored_process":
                    spe = StartMonitoredProcessEvent(data=ev.data)
                    await _forward_frontend_event("start_monitored_process", ev.data.agent_id, spe)
                    
                case "create_session":
                    cse = CreateSessionEvent(data=ev.data)
                    await _forward_frontend_event("create_session", ev.data.agent_id, cse)

                case "capture_process_screenshot":
                    cpse = CaptureProcessScreenshotEvent(data=ev.data)
                    await _forward_frontend_event("capture_process_screenshot", ev.data.agent_id, cpse)

                case "watch_process_manager":
                    await _add_process_manager_watcher(ws, ev.data.agent_id)

                case "unwatch_process_manager":
                    await _remove_process_manager_watcher(ws, ev.data.agent_id)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("Frontend websocket error: %s", e)
    finally:
        await _remove_all_process_manager_watchers(ws)
        frontend_watched_agents.pop(ws, None)
        frontend_clients.discard(ws)

async def broadcast_to_frontends(data):
    for ws in list(frontend_clients):
        try:
            await ws.send_json({"kind": "agents_snapshot", "data": data})
        except Exception:
            frontend_clients.discard(ws)


# ── Task helpers ───────────────────────────────────────────────────

# Frontends subscribing to a specific task's live output
_task_subscribers: dict[str, set[WebSocket]] = {}  # task_id → set of frontend WS

async def broadcast_task_event(task_id: str, payload: dict):
    """Send task output/status to all frontend clients."""
    for ws in list(frontend_clients):
        try:
            await ws.send_json({"kind": "task_event", "data": payload})
        except Exception:
            frontend_clients.discard(ws)


async def broadcast_process_screenshot(payload: dict):
    for ws in list(frontend_clients):
        try:
            await ws.send_json({"kind": "process_screenshot", "data": payload})
        except Exception:
            frontend_clients.discard(ws)


async def _send_to_agent(agent_id: str, event) -> bool:
    """Forward an event to a specific agent. Returns True if sent."""
    agent_socket = agent_runtime.get_agent_socket(agent_id)
    if agent_socket is None:
        return False

    try:
        await agent_socket.send_text(event.model_dump_json())
        return True
    except Exception:
        await agent_runtime.unregister_agent(agent_id, agent_socket)
        frontend_snapshot_event.set()
        return False


async def _forward_frontend_event(event_name: str, requested_agent_id: str, event) -> bool:
    target_agent_id = requested_agent_id or agent_runtime.get_default_target_agent_id()

    if not target_agent_id:
        if agent_runtime.active_agent_count() == 0:
            logger.warning("No agent clients connected to forward %s", event_name)
        else:
            logger.warning("agent_id is required to forward %s when multiple agents are connected", event_name)
        return False

    sent = await _send_to_agent(target_agent_id, event)
    if not sent:
        logger.warning("No connected agent with id %s to forward %s", target_agent_id, event_name)
        return False

    logger.info("Forwarded %s to agent %s", event_name, target_agent_id)
    return True


async def _set_agent_window_tracking(agent_id: str, enabled: bool) -> bool:
    event = SetWindowTrackingEvent(data=SetWindowTrackingData(agent_id=agent_id, enabled=enabled))
    sent = await _send_to_agent(agent_id, event)
    if sent:
        logger.info("Forwarded set_window_tracking=%s to agent %s", enabled, agent_id)
    else:
        logger.warning("Failed to forward set_window_tracking=%s to agent %s", enabled, agent_id)
    return sent


async def _add_process_manager_watcher(ws: WebSocket, agent_id: str):
    if not agent_id:
        return

    watched_agents = frontend_watched_agents.setdefault(ws, set())
    if agent_id in watched_agents:
        return

    watchers = process_manager_watchers.setdefault(agent_id, set())
    was_empty = len(watchers) == 0
    watchers.add(ws)
    watched_agents.add(agent_id)

    if was_empty:
        await _set_agent_window_tracking(agent_id, True)


async def _remove_process_manager_watcher(ws: WebSocket, agent_id: str):
    if not agent_id:
        return

    watched_agents = frontend_watched_agents.get(ws)
    if watched_agents is not None:
        watched_agents.discard(agent_id)

    watchers = process_manager_watchers.get(agent_id)
    if not watchers:
        return

    watchers.discard(ws)
    if len(watchers) == 0:
        process_manager_watchers.pop(agent_id, None)
        await _set_agent_window_tracking(agent_id, False)


async def _remove_all_process_manager_watchers(ws: WebSocket):
    for agent_id in list(frontend_watched_agents.get(ws, set())):
        await _remove_process_manager_watcher(ws, agent_id)


async def _advance_pipeline(task_id: str, task_status: str):
    """When a pipeline step finishes, advance to the next step or mark pipeline done."""
    task = await task_db.get_task(task_id)
    if not task or not task.get("pipeline_run_id"):
        return

    run_id = task["pipeline_run_id"]
    run = await task_db.get_pipeline_run(run_id)
    if not run or run["status"] not in ("running", "queued"):
        return

    pipeline = await task_db.get_pipeline(run["pipeline_id"])
    if not pipeline:
        return

    steps = pipeline.get("steps", [])
    current_step = task["step_index"]

    if task_status == "failed" or task_status == "timeout":
        # Check on_fail policy for this step
        step_def = next((s for s in steps if s["step_index"] == current_step), None)
        on_fail = step_def.get("on_fail", "stop") if step_def else "stop"
        if on_fail == "stop":
            await task_db.update_pipeline_run_status(run_id, "failed", current_step)
            return

    # Try to advance to next step
    next_index = current_step + 1
    next_step = next((s for s in steps if s["step_index"] == next_index), None)

    if not next_step:
        # All steps done
        await task_db.update_pipeline_run_status(run_id, "completed", current_step)
        return

    # Create and dispatch next task
    next_task_id = uuid4().hex
    await task_db.create_task(
        task_id=next_task_id,
        agent_id=run["agent_id"],
        script=next_step["script"],
        name=next_step.get("name", f"Step {next_index}"),
        cwd=next_step.get("cwd", ""),
        timeout_sec=next_step.get("timeout_sec", 300),
        session=run.get("session", ""),
        pipeline_run_id=run_id,
        step_index=next_index,
        requested_by="pipeline",
    )
    await task_db.update_pipeline_run_status(run_id, "running", next_index)

    sent = await _send_to_agent(run["agent_id"], ExecuteTaskEvent(
        data=ExecuteTaskData(
            task_id=next_task_id,
            script=next_step["script"],
            cwd=next_step.get("cwd", ""),
            timeout_sec=next_step.get("timeout_sec", 300),
            session=run.get("session", ""),
        )
    ))
    if sent:
        await task_db.update_task_status(next_task_id, "running", actor="server")

# --- REST API for historical data ---

@app.get("/api/metrics")
async def api_metrics(
    agent_id: str,
    pid: int = None,
    from_ts: int = None,
    to_ts: int = None,
    limit: int = Query(default=50000, le=100000)
):
    rows = await telemetry_db.get_metrics(agent_id, pid, from_ts, to_ts, limit)
    return JSONResponse(rows)


@app.get("/api/events")
async def api_events(
    agent_id: str = None,
    event_type: str = None,
    from_ts: int = None,
    to_ts: int = None,
    limit: int = Query(default=200, le=5000)
):
    rows = await telemetry_db.get_events(agent_id, event_type, from_ts, to_ts, limit)
    return JSONResponse(rows)


@app.get("/api/agents/summary")
async def api_agents_summary():
    rows = await telemetry_db.get_agents_summary()
    return JSONResponse(rows)


@app.get("/api/agents/{agent_id}")
async def api_agent_state(agent_id: str):
    state = agent_runtime.get_agent_state(agent_id)
    if state is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(state)


@app.get("/api/agent-registry")
async def api_agent_registry(limit: int = Query(default=200, le=500)):
    return JSONResponse(await registry_db.get_agents(limit))


@app.get("/api/agent-registry/{agent_id}")
async def api_agent_registry_item(agent_id: str):
    item = await registry_db.get_agent(agent_id)
    if not item:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(item)


def _resolve_agent_ws_url(request: Request) -> str:
    override = os.getenv("VM_AGENT_SERVER_WS_URL")
    if override:
        return override
    scheme = "wss" if request.url.scheme == "https" else "ws"
    port = request.url.port or (443 if request.url.scheme == "https" else 80)
    return f"{scheme}://{request.url.hostname}:{port}/ws"


@app.post("/api/deployments/prepare")
async def api_prepare_deployment(request: Request):
    body = await request.json()
    hostname = (body.get("hostname") or "").strip()
    if not hostname:
        return JSONResponse({"error": "hostname is required"}, status_code=400)

    agent_id = (body.get("agent_id") or hostname).strip()
    display_name = (body.get("display_name") or hostname).strip()
    source_ref = (body.get("source_ref") or "main").strip() or "main"
    requested_by = (body.get("requested_by") or "user").strip() or "user"

    deployment = await deployment_service.prepare_deployment(
        agent_id=agent_id,
        hostname=hostname,
        display_name=display_name,
        source_ref=source_ref,
        requested_by=requested_by,
        server_ws_url=_resolve_agent_ws_url(request),
    )
    return JSONResponse(deployment)


@app.get("/api/deployments")
async def api_list_deployments(agent_id: str = None, limit: int = Query(default=100, le=500)):
    return JSONResponse(await registry_db.get_deployments(agent_id=agent_id, limit=limit))


@app.get("/api/deployments/{deployment_id}")
async def api_get_deployment(deployment_id: str):
    deployment = await registry_db.get_deployment(deployment_id)
    if not deployment:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(deployment)


@app.get("/api/guacamole/config")
async def api_guacamole_config():
    return JSONResponse(get_guacamole_config())


@app.get("/api/agents/{agent_id}/guacamole")
async def api_agent_guacamole(agent_id: str):
    state = agent_runtime.get_agent_state(agent_id)
    if state is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(build_guacamole_session(agent_id, state))


# ── Task REST API ──────────────────────────────────────────────────

@app.post("/api/tasks")
async def api_create_task(request: Request):
    """Create and dispatch a task to an agent."""
    body = await request.json()
    task_id = uuid4().hex
    agent_id = body.get("agent_id", "")
    script = body.get("script", "")
    name = body.get("name", "")
    cwd = body.get("cwd", "")
    timeout_sec = body.get("timeout_sec", 300)
    session = body.get("session", "")
    requested_by = body.get("requested_by", "user")
    requested_from = request.client.host if request.client else ""

    if not agent_id or not script:
        return JSONResponse({"error": "agent_id and script are required"}, status_code=400)

    task = await task_db.create_task(
        task_id=task_id, agent_id=agent_id, script=script, name=name,
        cwd=cwd, timeout_sec=timeout_sec, session=session,
        requested_by=requested_by, requested_from=requested_from
    )

    # Dispatch to agent
    sent = await _send_to_agent(agent_id, ExecuteTaskEvent(
        data=ExecuteTaskData(
            task_id=task_id, script=script, cwd=cwd,
            timeout_sec=timeout_sec, session=session,
            env=body.get("env", {}),
        )
    ))
    if not sent:
        await task_db.update_task_status(task_id, "failed",
                                          error="Agent not connected", actor="server")
        task["status"] = "failed"
        task["error"] = "Agent not connected"

    return JSONResponse(task)


@app.get("/api/tasks")
async def api_list_tasks(
    agent_id: str = None,
    status: str = None,
    limit: int = Query(default=50, le=500)
):
    rows = await task_db.get_tasks(agent_id, status, limit)
    return JSONResponse(rows)


@app.get("/api/tasks/{task_id}")
async def api_get_task(task_id: str):
    task = await task_db.get_task(task_id)
    if not task:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(task)


@app.post("/api/tasks/{task_id}/cancel")
async def api_cancel_task(task_id: str, request: Request):
    task = await task_db.get_task(task_id)
    if not task:
        return JSONResponse({"error": "Not found"}, status_code=404)
    if task["status"] not in ("queued", "running"):
        return JSONResponse({"error": f"Cannot cancel task in status {task['status']}"}, status_code=400)

    sent = await _send_to_agent(task["agent_id"], CancelTaskEvent(
        data=CancelTaskData(task_id=task_id)
    ))
    if sent:
        await task_db.update_task_status(task_id, "cancelled",
                                          actor=request.client.host if request.client else "user")
    return JSONResponse({"ok": True, "sent": sent})


@app.get("/api/tasks/{task_id}/log")
async def api_task_log(task_id: str, offset: int = 0, limit: int = 0):
    """Read task log from disk. offset=byte offset, limit=max bytes."""
    result = task_db.read_log(task_id, offset, limit)
    return JSONResponse(result)


@app.get("/api/tasks/{task_id}/log/raw")
async def api_task_log_raw(task_id: str):
    """Download raw log file."""
    result = task_db.read_log(task_id)
    return PlainTextResponse(result["content"], media_type="text/plain")


# ── Pipeline REST API ──────────────────────────────────────────────

@app.post("/api/pipelines")
async def api_create_pipeline(request: Request):
    body = await request.json()
    pipeline_id = uuid4().hex
    name = body.get("name", "Unnamed Pipeline")
    description = body.get("description", "")
    steps = body.get("steps", [])
    requested_by = body.get("created_by", "user")

    if not steps:
        return JSONResponse({"error": "At least one step is required"}, status_code=400)

    pipeline = await task_db.create_pipeline(
        pipeline_id, name, steps, description, requested_by)
    return JSONResponse(pipeline)


@app.get("/api/pipelines")
async def api_list_pipelines(limit: int = Query(default=50, le=200)):
    rows = await task_db.get_pipelines(limit)
    return JSONResponse(rows)


@app.get("/api/pipelines/{pipeline_id}")
async def api_get_pipeline(pipeline_id: str):
    pipeline = await task_db.get_pipeline(pipeline_id)
    if not pipeline:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(pipeline)


@app.post("/api/pipelines/{pipeline_id}/run")
async def api_run_pipeline(pipeline_id: str, request: Request):
    """Start a pipeline run — creates tasks for each step, dispatches the first."""
    body = await request.json()
    agent_id = body.get("agent_id", "")
    session = body.get("session", "")
    requested_by = body.get("requested_by", "user")
    requested_from = request.client.host if request.client else ""

    pipeline = await task_db.get_pipeline(pipeline_id)
    if not pipeline:
        return JSONResponse({"error": "Pipeline not found"}, status_code=404)
    if not agent_id:
        return JSONResponse({"error": "agent_id is required"}, status_code=400)

    steps = pipeline.get("steps", [])
    if not steps:
        return JSONResponse({"error": "Pipeline has no steps"}, status_code=400)

    run_id = uuid4().hex
    run = await task_db.create_pipeline_run(
        run_id, pipeline_id, agent_id, session, requested_by, requested_from)

    # Create first step's task
    first_step = steps[0]
    task_id = uuid4().hex
    await task_db.create_task(
        task_id=task_id, agent_id=agent_id, script=first_step["script"],
        name=first_step.get("name", "Step 0"), cwd=first_step.get("cwd", ""),
        timeout_sec=first_step.get("timeout_sec", 300), session=session,
        pipeline_run_id=run_id, step_index=first_step.get("step_index", 0),
        requested_by=requested_by, requested_from=requested_from
    )
    await task_db.update_pipeline_run_status(run_id, "running", 0)

    sent = await _send_to_agent(agent_id, ExecuteTaskEvent(
        data=ExecuteTaskData(
            task_id=task_id, script=first_step["script"],
            cwd=first_step.get("cwd", ""),
            timeout_sec=first_step.get("timeout_sec", 300),
            session=session,
        )
    ))
    if sent:
        await task_db.update_task_status(task_id, "running", actor="server")
    else:
        await task_db.update_task_status(task_id, "failed",
                                          error="Agent not connected", actor="server")
        await task_db.update_pipeline_run_status(run_id, "failed", 0)

    return JSONResponse({"run_id": run_id, "task_id": task_id, "sent": sent})


@app.get("/api/pipeline-runs/{run_id}")
async def api_get_pipeline_run(run_id: str):
    run = await task_db.get_pipeline_run(run_id)
    if not run:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(run)


# ── Audit log API ──────────────────────────────────────────────────

@app.get("/api/audit")
async def api_audit_log(
    entity_type: str = None,
    entity_id: str = None,
    limit: int = Query(default=100, le=1000)
):
    rows = await task_db.get_audit_log(entity_type, entity_id, limit)
    return JSONResponse(rows)


if __name__ == "__main__":
    #disable_rdp_publisher_warning()
    #add_trusted_rdp_host("DESKTOP-JJULF7D")
    uvicorn.run("vm_agent_server.src.server:app", host="0.0.0.0", port=8765, reload=False)