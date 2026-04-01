from __future__ import annotations

import logging

from shared.network.events import discover, parse

from vm_agent.src.network.context import AgentSessionContext
from vm_agent.src.network.event_router import EventRouter


class AgentSession:
    def __init__(self, router: EventRouter, *, logger: logging.Logger | None = None):
        self._router = router
        self._logger = logger or logging.getLogger(__name__)
        discover()

    async def process(self, raw_event: str | bytes, context: AgentSessionContext) -> bool:
        event = parse(raw_event)
        self._logger.debug("Processing event: %s", event)

        handled = await self._router.dispatch(event, context)
        if not handled:
            self._logger.warning("Unhandled event type: %s", event.type)
        return handled