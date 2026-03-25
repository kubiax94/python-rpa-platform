from typing import Protocol

from shared.network.iconnection import IConnection
from shared.protocol.network_event import NetworkEvent

class ISendableEvent(Protocol):
    async def send(self, client: IConnection, event: NetworkEvent) -> None:
        ...