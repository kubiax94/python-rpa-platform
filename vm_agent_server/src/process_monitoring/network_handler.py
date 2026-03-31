from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import WebSocket

from shared.network.events.example_event import ProcessScreenshotEvent, SetWindowTrackingData, SetWindowTrackingEvent
from shared.protocol.network_event import NetworkEvent
from vm_agent_server.src.network.context import ProcessScreenshotContext

logger = logging.getLogger(__name__)


class ProcessMonitoringNetworkHandler:
    agent_event_types = ("process_screenshot",)
    frontend_event_types = ("watch_process_manager", "unwatch_process_manager")

    def __init__(
        self,
        send_to_agent: Callable[[str, NetworkEvent], Awaitable[bool]],
        process_manager_watchers: dict[str, set[WebSocket]],
        frontend_watched_agents: dict[WebSocket, set[str]],
    ):
        self._send_to_agent = send_to_agent
        self._process_manager_watchers = process_manager_watchers
        self._frontend_watched_agents = frontend_watched_agents

    async def handle(
        self,
        event: NetworkEvent,
        context: ProcessScreenshotContext,
    ) -> bool:
        if not isinstance(event, ProcessScreenshotEvent):
            return False

        await context.broadcast_process_screenshot(
            {
                "type": "process_screenshot",
                "agent_id": event.data.agent_id or context.client_id or "",
                "target_type": event.data.target_type,
                "pid": event.data.pid,
                "hwnd": event.data.hwnd,
                "session_id": event.data.session_id,
                "request_id": event.data.request_id,
                "status": event.data.status,
                "image_base64": event.data.image_base64,
                "image_format": event.data.image_format,
                "window_title": event.data.window_title,
                "error": event.data.error,
                "captured_at": event.data.captured_at,
            }
        )
        return True

    async def set_agent_window_tracking(self, agent_id: str, enabled: bool) -> bool:
        event = SetWindowTrackingEvent(data=SetWindowTrackingData(agent_id=agent_id, enabled=enabled))
        sent = await self._send_to_agent(agent_id, event)
        if sent:
            logger.info("Forwarded set_window_tracking=%s to agent %s", enabled, agent_id)
        else:
            logger.warning("Failed to forward set_window_tracking=%s to agent %s", enabled, agent_id)
        return sent

    async def add_watcher(self, ws: WebSocket, agent_id: str) -> None:
        if not agent_id:
            return

        watched_agents = self._frontend_watched_agents.setdefault(ws, set())
        if agent_id in watched_agents:
            return

        watchers = self._process_manager_watchers.setdefault(agent_id, set())
        was_empty = len(watchers) == 0
        watchers.add(ws)
        watched_agents.add(agent_id)

        if was_empty:
            await self.set_agent_window_tracking(agent_id, True)

    async def remove_watcher(self, ws: WebSocket, agent_id: str) -> None:
        if not agent_id:
            return

        watched_agents = self._frontend_watched_agents.get(ws)
        if watched_agents is not None:
            watched_agents.discard(agent_id)

        watchers = self._process_manager_watchers.get(agent_id)
        if not watchers:
            return

        watchers.discard(ws)
        if len(watchers) == 0:
            self._process_manager_watchers.pop(agent_id, None)
            await self.set_agent_window_tracking(agent_id, False)

    async def remove_all_watchers(self, ws: WebSocket) -> None:
        for agent_id in list(self._frontend_watched_agents.get(ws, set())):
            await self.remove_watcher(ws, agent_id)