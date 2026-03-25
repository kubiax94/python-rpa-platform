from typing import Protocol

from shared.protocol.abstract_event import AbstractEvent 

class IProcesable(Protocol):
    async def process(self, event: "AbstractEvent") -> None:
        ...