import logging

from shared.core.event_handler import EventHandler
from shared.network.events.example_event import CaptureProcessScreenshotData, SetWindowTrackingData
from shared.protocol.network_event import NetworkEvent

from vm_agent.src.network.context import AgentSessionContext
from vm_agent.src.network.payload_utils import coerce_event_data


class ProcessMonitoringHandler(EventHandler):
    event_types = (
        "capture_process_screenshot",
        "set_window_tracking",
    )

    def __init__(self, bus, prefix="event."):
        super().__init__(bus, prefix)

    def handle_event(self, event: NetworkEvent, context: AgentSessionContext):
        match event.type:
            case "capture_process_screenshot":
                logging.info(f"Capture process screenshot event received: {event.data}")
                self._bus.emit(event.type, coerce_event_data(event.data, CaptureProcessScreenshotData))
            case "set_window_tracking":
                logging.info(f"Set window tracking event received: {event.data}")
                self._bus.emit(event.type, coerce_event_data(event.data, SetWindowTrackingData))
            case _:
                logging.warning(f"Unhandled process monitoring event type: {event.type}")