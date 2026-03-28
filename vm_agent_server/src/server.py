import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
import uvicorn
from websockets.asyncio.client import connect as websocket_connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from vm_agent_server.src.api.routers.guacamole_router import build_guacamole_router
from shared.network.events.example_event import AuthResultData, AuthResultEvent, CaptureProcessScreenshotEvent, CreateSessionEvent, CancelTaskEvent, CancelTaskData, HeartbeatData, SetWindowTrackingData, SetWindowTrackingEvent, StartMonitoredProcessEvent, StartProgramEvent
from vm_agent_server.src.api.routers.deployment_router import build_deployment_router
from vm_agent_server.src.api.routers.task_router import build_task_router
from vm_agent_server.src.agent_registry_db import AgentRegistryDB
from vm_agent_server.src.deployment_service import DeploymentService
from vm_agent_server.src.network_event_handler import NetworkEventHandler
from vm_agent_server.src.add_trust_rdp_host import add_trusted_rdp_host, disable_rdp_publisher_warning
from vm_agent_server.src.agent_runtime import AgentRuntime, HEARTBEAT_TIMEOUT_SECONDS
from vm_agent_server.src.guacamole_bridge import build_guacamole_proxy_tunnel_urls, build_guacamole_session, create_guacamole_client_session, get_guacamole_config, get_guacamole_request_base_url, inspect_guacamole_connection, invalidate_guacamole_token, list_guacamole_connections
from vm_agent_server.src.telemetry_db import TelemetryDB
from vm_agent_server.src.task_db import TaskDB
from vm_agent_server.src.task_dispatcher import TaskDispatcher, build_agent_task_handler, build_deployment_task_handler
from vm_agent_server.src.task_service import TaskService

telemetry_db = TelemetryDB()
task_db = TaskDB()
registry_db = AgentRegistryDB()
agent_runtime = AgentRuntime()
frontend_snapshot_event = asyncio.Event()
frontend_snapshot_broadcast_task: asyncio.Task | None = None
heartbeat_watchdog_task: asyncio.Task | None = None
logger = logging.getLogger(__name__)
repo_root = Path(__file__).resolve().parents[2]
task_dispatcher = TaskDispatcher()
task_service = TaskService(task_db, task_dispatcher)
deployment_service = DeploymentService(registry_db, task_db, repo_root)
deployment_service.set_task_service(task_service)


def _is_benign_connection_reset(context: dict[str, object]) -> bool:
    exception = context.get("exception")
    if not isinstance(exception, ConnectionResetError):
        return False

    if getattr(exception, "winerror", None) != 10054:
        return False

    handle = context.get("handle")
    return "_ProactorBasePipeTransport._call_connection_lost" in str(handle)


class _UvicornAccessPathFilter(logging.Filter):
    def __init__(self, suppressed_fragments: tuple[str, ...]):
        super().__init__()
        self.suppressed_fragments = suppressed_fragments

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(fragment in message for fragment in self.suppressed_fragments)


def _configure_access_log_filters() -> None:
    if (os.getenv("VM_AGENT_SERVER_SUPPRESS_GUAC_TUNNEL_ACCESS_LOGS") or "true").strip().lower() not in {"1", "true", "yes", "on"}:
        return

    access_logger = logging.getLogger("uvicorn.access")
    suppressed_fragments = (
        ' /api/guacamole/tunnel?',
        ' /api/guacamole/websocket-tunnel',
    )

    for existing_filter in access_logger.filters:
        if isinstance(existing_filter, _UvicornAccessPathFilter):
            return

    access_logger.addFilter(_UvicornAccessPathFilter(suppressed_fragments))


_configure_access_log_filters()


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
    loop = asyncio.get_running_loop()
    previous_exception_handler = loop.get_exception_handler()

    def loop_exception_handler(loop: asyncio.AbstractEventLoop, context: dict[str, object]) -> None:
        if _is_benign_connection_reset(context):
            return
        if previous_exception_handler is not None:
            previous_exception_handler(loop, context)
            return
        loop.default_exception_handler(context)

    loop.set_exception_handler(loop_exception_handler)
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
    loop.set_exception_handler(previous_exception_handler)
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
    expose_headers=["Guacamole-Tunnel-Token", "Guacamole-Status-Code", "Guacamole-Error-Message"],
)
frontend_clients = set()
process_manager_watchers: dict[str, set[WebSocket]] = {}
frontend_watched_agents: dict[WebSocket, set[str]] = {}
guacamole_agent_tokens: dict[str, set[str]] = {}
guacamole_http_tunnel_tokens: dict[str, str] = {}
guacamole_websocket_proxy_supported: bool | None = None


def _extract_bearer_token(header_value: str | None) -> str | None:
    if not header_value:
        return None
    prefix = "bearer "
    if header_value.lower().startswith(prefix):
        return header_value[len(prefix):].strip()
    return None

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    auth_token = _extract_bearer_token(ws.headers.get("authorization"))
    await ws.accept()    
    await ws.send_text('{"type":"handshake","data":{"client_id":"server","capabilities":["ws"]}}')

    client_id = None
    authenticated = False
    try:
        while True:
            msg = await ws.receive_text()
            try:
                eh = NetworkEventHandler(None)
                ev = eh.parser(msg)

                match(ev.type):
                    case "handshake":
                        requested_client_id = ev.data.client_id
                        reported_hostname = str(getattr(ev.data, "hostname", "") or "").strip()
                        auth_result = await registry_db.authorize_agent(requested_client_id, auth_token)
                        if not auth_result.get("authorized"):
                            reason = auth_result.get("reason", "unauthorized")
                            latest_deployment = await registry_db.get_latest_deployment_for_agent(requested_client_id)
                            if latest_deployment and reason == "bootstrap token expired":
                                await registry_db.update_deployment(
                                    latest_deployment["id"],
                                    status="expired_bootstrap",
                                    error="Bootstrap token expired before the first successful agent start.",
                                    completed_at=int(time.time()),
                                )
                                await registry_db.upsert_agent(
                                    requested_client_id,
                                    status="bootstrap_expired",
                                    connection_status="offline",
                                    last_deployment_id=latest_deployment["id"],
                                    last_seen_at=int(time.time()),
                                )
                            logger.warning("Rejecting agent %s during handshake: %s", requested_client_id, reason)
                            await ws.send_text(AuthResultEvent(data=AuthResultData(status="error", agent_id=requested_client_id, reason=reason)).model_dump_json())
                            await ws.close(code=4401, reason=reason)
                            return

                        expected_hostname = await registry_db.get_expected_hostname_for_agent(requested_client_id)
                        if expected_hostname and reported_hostname and expected_hostname.lower() != reported_hostname.lower():
                            reason = f"hostname mismatch: expected {expected_hostname}, got {reported_hostname}"
                            latest_deployment = await registry_db.get_latest_deployment_for_agent(requested_client_id)
                            if latest_deployment:
                                await registry_db.update_deployment(
                                    latest_deployment["id"],
                                    error=f"Agent attempted bootstrap from unexpected host '{reported_hostname}'. Expected '{expected_hostname}'.",
                                )
                            await registry_db.upsert_agent(
                                requested_client_id,
                                hostname=expected_hostname,
                                status="hostname_mismatch",
                                connection_status="offline",
                                last_seen_at=int(time.time()),
                            )
                            logger.warning("Rejecting agent %s during handshake: %s", requested_client_id, reason)
                            await ws.send_text(AuthResultEvent(data=AuthResultData(status="error", agent_id=requested_client_id, reason=reason)).model_dump_json())
                            await ws.close(code=4403, reason="hostname mismatch")
                            return

                        client_id = requested_client_id
                        authenticated = True
                        issued_secret = auth_result.get("issued_secret") or ""
                        await ws.send_text(
                            AuthResultEvent(
                                data=AuthResultData(
                                    status="ok",
                                    agent_id=client_id,
                                    secret=issued_secret,
                                    secret_issued=bool(issued_secret),
                                )
                            ).model_dump_json()
                        )
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
                        if not authenticated:
                            await ws.close(code=4401, reason="handshake required")
                            return
                        agent_runtime.merge_heartbeat(ev.data, telemetry_db)
                        metrics = ev.data.system_metrics if hasattr(ev.data, "system_metrics") else {}
                        hostname = metrics.get("hostname", "") if isinstance(metrics, dict) else ""
                        if client_id:
                            expected_hostname = await registry_db.get_expected_hostname_for_agent(client_id)
                            if expected_hostname and hostname and expected_hostname.lower() != hostname.lower():
                                logger.warning(
                                    "Disconnecting agent %s after heartbeat hostname mismatch: expected %s, got %s",
                                    client_id,
                                    expected_hostname,
                                    hostname,
                                )
                                await registry_db.upsert_agent(
                                    client_id,
                                    hostname=expected_hostname,
                                    status="hostname_mismatch",
                                    connection_status="offline",
                                    last_seen_at=int(time.time()),
                                )
                                await ws.close(code=4403, reason="hostname mismatch")
                                return
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
                        if not authenticated:
                            await ws.close(code=4401, reason="handshake required")
                            return
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
                        if not authenticated:
                            await ws.close(code=4401, reason="handshake required")
                            return
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
                            await task_service.advance_pipeline(ev.data.task_id, ev.data.status)
                    case "process_screenshot":
                        if not authenticated:
                            await ws.close(code=4401, reason="handshake required")
                            return
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


def _configure_task_handlers() -> None:
    task_dispatcher.register_handler("agent", build_agent_task_handler(_send_to_agent))
    task_dispatcher.register_handler("deployment", build_deployment_task_handler(deployment_service.dispatch_task))


_configure_task_handlers()


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


def _resolve_public_base_url(request: Request) -> str:
    override = os.getenv("VM_AGENT_SERVER_PUBLIC_URL")
    if override:
        return override.rstrip("/")
    return str(request.base_url).rstrip("/")


def _get_guacamole_base_url() -> str:
    return get_guacamole_request_base_url()


def _get_guacamole_websocket_tunnel_url() -> str:
    base_url = _get_guacamole_base_url()
    if not base_url:
        return ""
    if base_url.startswith("https://"):
        return f"wss://{base_url[len('https://'): ]}/websocket-tunnel"
    if base_url.startswith("http://"):
        return f"ws://{base_url[len('http://'): ]}/websocket-tunnel"
    return f"{base_url}/websocket-tunnel"


def _copy_guacamole_response_headers(headers: any) -> dict[str, str]:
    forwarded: dict[str, str] = {}
    for header_name in [
        "Content-Type",
        "Guacamole-Tunnel-Token",
        "Guacamole-Status-Code",
        "Guacamole-Error-Message",
        "Cache-Control",
    ]:
        value = headers.get(header_name)
        if value:
            forwarded[header_name] = value
    return forwarded


def _extract_guacamole_tunnel_uuid(raw_query: str) -> str:
    if raw_query == "connect":
        return ""

    for prefix in ("read:", "write:"):
        if raw_query.startswith(prefix):
            remainder = raw_query[len(prefix):]
            if prefix == "read:":
                return remainder.split(":", 1)[0].strip()
            return remainder.strip()

    return ""


def _proxy_guacamole_tunnel_request(method: str, raw_query: str, body: bytes, headers: dict[str, str]) -> Response:
    base_url = _get_guacamole_base_url()
    if not base_url:
        return JSONResponse({"error": "Guacamole bridge is not configured"}, status_code=503)

    upstream_url = f"{base_url}/tunnel"
    if raw_query:
        upstream_url = f"{upstream_url}?{raw_query}"

    request_headers = {
        "Accept": headers.get("accept") or "*/*",
    }
    content_type = headers.get("content-type")
    if content_type:
        request_headers["Content-Type"] = content_type
    tunnel_uuid = _extract_guacamole_tunnel_uuid(raw_query)
    tunnel_token = headers.get("guacamole-tunnel-token") or guacamole_http_tunnel_tokens.get(tunnel_uuid, "")
    if tunnel_token:
        request_headers["Guacamole-Tunnel-Token"] = tunnel_token

    upstream_request = UrlRequest(
        upstream_url,
        data=body if method != "GET" else None,
        headers=request_headers,
        method=method,
    )

    try:
        upstream_response = urlopen(upstream_request, timeout=60)
    except HTTPError as error:
        error_body = error.read()
        if tunnel_uuid and error.code in {404, 410}:
            guacamole_http_tunnel_tokens.pop(tunnel_uuid, None)
        return Response(
            content=error_body,
            status_code=error.code,
            headers=_copy_guacamole_response_headers(error.headers),
            media_type=error.headers.get("Content-Type"),
        )
    except URLError as error:
        return JSONResponse({"error": f"Could not reach Guacamole tunnel: {error.reason}"}, status_code=502)
    except OSError as error:
        return JSONResponse({"error": f"Guacamole tunnel proxy failed: {error}"}, status_code=502)

    response_headers = _copy_guacamole_response_headers(upstream_response.headers)
    media_type = upstream_response.headers.get("Content-Type")

    if raw_query == "connect":
        connect_uuid = upstream_response.read().decode("utf-8").strip()
        connect_tunnel_token = response_headers.get("Guacamole-Tunnel-Token", "").strip()
        upstream_response.close()
        if connect_uuid and connect_tunnel_token:
            guacamole_http_tunnel_tokens[connect_uuid] = connect_tunnel_token
        return Response(
            content=connect_uuid,
            status_code=upstream_response.status,
            headers=response_headers,
            media_type=media_type,
        )

    if method == "GET":
        async def iter_chunks():
            reader = getattr(upstream_response, "read1", upstream_response.read)
            try:
                while True:
                    chunk = await asyncio.to_thread(reader, 1024)
                    if not chunk:
                        break
                    yield chunk
            except asyncio.CancelledError:
                return
            finally:
                upstream_response.close()

        return StreamingResponse(
            iter_chunks(),
            status_code=upstream_response.status,
            headers={
                **response_headers,
                "Cache-Control": response_headers.get("Cache-Control", "no-cache"),
                "X-Accel-Buffering": "no",
            },
            media_type=media_type,
        )

    response_body = upstream_response.read()
    upstream_response.close()
    if tunnel_uuid and raw_query.startswith("write:") and upstream_response.status >= 400:
        guacamole_http_tunnel_tokens.pop(tunnel_uuid, None)
    return Response(
        content=response_body,
        status_code=upstream_response.status,
        headers=response_headers,
        media_type=media_type,
    )


app.include_router(build_task_router(task_service, task_db, _send_to_agent))
app.include_router(build_deployment_router(deployment_service, registry_db, _resolve_agent_ws_url))
app.include_router(
    build_guacamole_router(
        agent_runtime.get_agent_state,
        _resolve_public_base_url,
        build_guacamole_proxy_tunnel_urls,
        get_guacamole_config,
        list_guacamole_connections,
        build_guacamole_session,
        inspect_guacamole_connection,
        create_guacamole_client_session,
        invalidate_guacamole_token,
        _get_guacamole_base_url,
        _proxy_guacamole_tunnel_request,
        lambda: guacamole_websocket_proxy_supported,
        guacamole_agent_tokens,
    )
)


@app.websocket("/api/guacamole/websocket-tunnel")
async def api_guacamole_websocket_tunnel(ws: WebSocket):
    global guacamole_websocket_proxy_supported
    upstream_base = _get_guacamole_websocket_tunnel_url()
    if not upstream_base:
        await ws.close(code=1011, reason="Guacamole bridge is not configured")
        return

    raw_query = ws.scope.get("query_string", b"").decode("utf-8")
    upstream_url = f"{upstream_base}?{raw_query}" if raw_query else upstream_base

    await ws.accept()

    try:
        async with websocket_connect(upstream_url, max_size=None) as upstream:
            guacamole_websocket_proxy_supported = True
            async def client_to_upstream():
                while True:
                    message = await ws.receive()
                    if message.get("type") == "websocket.disconnect":
                        break
                    if message.get("text") is not None:
                        await upstream.send(message["text"])
                    elif message.get("bytes") is not None:
                        await upstream.send(message["bytes"])

            async def upstream_to_client():
                while True:
                    payload = await upstream.recv()
                    if isinstance(payload, bytes):
                        await ws.send_bytes(payload)
                    else:
                        await ws.send_text(payload)

            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except WebSocketDisconnect:
        return
    except InvalidStatus as error:
        if getattr(error, "response", None) is not None and getattr(error.response, "status_code", None) == 404:
            guacamole_websocket_proxy_supported = False
            try:
                await ws.close(code=1000, reason="Guacamole websocket tunnel unavailable")
            except RuntimeError:
                pass
            return
        logger.warning("Guacamole websocket tunnel proxy failed: %s", error)
        try:
            await ws.close(code=1011, reason="Guacamole websocket tunnel failed")
        except RuntimeError:
            pass
    except ConnectionClosed:
        try:
            await ws.close()
        except RuntimeError:
            pass
    except Exception as error:
        logger.warning("Guacamole websocket tunnel proxy failed: %s", error)
        try:
            await ws.close(code=1011, reason="Guacamole websocket tunnel failed")
        except RuntimeError:
            pass
if __name__ == "__main__":
    #disable_rdp_publisher_warning()
    #add_trusted_rdp_host("DESKTOP-JJULF7D")
    uvicorn.run("vm_agent_server.src.server:app", host="0.0.0.0", port=8765, reload=False)