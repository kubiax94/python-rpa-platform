import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel
import uvicorn
from websockets.asyncio.client import connect as websocket_connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from vm_agent_server.src.agents import AgentCommandHandler, AgentLifecycleEventHandler
from vm_agent_server.src.api.routers.guacamole_router import build_guacamole_router
from vm_agent_server.src.api.routers.settings_router import build_settings_router
from vm_agent_server.src.api.routers.users_router import build_users_router
from vm_agent_server.src.api.schemas.agent_responses import AgentTokenRotationResponse
from vm_agent_server.src.authz import request_has_minimum_role, role_required_response, websocket_has_minimum_role
from vm_agent_server.src.api.routers.deployment_router import build_deployment_router
from vm_agent_server.src.api.routers.task_router import build_task_router
from vm_agent_server.src.persistence.agent_registry_db import AgentRegistryDB
from vm_agent_server.src.add_trust_rdp_host import add_trusted_rdp_host, disable_rdp_publisher_warning
from vm_agent_server.src.agent_runtime import AgentRuntime, HEARTBEAT_TIMEOUT_SECONDS
from vm_agent_server.src.guacamole.bridge import build_guacamole_proxy_tunnel_urls, build_guacamole_session, create_guacamole_client_session, get_guacamole_config, get_guacamole_request_base_url, inspect_guacamole_connection, invalidate_guacamole_token, list_guacamole_connections, provision_guacamole_agent_target_with_diagnostics, set_guacamole_settings_provider
from vm_agent_server.src.network.agent_session import run_agent_ws_session
from vm_agent_server.src.network.context import AgentSessionDependencies, FrontendSessionDependencies
from vm_agent_server.src.network.frontend_session import run_frontend_ws_session
from vm_agent_server.src.process_monitoring import ProcessMonitoringNetworkHandler
from vm_agent_server.src.settings.db import ServerSettingsDB
from vm_agent_server.src.settings.service import ServerSettingsService
from vm_agent_server.src.services import DeploymentService, GuacamoleService, RdpMonitorService, TaskService, UserService
from vm_agent_server.src.persistence.telemetry_db import TelemetryDB
from vm_agent_server.src.tasks.db import TaskDB
from vm_agent_server.src.tasks.dispatcher import TaskDispatcher, build_agent_task_handler, build_deployment_task_handler
from vm_agent_server.src.tasks.network_handler import TaskNetworkHandler

telemetry_db = TelemetryDB()
task_db = TaskDB()
registry_db = AgentRegistryDB()
server_settings_db = ServerSettingsDB()
server_settings_service = ServerSettingsService(server_settings_db)
set_guacamole_settings_provider(server_settings_service.get_snapshot)
user_service = UserService()
agent_runtime = AgentRuntime()
frontend_snapshot_event = asyncio.Event()
frontend_snapshot_broadcast_task: asyncio.Task | None = None
heartbeat_watchdog_task: asyncio.Task | None = None
rdp_session_watchdog_task: asyncio.Task | None = None
logger = logging.getLogger(__name__)
repo_root = Path(__file__).resolve().parents[2]
task_dispatcher = TaskDispatcher()
task_service = TaskService(task_db, task_dispatcher)
task_network_handler = TaskNetworkHandler(task_db, task_service)
agent_command_handler = AgentCommandHandler()
deployment_service = DeploymentService(registry_db, task_db, repo_root, server_settings_service=server_settings_service)
deployment_service.set_task_service(task_service)
rdp_monitor_service = RdpMonitorService()
guacamole_service = GuacamoleService(
    build_proxy_tunnel_urls=build_guacamole_proxy_tunnel_urls,
    get_guacamole_config=get_guacamole_config,
    list_guacamole_connections=list_guacamole_connections,
    build_guacamole_session=build_guacamole_session,
    inspect_guacamole_connection=inspect_guacamole_connection,
    create_guacamole_client_session=create_guacamole_client_session,
    invalidate_guacamole_token=invalidate_guacamole_token,
    get_guacamole_base_url=get_guacamole_request_base_url,
    rdp_monitor=rdp_monitor_service,
)


class AgentGuacamoleFileTransferUpdateRequest(BaseModel):
    upload_enabled: bool | None = None
    download_enabled: bool | None = None


class AgentGuacamoleAccessUpdateRequest(BaseModel):
    minimum_role: Literal["viewer", "operator", "admin"] | None = None
    interactive_minimum_role: Literal["viewer", "operator", "admin"] | None = None
    file_transfer: AgentGuacamoleFileTransferUpdateRequest | None = None


class AgentRegistryUpdateRequest(BaseModel):
    hostname: str | None = None
    display_name: str | None = None
    guacamole_access: AgentGuacamoleAccessUpdateRequest | None = None


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


async def _rdp_session_watchdog():
    interval = 30
    raw_interval = (os.getenv("RDP_MONITOR_SWEEP_INTERVAL_SECONDS") or "30").strip()
    try:
        interval = max(5, int(raw_interval))
    except ValueError:
        interval = 30

    while True:
        await asyncio.sleep(interval)
        expired_count = await guacamole_service.expire_idle_sessions()
        if expired_count > 0:
            logger.info("Expired %s idle Guacamole session(s)", expired_count)


async def _close_frontend_socket(ws: WebSocket) -> None:
    try:
        await ws.close(code=1001, reason="Server shutdown")
    except Exception:
        pass


async def _shutdown_open_connections() -> None:
    for ws in list(frontend_clients):
        await _remove_all_process_manager_watchers(ws)
        await _close_frontend_socket(ws)
        frontend_watched_agents.pop(ws, None)
        frontend_clients.discard(ws)

    process_manager_watchers.clear()
    frontend_watched_agents.clear()

    closed_agents = await agent_runtime.close_all_connections()
    if closed_agents > 0:
        logger.info("Closed %s active agent websocket connection(s) during shutdown", closed_agents)

    closed_guacamole = await guacamole_service.close_all_sessions()
    if closed_guacamole > 0:
        logger.info("Closed %s tracked Guacamole session(s) during shutdown", closed_guacamole)

@asynccontextmanager
async def lifespan(app):
    global frontend_snapshot_broadcast_task, heartbeat_watchdog_task, rdp_session_watchdog_task
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
    await server_settings_db.start()
    await server_settings_service.initialize()
    await deployment_service.recover_interrupted_deployments()
    frontend_snapshot_broadcast_task = asyncio.create_task(_frontend_snapshot_broadcaster())
    heartbeat_watchdog_task = asyncio.create_task(_heartbeat_watchdog())
    rdp_session_watchdog_task = asyncio.create_task(_rdp_session_watchdog())
    yield
    if rdp_session_watchdog_task:
        rdp_session_watchdog_task.cancel()
        try:
            await rdp_session_watchdog_task
        except asyncio.CancelledError:
            pass
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
    await _shutdown_open_connections()
    loop.set_exception_handler(previous_exception_handler)
    await task_db.stop()
    await telemetry_db.stop()
    await registry_db.stop()
    await server_settings_db.stop()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Guacamole-Tunnel-Token", "Guacamole-Status-Code", "Guacamole-Error-Message"],
)
frontend_clients = set()
process_manager_watchers: dict[str, set[WebSocket]] = {}
frontend_watched_agents: dict[WebSocket, set[str]] = {}


def _get_agent_lifecycle_handler() -> AgentLifecycleEventHandler:
    return AgentLifecycleEventHandler(
        registry_db,
        agent_runtime,
        telemetry_db,
        frontend_snapshot_event,
        process_manager_watchers,
    )


def _get_process_monitoring_handler() -> ProcessMonitoringNetworkHandler:
    return ProcessMonitoringNetworkHandler(
        _send_to_agent,
        process_manager_watchers,
        frontend_watched_agents,
    )


def _build_frontend_session_dependencies() -> FrontendSessionDependencies:
    return FrontendSessionDependencies(
        user_service=user_service,
        agent_runtime=agent_runtime,
        frontend_clients=frontend_clients,
        frontend_watched_agents=frontend_watched_agents,
        create_process_monitoring_handler=_get_process_monitoring_handler,
        agent_command_handler=agent_command_handler,
        forward_frontend_event=_forward_frontend_event,
        reject_frontend_command=_reject_frontend_command,
        websocket_has_minimum_role=websocket_has_minimum_role,
        logger=logger,
    )


def _build_agent_session_dependencies() -> AgentSessionDependencies:
    return AgentSessionDependencies(
        create_lifecycle_handler=_get_agent_lifecycle_handler,
        task_network_handler=task_network_handler,
        create_process_monitoring_handler=_get_process_monitoring_handler,
        set_window_tracking=_set_agent_window_tracking,
        broadcast_task_event=broadcast_task_event,
        broadcast_process_screenshot=broadcast_process_screenshot,
        run_frontend_ws_session=lambda ws, payload: run_frontend_ws_session(ws, payload, _build_frontend_session_dependencies()),
        frontend_snapshot_event=frontend_snapshot_event,
        logger=logger,
    )


def _extract_bearer_token(header_value: str | None) -> str | None:
    if not header_value:
        return None
    prefix = "bearer "
    if header_value.lower().startswith(prefix):
        return header_value[len(prefix):].strip()
    return None


def _extract_access_token_from_scope(scope: dict[str, object]) -> str | None:
    headers = scope.get("headers") or []
    if isinstance(headers, list):
        for raw_name, raw_value in headers:
            if raw_name.decode("latin-1").lower() == "authorization":
                return _extract_bearer_token(raw_value.decode("latin-1"))

    query_string = scope.get("query_string", b"")
    if isinstance(query_string, bytes):
        raw_query = query_string.decode("utf-8")
        for pair in raw_query.split("&"):
            if not pair or "=" not in pair:
                continue
            key, value = pair.split("=", 1)
            if key in {"access_token", "app_access_token"} and value:
                return value
    return None


def _mask_debug_token(value: str | None) -> str:
    clean_value = (value or "").strip()
    if not clean_value:
        return "<none>"
    if len(clean_value) <= 12:
        return clean_value
    return f"{clean_value[:6]}...{clean_value[-6:]}"


def _describe_guacamole_websocket_query(raw_query: str) -> dict[str, object]:
    parsed_query = parse_qs(raw_query, keep_blank_values=True)
    token_values = parsed_query.get("token") or parsed_query.get("authToken") or []
    return {
        "token": _mask_debug_token(token_values[0] if token_values else ""),
        "data_source": ((parsed_query.get("GUAC_DATA_SOURCE") or [""])[0] or "<none>"),
        "connection_id": ((parsed_query.get("GUAC_ID") or [""])[0] or "<none>"),
        "has_resume_tunnel": bool(((parsed_query.get("GUAC_RESUME_TUNNEL") or [""])[0] or "").strip()),
    }


async def _reject_frontend_command(ws: WebSocket, minimum_role: str, event_type: str) -> None:
    await ws.send_json({
        "kind": "command_rejected",
        "event_type": event_type,
        "error": f"{minimum_role.capitalize()} role required",
    })


def _is_public_user_api_path(path: str) -> bool:
    return path in {
        "/api/users/auth-config",
        "/api/users/login/local",
        "/api/users/login/microsoft",
        "/api/users/callback/microsoft",
        "/api/guacamole/tunnel",
    }


@app.middleware("http")
async def user_auth_middleware(request: Request, call_next):
    request.state.user_session = None
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api") or _is_public_user_api_path(path):
        return await call_next(request)

    access_token = _extract_bearer_token(request.headers.get("authorization"))
    if not access_token:
        access_token = request.query_params.get("access_token") or request.query_params.get("app_access_token")

    session = user_service.get_session(access_token)
    if session is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    request.state.user_session = session
    return await call_next(request)

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    auth_token = _extract_bearer_token(ws.headers.get("authorization"))
    await ws.accept()
    await ws.send_text('{"type":"handshake","data":{"client_id":"server","capabilities":["ws"]}}')
    await run_agent_ws_session(ws, auth_token, _build_agent_session_dependencies())


@app.websocket("/frontend")
async def frontend_ws(ws: WebSocket):
    await ws.accept()

    try:
        auth_message = await ws.receive_text()
        auth_payload = json.loads(auth_message)
    except WebSocketDisconnect:
        return
    except Exception:
        await ws.close(code=4401, reason="authentication required")
        return

    if not isinstance(auth_payload, dict) or auth_payload.get("type") != "auth":
        await ws.close(code=4401, reason="authentication required")
        return

    await run_frontend_ws_session(ws, auth_payload, _build_frontend_session_dependencies())

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
    return await _get_process_monitoring_handler().set_agent_window_tracking(agent_id, enabled)


async def _add_process_manager_watcher(ws: WebSocket, agent_id: str):
    await _get_process_monitoring_handler().add_watcher(ws, agent_id)


async def _remove_process_manager_watcher(ws: WebSocket, agent_id: str):
    await _get_process_monitoring_handler().remove_watcher(ws, agent_id)


async def _remove_all_process_manager_watchers(ws: WebSocket):
    await _get_process_monitoring_handler().remove_all_watchers(ws)

# --- REST API for historical data ---

@app.get("/api/metrics")
async def api_metrics(
    agent_id: str,
    request: Request,
    pid: int = None,
    from_ts: int = None,
    to_ts: int = None,
    limit: int = Query(default=50000, le=100000)
):
    if not request_has_minimum_role(request, "viewer"):
        return role_required_response("viewer")
    rows = await telemetry_db.get_metrics(agent_id, pid, from_ts, to_ts, limit)
    return JSONResponse(rows)


@app.get("/api/events")
async def api_events(
    request: Request,
    agent_id: str = None,
    event_type: str = None,
    from_ts: int = None,
    to_ts: int = None,
    limit: int = Query(default=200, le=5000)
):
    if not request_has_minimum_role(request, "viewer"):
        return role_required_response("viewer")
    rows = await telemetry_db.get_events(agent_id, event_type, from_ts, to_ts, limit)
    return JSONResponse(rows)


@app.get("/api/agents/summary")
async def api_agents_summary(request: Request):
    if not request_has_minimum_role(request, "viewer"):
        return role_required_response("viewer")
    rows = await telemetry_db.get_agents_summary()
    return JSONResponse(rows)


@app.get("/api/agents/{agent_id}")
async def api_agent_state(agent_id: str, request: Request):
    if not request_has_minimum_role(request, "viewer"):
        return role_required_response("viewer")
    state = agent_runtime.get_agent_state(agent_id)
    if state is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(state)


@app.get("/api/agent-registry")
async def api_agent_registry(request: Request, limit: int = Query(default=200, le=500)):
    if not request_has_minimum_role(request, "viewer"):
        return role_required_response("viewer")
    return JSONResponse(await registry_db.get_agents(limit))


@app.get("/api/agent-registry/{agent_id}")
async def api_agent_registry_item(agent_id: str, request: Request):
    if not request_has_minimum_role(request, "viewer"):
        return role_required_response("viewer")
    item = await registry_db.get_agent(agent_id)
    if not item:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(item)


@app.patch("/api/agent-registry/{agent_id}")
async def api_update_agent_registry_item(agent_id: str, body: AgentRegistryUpdateRequest, request: Request):
    if not request_has_minimum_role(request, "admin"):
        return role_required_response("admin")

    existing = await registry_db.get_agent(agent_id)
    if not existing:
        return JSONResponse({"error": "Not found"}, status_code=404)

    hostname = body.hostname.strip() if isinstance(body.hostname, str) else ""
    display_name = body.display_name.strip() if isinstance(body.display_name, str) else ""
    metadata = None
    if body.guacamole_access is not None:
        metadata = {
            "guacamole": {
                "access": body.guacamole_access.model_dump(mode="python", exclude_none=True),
            },
        }

    await registry_db.upsert_agent(agent_id, hostname=hostname, display_name=display_name, metadata=metadata)
    updated = await registry_db.get_agent(agent_id)

    if updated:
        updated_metadata = updated.get("metadata") if isinstance(updated.get("metadata"), dict) else {}
        guacamole_mapping = updated_metadata.get("guacamole") if isinstance(updated_metadata.get("guacamole"), dict) else {}
        if guacamole_mapping:
            provision_hostname = str(updated.get("hostname") or guacamole_mapping.get("target_host") or agent_id).strip() or agent_id
            try:
                refreshed_mapping, _ = await asyncio.to_thread(
                    provision_guacamole_agent_target_with_diagnostics,
                    agent_id,
                    provision_hostname,
                    guacamole_mapping,
                )
                await registry_db.upsert_agent(agent_id, metadata={"guacamole": refreshed_mapping})
                updated = await registry_db.get_agent(agent_id)
            except Exception as error:
                logger.warning("Failed to reprovision Guacamole connection for agent %s after registry update: %s", agent_id, error)

    return JSONResponse(updated or {"id": agent_id})


@app.delete("/api/agent-registry/{agent_id}")
async def api_delete_agent_registry_item(agent_id: str, request: Request):
    if not request_has_minimum_role(request, "admin"):
        return role_required_response("admin")

    existing = await registry_db.get_agent(agent_id)
    if not existing:
        return JSONResponse({"error": "Not found"}, status_code=404)

    await agent_runtime.timeout_agent(agent_id)
    agent_runtime.remove_agent(agent_id)
    await registry_db.delete_agent(agent_id)
    frontend_snapshot_event.set()
    return JSONResponse({"deleted": True, "agent_id": agent_id})


@app.post("/api/agent-registry/{agent_id}/rotate-token", response_model=AgentTokenRotationResponse)
async def api_rotate_agent_token(agent_id: str, request: Request):
    if not request_has_minimum_role(request, "admin"):
        return role_required_response("admin")
    rotated = await registry_db.rotate_agent_token_version(agent_id)
    if not rotated:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"ok": True, **rotated}


def _resolve_agent_ws_url(request: Request) -> str:
    override = os.getenv("VM_AGENT_SERVER_WS_URL")
    if override:
        return override

    public_base_url = os.getenv("VM_AGENT_SERVER_PUBLIC_URL", "").strip().rstrip("/")
    if public_base_url:
        parsed = urlsplit(public_base_url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            ws_scheme = "wss" if parsed.scheme == "https" else "ws"
            return urlunsplit((ws_scheme, parsed.netloc, "/ws", "", ""))

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
            return remainder.split(":", 1)[0].strip()

    return ""


def _extract_guacamole_cookie_header(headers: any) -> str:
    raw_cookie_headers: list[str] = []
    get_all = getattr(headers, "get_all", None)
    if callable(get_all):
        raw_cookie_headers = get_all("Set-Cookie") or []

    if not raw_cookie_headers:
        single_cookie = headers.get("Set-Cookie")
        if single_cookie:
            raw_cookie_headers = [single_cookie]

    if not raw_cookie_headers:
        return ""

    cookie = SimpleCookie()
    for raw_cookie in raw_cookie_headers:
        try:
            cookie.load(raw_cookie)
        except Exception:
            continue

    return "; ".join(f"{morsel.key}={morsel.value}" for morsel in cookie.values())


def _proxy_guacamole_tunnel_request(method: str, raw_query: str, body: bytes, headers: dict[str, str]) -> Response:
    return guacamole_service.proxy_tunnel_request(method, raw_query, body, headers)


app.include_router(build_task_router(task_service, task_db, _send_to_agent))
app.include_router(build_deployment_router(deployment_service, registry_db, _resolve_agent_ws_url))
app.include_router(build_users_router(server_settings_service, user_service, _resolve_public_base_url))
app.include_router(build_settings_router(server_settings_service, user_service))
app.include_router(
    build_guacamole_router(
        agent_runtime.get_agent_state,
        registry_db.get_agent,
        _resolve_public_base_url,
        guacamole_service,
        user_service,
    )
)


@app.websocket("/api/guacamole/websocket-tunnel")
async def api_guacamole_websocket_tunnel(ws: WebSocket):
    upstream_base = _get_guacamole_websocket_tunnel_url()
    if not upstream_base:
        await ws.close(code=1011, reason="Guacamole bridge is not configured")
        return

    raw_query = ws.scope.get("query_string", b"").decode("utf-8")
    upstream_url = f"{upstream_base}?{raw_query}" if raw_query else upstream_base
    query_details = _describe_guacamole_websocket_query(raw_query)

    await ws.accept(subprotocol="guacamole")
    tracked_auth_token = await guacamole_service.register_websocket(raw_query, ws)
    logger.info("Guacamole websocket proxy accepted: %s", query_details)

    try:
        async with websocket_connect(
            upstream_url,
            max_size=None,
            subprotocols=["guacamole"],
            compression=None,
            ping_interval=None,
            ping_timeout=None,
        ) as upstream:
            guacamole_service.set_websocket_proxy_supported(True)
            logger.info("Guacamole websocket upstream connected: %s", query_details)

            async def client_to_upstream():
                try:
                    while True:
                        message = await ws.receive()
                        if message.get("type") == "websocket.disconnect":
                            logger.info("Guacamole websocket browser disconnected: %s", query_details)
                            return "browser-disconnected"
                        guacamole_service.touch_websocket(raw_query)
                        if message.get("text") is not None:
                            await upstream.send(message["text"])
                        elif message.get("bytes") is not None:
                            await upstream.send(message["bytes"])
                except WebSocketDisconnect:
                    logger.info("Guacamole websocket proxy client disconnected before tunnel completed: %s", query_details)
                    return "browser-disconnected"
                except ConnectionClosed as error:
                    logger.warning(
                        "Guacamole websocket upstream closed while receiving browser data: sent=%s received=%s details=%s",
                        getattr(error, "sent", None),
                        getattr(error, "rcvd", None),
                        query_details,
                    )
                    return "upstream-closed"

            async def upstream_to_client():
                try:
                    while True:
                        payload = await upstream.recv()
                        guacamole_service.touch_websocket(raw_query)
                        if isinstance(payload, bytes):
                            await ws.send_bytes(payload)
                        else:
                            await ws.send_text(payload)
                except ConnectionClosed as error:
                    logger.warning(
                        "Guacamole websocket upstream closed: sent=%s received=%s details=%s",
                        getattr(error, "sent", None),
                        getattr(error, "rcvd", None),
                        query_details,
                    )
                    return "upstream-closed"
                except RuntimeError as error:
                    logger.info("Guacamole websocket browser socket closed during upstream send: %s details=%s", error, query_details)
                    return "browser-closed"

            client_task = asyncio.create_task(client_to_upstream())
            upstream_task = asyncio.create_task(upstream_to_client())
            done, pending = await asyncio.wait(
                {client_task, upstream_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

            for task in done:
                task.result()

            try:
                await upstream.close()
            except Exception:
                pass

            try:
                await ws.close()
            except RuntimeError:
                pass
    except WebSocketDisconnect:
        logger.info("Guacamole websocket proxy client disconnected before tunnel completed: %s", query_details)
        return
    except InvalidStatus as error:
        if getattr(error, "response", None) is not None and getattr(error.response, "status_code", None) == 404:
            guacamole_service.set_websocket_proxy_supported(False)
            logger.warning("Guacamole websocket upstream unavailable (404): %s", query_details)
            try:
                await ws.close(code=1000, reason="Guacamole websocket tunnel unavailable")
            except RuntimeError:
                pass
            return
        logger.warning("Guacamole websocket tunnel proxy failed: %s details=%s", error, query_details)
        try:
            await ws.close(code=1011, reason="Guacamole websocket tunnel failed")
        except RuntimeError:
            pass
    except Exception as error:
        logger.warning("Guacamole websocket tunnel proxy failed: %s details=%s", error, query_details)
        try:
            await ws.close(code=1011, reason="Guacamole websocket tunnel failed")
        except RuntimeError:
            pass
    finally:
        await guacamole_service.unregister_websocket(tracked_auth_token, ws)
if __name__ == "__main__":
    #disable_rdp_publisher_warning()
    #add_trusted_rdp_host("DESKTOP-JJULF7D")
    uvicorn.run(
        "vm_agent_server.src.server:app",
        host="0.0.0.0",
        port=8765,
        reload=False,
        timeout_keep_alive=1,
        timeout_graceful_shutdown=2,
    )