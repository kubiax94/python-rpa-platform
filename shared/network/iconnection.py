from typing import Protocol, Callable, Any
import pyee # only for typing


class IConnection(Protocol):
    async def open(self, bus: pyee.EventEmitter ):
        raise NotImplementedError
    
    async def close(self):
        raise NotImplementedError
    
    async def send_event(self):
        raise NotImplementedError
    
    def on(self, event: str, handler: Callable[..., Any]) -> None:
        raise NotImplementedError
    
    def once(self, event: str, handler: Callable[..., Any]) -> None:
        raise NotImplementedError