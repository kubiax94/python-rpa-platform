from __future__ import annotations

from typing import Protocol, TypeVar

from shared.protocol.network_event import NetworkEvent


ContextT = TypeVar("ContextT")


class NetworkDomainHandler(Protocol[ContextT]):
    event_types: tuple[str, ...] | set[str]

    async def handle(self, event: NetworkEvent, context: ContextT) -> bool:
        ...