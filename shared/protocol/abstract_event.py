from datetime import datetime, timezone
from typing import Any, Dict, Protocol, Callable
from collections.abc import Callable
import uuid
from pydantic import BaseModel, Field, ConfigDict
from pyee import EventEmitter


class IListenerRegister(Protocol):
    def register_listener(self, bus: EventEmitter) -> None:
        ...

class AbstractEvent(BaseModel):
    type: str
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    model_config = ConfigDict(extra="ignore")

    def register_listener(self, bus: EventEmitter, callback: Callable[[Any], None], once: bool = True) -> None:
        if once:
            bus.once(self.type, callback)
        else:
            bus.on(self.type, callback)