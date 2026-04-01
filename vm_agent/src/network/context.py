from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from shared.network.iconnection import IConnection
from shared.protocol.network_event import NetworkEvent


@dataclass(slots=True)
class AgentSessionContext:
    connection: IConnection
    client_id: str
    initialized: bool
    send_event: Callable[[NetworkEvent], None]
    set_initialized: Callable[[bool], None]