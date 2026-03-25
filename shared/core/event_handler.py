from __future__ import annotations
import asyncio
import logging
from typing import Any, Callable, Dict, Optional, Type, Awaitable

from pyee.base import EventEmitter

from shared.protocol.abstract_event import AbstractEvent

try:
    from pydantic import BaseModel, ValidationError  # opcjonalnie
except ImportError:
    BaseModel = object
    class ValidationError(Exception): ...

from shared.network.iconnection import IConnection
from shared.protocol.network_event import NetworkEvent


# Base handler for AbstractEvent, from this we could create separated 
# handler for server and agent to proper handle event flow beetwen them.
class EventHandler:
    def __init__(self, bus: Any, prefix: str = "event."):
        self._bus: EventEmitter = bus
        self._prefix = prefix

    def parser(self, raw_data: str | bytes):
       return AbstractEvent.model_validate_json(raw_data)

    def handle_event(self, event: AbstractEvent, client: IConnection):
        match event.type:
            case "handshake":
                print("Handling handshake event")
                self._bus.emit("handshake", event)
            case _:
                print(f"Unhandled event type: {event.type}")
