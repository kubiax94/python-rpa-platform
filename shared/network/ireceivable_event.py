from typing import Protocol

from shared.protocol.network_event import NetworkEvent

class IReceivableEvent(Protocol):
    def receive(self, data: str | bytes) -> "NetworkEvent":
        ...