from __future__ import annotations

import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

from shared.network.events import parse as parse_network_event
from vm_agent_server.src.agents.lifecycle_handler import AgentLifecycleEventHandler
from vm_agent_server.src.network.context import AgentConnectionState, AgentLifecycleContext, AgentSessionDependencies, ProcessScreenshotContext, TaskEventContext
from vm_agent_server.src.network.event_router import EventRouter


async def run_agent_ws_session(ws: WebSocket, auth_token: str | None, deps: AgentSessionDependencies) -> None:
    state = AgentConnectionState()
    lifecycle_handler = deps.create_lifecycle_handler()
    process_monitoring_handler = deps.create_process_monitoring_handler()
    lifecycle_context = AgentLifecycleContext(
        ws=ws,
        state=state,
        auth_token=auth_token,
        set_window_tracking=deps.set_window_tracking,
    )

    router = EventRouter()
    router.register(
        tuple(lifecycle_handler.event_types),
        lambda event: lifecycle_handler.handle(event, lifecycle_context),
    )
    router.register(
        tuple(deps.task_network_handler.event_types),
        lambda event: deps.task_network_handler.handle(
            event,
            TaskEventContext(
                client_id=state.client_id,
                broadcast_task_event=deps.broadcast_task_event,
            ),
        ),
    )
    router.register(
        tuple(process_monitoring_handler.agent_event_types),
        lambda event: process_monitoring_handler.handle(
            event,
            ProcessScreenshotContext(
                client_id=state.client_id,
                broadcast_process_screenshot=deps.broadcast_process_screenshot,
            ),
        ),
    )

    try:
        while True:
            msg = await ws.receive_text()
            try:
                try:
                    raw_payload = json.loads(msg)
                except Exception:
                    raw_payload = None

                if isinstance(raw_payload, dict) and raw_payload.get("type") == "auth" and raw_payload.get("access_token"):
                    deps.logger.info("Treating /ws auth frame as frontend websocket compatibility fallback")
                    await deps.run_frontend_ws_session(ws, raw_payload)
                    return

                ev = parse_network_event(msg)
                if ev.type != "handshake" and not state.authenticated:
                    await ws.close(code=4401, reason="handshake required")
                    return

                handled = await router.dispatch(ev)
                if ev.type in lifecycle_handler.event_types and not handled:
                    return
            except Exception as error:
                deps.logger.exception("Error processing agent message: %s", error)

    except WebSocketDisconnect:
        deps.logger.info("Agent websocket disconnected: %s", state.client_id)
    except Exception as error:
        deps.logger.exception("Agent websocket error: %s", error)
    finally:
        if await lifecycle_handler.cleanup_connection(lifecycle_context):
            deps.frontend_snapshot_event.set()