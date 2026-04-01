import logging
import os

from shared.core.event_handler import EventHandler
from shared.network.events.example_event import AuthResultData, HandshakeData, HandshakeEvent
from shared.protocol.network_event import NetworkEvent

from vm_agent.src.network.context import AgentSessionContext
from vm_agent.src.network.payload_utils import coerce_event_data


class AgentLifecycleHandler(EventHandler):
    event_types = (
        "handshake",
        "auth_result",
    )

    def __init__(self, bus, prefix="event."):
        super().__init__(bus, prefix)

    def handle_event(self, event: NetworkEvent, context: AgentSessionContext):
        match event.type:
            case "handshake":
                if context.initialized:
                    logging.info("Ignoring duplicate handshake for client %s", context.client_id)
                    return

                context.set_initialized(True)
                context.send_event(
                    HandshakeEvent(
                        data=HandshakeData(
                            client_id=context.client_id,
                            hostname=str(os.getenv("COMPUTERNAME") or ""),
                            capabilities=["ws"],
                        )
                    )
                )
            case "auth_result":
                logging.info(f"Auth result event received: {event.data}")
                self._bus.emit(event.type, coerce_event_data(event.data, AuthResultData))
            case _:
                logging.warning(f"Unhandled lifecycle event type: {event.type}")