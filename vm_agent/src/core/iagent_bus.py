from typing import Protocol

from shared.protocol.abstract_event import AbstractEvent

class IAgentBus(Protocol):
    """
    Interface for the agent's event bus.
    Components implementing this interface can emit and listen to events.
    """

    def emit_event(self, event: AbstractEvent) -> None:
        """
        Emit an event to all registered listeners.

        Args:
            event: Name of the event to emit.
            *args: Positional arguments to pass to event listeners.
            **kwargs: Keyword arguments to pass to event listeners.
        """
        ...

    def on(self, event: str, listener) -> None:
        """
        Register a listener for a specific event.

        Args:
            event: Name of the event to listen for.
            listener: Callable to be invoked when the event is emitted.
        """
        ...