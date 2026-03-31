from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket

from shared.protocol.network_event import NetworkEvent

if TYPE_CHECKING:
    from vm_agent_server.src.agents.command_handler import AgentCommandHandler
    from vm_agent_server.src.agents.lifecycle_handler import AgentLifecycleEventHandler
    from vm_agent_server.src.process_monitoring.network_handler import ProcessMonitoringNetworkHandler
    from vm_agent_server.src.tasks.network_handler import TaskNetworkHandler


@dataclass(slots=True)
class AgentConnectionState:
    client_id: str | None = None
    authenticated: bool = False


@dataclass(slots=True)
class AgentLifecycleContext:
    ws: WebSocket
    state: AgentConnectionState
    auth_token: str | None
    set_window_tracking: Callable[[str, bool], Awaitable[bool]]


@dataclass(slots=True)
class TaskEventContext:
    client_id: str | None
    broadcast_task_event: Callable[[str, dict], Awaitable[None]]


@dataclass(slots=True)
class ProcessScreenshotContext:
    client_id: str | None
    broadcast_process_screenshot: Callable[[dict], Awaitable[None]]


@dataclass(slots=True)
class AgentCommandContext:
    ws: WebSocket
    forward_frontend_event: Callable[[str, str, NetworkEvent], Awaitable[bool]]
    reject_frontend_command: Callable[[WebSocket, str, str], Awaitable[None]]
    websocket_has_minimum_role: Callable[[WebSocket, str], bool]


@dataclass(slots=True)
class AgentSessionDependencies:
    create_lifecycle_handler: Callable[[], "AgentLifecycleEventHandler"]
    task_network_handler: "TaskNetworkHandler"
    create_process_monitoring_handler: Callable[[], "ProcessMonitoringNetworkHandler"]
    set_window_tracking: Callable[[str, bool], Awaitable[bool]]
    broadcast_task_event: Callable[[str, dict], Awaitable[None]]
    broadcast_process_screenshot: Callable[[dict], Awaitable[None]]
    run_frontend_ws_session: Callable[[WebSocket, dict[str, object]], Awaitable[None]]
    frontend_snapshot_event: Any
    logger: logging.Logger


@dataclass(slots=True)
class FrontendSessionDependencies:
    user_service: Any
    agent_runtime: Any
    frontend_clients: set[WebSocket]
    frontend_watched_agents: dict[WebSocket, set[str]]
    create_process_monitoring_handler: Callable[[], "ProcessMonitoringNetworkHandler"]
    agent_command_handler: "AgentCommandHandler"
    forward_frontend_event: Callable[[str, str, NetworkEvent], Awaitable[bool]]
    reject_frontend_command: Callable[[WebSocket, str, str], Awaitable[None]]
    websocket_has_minimum_role: Callable[[WebSocket, str], bool]
    logger: logging.Logger