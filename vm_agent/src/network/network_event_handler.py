
import logging
from shared.core.event_handler import EventHandler
from shared.network.events.example_event import AuthResultData, CancelTaskData, CaptureProcessScreenshotData, CreateSessionData, CreateSessionEvent, ExecuteTaskData, HandshakeData, SetWindowTrackingData, StartProgramData
from shared.network.iconnection import IConnection
from shared.protocol.network_event import NetworkEvent

logging.basicConfig(
    filename=r"C:\VmAgent\agent.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

class NetworkEventHandler(EventHandler):
    event_types = (
        "handshake",
        "auth_result",
        "start_program",
        "start_monitored_process",
        "create_session",
        "execute_task",
        "cancel_task",
        "capture_process_screenshot",
        "set_window_tracking",
    )

    def __init__(self, bus, prefix = "event."):
        super().__init__(bus, prefix)

    def handle_event(self, event: NetworkEvent, connection: IConnection):
        match(event.type):

            case "handshake":
                self._bus.emit(event.type, HandshakeData(**event.data))

            case "auth_result":
                logging.info(f"Auth result event received: {event.data}")
                self._bus.emit(event.type, AuthResultData(**event.data))

            case "start_program":
                logging.info(f"Start program event received: {event.data}")
                self._bus.emit(event.type, StartProgramData(**event.data))

            case "start_monitored_process":
                logging.info(f"Start monitored process event received: {event.data}")
                self._bus.emit(event.type, StartProgramData(**event.data))

            case "create_session":
                logging.info(f"Create session event received: {event.data}")
                self._bus.emit(event.type, CreateSessionData(**event.data))

            case "execute_task":
                logging.info(f"Execute task event received: {event.data}")
                self._bus.emit(event.type, ExecuteTaskData(**event.data))

            case "cancel_task":
                logging.info(f"Cancel task event received: {event.data}")
                self._bus.emit(event.type, CancelTaskData(**event.data))

            case "capture_process_screenshot":
                logging.info(f"Capture process screenshot event received: {event.data}")
                self._bus.emit(event.type, CaptureProcessScreenshotData(**event.data))

            case "set_window_tracking":
                logging.info(f"Set window tracking event received: {event.data}")
                self._bus.emit(event.type, SetWindowTrackingData(**event.data))

            case _:
                logging.warning(f"Unhandled event type: {event.type}")
        
    def _handle_handshake(self, event: NetworkEvent, connection: IConnection):
        handshake_data = HandshakeData(**event.data)
        logging.info(f"Handling handshake for client ID: {handshake_data.client_id}")
        # Further processing logic here