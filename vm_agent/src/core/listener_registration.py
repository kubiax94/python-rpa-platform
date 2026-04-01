from __future__ import annotations

from typing import Any

from shared.protocol.abstract_event import AbstractEvent


def register_listener(event_cls: type[AbstractEvent], *, once: bool = False):
    def decorator(func):
        registrations = list(getattr(func, "__listener_registrations__", []))
        registrations.append({"event_cls": event_cls, "once": once})
        setattr(func, "__listener_registrations__", registrations)
        return func

    return decorator


def bind_registered_listeners(bus: Any, owner: Any) -> None:
    for attr_name in dir(owner):
        handler = getattr(owner, attr_name)
        registrations = getattr(handler, "__listener_registrations__", None)
        if not registrations:
            continue

        for registration in registrations:
            registration["event_cls"]().register_listener(
                bus,
                handler,
                once=registration["once"],
            )