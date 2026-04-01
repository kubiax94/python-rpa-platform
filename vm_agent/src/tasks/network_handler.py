import logging

from shared.core.event_handler import EventHandler
from shared.network.events.example_event import CancelTaskData, ExecuteTaskData
from shared.protocol.network_event import NetworkEvent

from vm_agent.src.network.context import AgentSessionContext
from vm_agent.src.network.payload_utils import coerce_event_data


class AgentTaskHandler(EventHandler):
    event_types = (
        "execute_task",
        "cancel_task",
    )

    def __init__(self, bus, prefix="event."):
        super().__init__(bus, prefix)

    def handle_event(self, event: NetworkEvent, context: AgentSessionContext):
        match event.type:
            case "execute_task":
                logging.info(f"Execute task event received: {event.data}")
                self._bus.emit(event.type, coerce_event_data(event.data, ExecuteTaskData))
            case "cancel_task":
                logging.info(f"Cancel task event received: {event.data}")
                self._bus.emit(event.type, coerce_event_data(event.data, CancelTaskData))
            case _:
                logging.warning(f"Unhandled task event type: {event.type}")