"""
Interface for components that can register event listeners.
Components implementing this interface will automatically receive
access to the event bus when registered with LifecycleManager.
"""

from typing import Protocol
from pyee.base import EventEmitter


class IEventAware(Protocol):
    """
    Component that can register and handle events from the global event bus.
    
    Event naming convention:
    - server.*   - Events received from server (e.g., server.login_request)
    - session.*  - Session lifecycle events (e.g., session.created, session.closed)
    - process.*  - Process lifecycle events (e.g., process.started, process.terminated)
    - client.*   - Events to be sent to server (e.g., client.status_update)
    """
    
    def register_events(self, bus: EventEmitter) -> None:
        """
        Register all event listeners for this component.
        Called automatically by LifecycleManager when component is registered.
        
        Args:
            bus: Global event bus (EventEmitter instance)
        
        Example:
            def register_events(self, bus: EventEmitter) -> None:
                self._bus = bus
                bus.on("server.login_request", self._handle_login)
                bus.on("session.logout_request", self._handle_logout)
        """
        ...