from __future__ import annotations

from collections.abc import Awaitable, Callable

from shared.protocol.network_event import NetworkEvent


HandlerFunc = Callable[[NetworkEvent], Awaitable[bool]]


class EventRouter:
    def __init__(self):
        self._handlers: dict[str, HandlerFunc] = {}

    def register(self, event_types: tuple[str, ...] | list[str] | set[str], handler: HandlerFunc) -> None:
        for event_type in event_types:
            self._handlers[event_type] = handler

    async def dispatch(self, event: NetworkEvent) -> bool:
        handler = self._handlers.get(event.type)
        if handler is None:
            return False
        return await handler(event)