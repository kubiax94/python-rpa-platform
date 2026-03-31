from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Any, Awaitable, Callable

from shared.protocol.network_event import NetworkEvent


Handler = Callable[[NetworkEvent, Any], Any]


class EventRouter:
    def __init__(self):
        self._handlers: dict[str, Handler] = {}

    def register(self, event_types: Iterable[str], handler: Handler) -> None:
        for event_type in event_types:
            self._handlers[event_type] = handler

    async def dispatch(self, event: NetworkEvent, context: Any) -> bool:
        handler = self._handlers.get(event.type)
        if handler is None:
            return False

        result = handler(event, context)
        if inspect.isawaitable(result):
            await result
        return True