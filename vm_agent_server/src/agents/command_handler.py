from __future__ import annotations

from collections.abc import Awaitable, Callable

from shared.protocol.network_event import NetworkEvent
from vm_agent_server.src.network.context import AgentCommandContext


class AgentCommandHandler:
    _operator_event_types = {
        "start_program",
        "start_monitored_process",
        "create_session",
    }
    event_types = _operator_event_types | {"capture_process_screenshot"}

    def can_handle(self, event: NetworkEvent) -> bool:
        return event.type in self.event_types

    async def handle(
        self,
        event: NetworkEvent,
        context: AgentCommandContext,
    ) -> bool:
        if not self.can_handle(event):
            return False

        if event.type in self._operator_event_types and not context.websocket_has_minimum_role(context.ws, "operator"):
            await context.reject_frontend_command(context.ws, "operator", event.type)
            return True

        requested_agent_id = getattr(event.data, "agent_id", "")
        await context.forward_frontend_event(event.type, requested_agent_id, event)
        return True