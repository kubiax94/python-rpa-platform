from __future__ import annotations
import importlib
import pkgutil
import json
from typing import Any, Dict, Type, Optional, Union

from pydantic import BaseModel
from shared.protocol.network_event import NetworkEvent
from shared.protocol.abstract_event import AbstractEvent

REGISTRY: Dict[str, Type[NetworkEvent]] = {}

def register_event(type_name: Optional[str] = None):
    def _decorator(cls: Type[NetworkEvent]):
        t = type_name or getattr(cls, "type", None)
        if not isinstance(t, str):
            raise ValueError(f"{cls.__name__} must define 'type' or pass type_name")
        REGISTRY[t] = cls
        return cls
    return _decorator

def discover(package: str = __name__) -> Dict[str, Type[NetworkEvent]]:
    pkg = importlib.import_module(package)
    for _, mod_name, _ in pkgutil.iter_modules(pkg.__path__, package + "."):
        importlib.import_module(mod_name)  # import wywoła dekoratory
    return REGISTRY

def get_registry() -> Dict[str, Type[NetworkEvent]]:
    return REGISTRY

JsonLike = Union[str, bytes, Dict[str, Any], AbstractEvent]

def parse(incoming: JsonLike) -> NetworkEvent:
    if isinstance(incoming, (str, bytes)):
        raw = json.loads(incoming)
    elif isinstance(incoming, AbstractEvent):
        raw = incoming.model_dump()
    elif isinstance(incoming, dict):
        raw = incoming
    else:
        raise TypeError(f"Unsupported event input: {type(incoming)}")

    evt_type = raw.get("type")
    cls = REGISTRY.get(evt_type, NetworkEvent)
    if issubclass(cls, BaseModel):
        return cls.model_validate(raw)  # Pydantic v2
    return cls(**raw)  # type: ignore