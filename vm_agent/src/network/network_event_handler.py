
import logging
from pydantic import BaseModel
from shared.core.event_handler import EventHandler
from shared.network.events.example_event import AuthResultData, CancelTaskData, CaptureProcessScreenshotData, CreateSessionData, ExecuteTaskData, HandshakeData, SetWindowTrackingData, StartProgramData
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

    def _coerce_data(self, data, model_type):
        if isinstance(data, model_type):
            return data
        if isinstance(data, BaseModel):
            return model_type.model_validate(data.model_dump())
        return model_type.model_validate(data)

    def handle_event(self, event: NetworkEvent, connection: IConnection):
        match(event.type):

            case "handshake":
                self._bus.emit(event.type, self._coerce_data(event.data, HandshakeData))

            case "auth_result":
                logging.info(f"Auth result event received: {event.data}")
                self._bus.emit(event.type, self._coerce_data(event.data, AuthResultData))

            case "start_program":
                logging.info(f"Start program event received: {event.data}")
                self._bus.emit(event.type, self._coerce_data(event.data, StartProgramData))

            case "start_monitored_process":
                logging.info(f"Start monitored process event received: {event.data}")
                self._bus.emit(event.type, self._coerce_data(event.data, StartProgramData))

            case "create_session":
                logging.info(f"Create session event received: {event.data}")
                self._bus.emit(event.type, self._coerce_data(event.data, CreateSessionData))

            case "execute_task":
                logging.info(f"Execute task event received: {event.data}")
                self._bus.emit(event.type, self._coerce_data(event.data, ExecuteTaskData))

            case "cancel_task":
                logging.info(f"Cancel task event received: {event.data}")
                self._bus.emit(event.type, self._coerce_data(event.data, CancelTaskData))

            case "capture_process_screenshot":
                logging.info(f"Capture process screenshot event received: {event.data}")
                self._bus.emit(event.type, self._coerce_data(event.data, CaptureProcessScreenshotData))

            case "set_window_tracking":
                logging.info(f"Set window tracking event received: {event.data}")
                self._bus.emit(event.type, self._coerce_data(event.data, SetWindowTrackingData))

            case _:
                logging.warning(f"Unhandled event type: {event.type}")
        
    def _handle_handshake(self, event: NetworkEvent, connection: IConnection):
        handshake_data = self._coerce_data(event.data, HandshakeData)
        logging.info(f"Handling handshake for client ID: {handshake_data.client_id}")
        # Further processing logic here