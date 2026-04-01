import logging

from shared.core.event_handler import EventHandler
from shared.network.events.example_event import CreateSessionData, StartProgramData
from shared.protocol.network_event import NetworkEvent

from vm_agent.src.network.context import AgentSessionContext
from vm_agent.src.network.payload_utils import coerce_event_data


class AgentCommandHandler(EventHandler):
    event_types = (
        "start_program",
        "start_monitored_process",
        "create_session",
    )

    def __init__(self, bus, prefix="event."):
        super().__init__(bus, prefix)

    def handle_event(self, event: NetworkEvent, context: AgentSessionContext):
        match event.type:
            case "start_program":
                logging.info(f"Start program event received: {event.data}")
                self._bus.emit(event.type, coerce_event_data(event.data, StartProgramData))
            case "start_monitored_process":
                logging.info(f"Start monitored process event received: {event.data}")
                self._bus.emit(event.type, coerce_event_data(event.data, StartProgramData))
            case "create_session":
                logging.info(f"Create session event received: {event.data}")
                self._bus.emit(event.type, coerce_event_data(event.data, CreateSessionData))
            case _:
                logging.warning(f"Unhandled command event type: {event.type}")