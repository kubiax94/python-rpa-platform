from __future__ import annotations

import logging

from fastapi import WebSocket, WebSocketDisconnect

from shared.network.events import parse as parse_network_event
from vm_agent_server.src.network.context import AgentCommandContext, FrontendSessionDependencies
from vm_agent_server.src.network.event_router import EventRouter


async def run_frontend_ws_session(ws: WebSocket, auth_payload: dict[str, object], deps: FrontendSessionDependencies) -> None:
    access_token = str(auth_payload.get("access_token") or "").strip()
    session = deps.user_service.get_session(access_token)
    if session is None:
        await ws.close(code=4401, reason="unauthorized")
        return

    ws.state.user_session = session
    await ws.send_json({"kind": "auth_ok"})
    deps.frontend_clients.add(ws)
    deps.frontend_watched_agents[ws] = set()
    if deps.agent_runtime.latest_stats:
        await ws.send_json({"kind": "agents_snapshot", "data": deps.agent_runtime.build_frontend_snapshot()})

    process_monitoring_handler = deps.create_process_monitoring_handler()
    agent_command_context = AgentCommandContext(
        ws=ws,
        forward_frontend_event=deps.forward_frontend_event,
        reject_frontend_command=deps.reject_frontend_command,
        websocket_has_minimum_role=deps.websocket_has_minimum_role,
    )
    router = EventRouter()
    router.register(
        tuple(deps.agent_command_handler.event_types),
        lambda event: deps.agent_command_handler.handle(event, agent_command_context),
    )
    router.register(
        tuple(process_monitoring_handler.frontend_event_types),
        lambda event: process_monitoring_handler.add_watcher(ws, event.data.agent_id)
        if event.type == "watch_process_manager"
        else process_monitoring_handler.remove_watcher(ws, event.data.agent_id),
    )

    try:
        while True:
            msg = await ws.receive_text()
            ev = parse_network_event(msg)
            await router.dispatch(ev)
    except WebSocketDisconnect:
        pass
    except Exception as error:
        deps.logger.exception("Frontend websocket error: %s", error)
    finally:
        await process_monitoring_handler.remove_all_watchers(ws)
        deps.frontend_watched_agents.pop(ws, None)
        deps.frontend_clients.discard(ws)