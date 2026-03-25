
import json
import logging
from typing import override
from shared.core.event_handler import EventHandler
from shared.network.events.example_event import HandshakeData
from shared.network.iconnection import IConnection
from shared.protocol.network_event import NetworkEvent
from shared.network.events import REGISTRY

class NetworkEventHandler(EventHandler):
    def __init__(self, bus, prefix = "event."):
        super().__init__(bus, prefix)

    @override
    def parser(self, raw_data: str | bytes) -> NetworkEvent:
        if isinstance(raw_data, (bytes)):
            raw_data = raw_data.decode('utf-8')
        
        data_dict = json.loads(raw_data)
        eventype = data_dict.get("type")
        event_class = REGISTRY.get(eventype, NetworkEvent)

        if not issubclass(event_class, NetworkEvent):
            logging.error(f"Registered event {eventype} is not a NetworkEvent subclass.")
            return NetworkEvent.model_validate_json(raw_data)
        
        return event_class.model_validate_json(raw_data)
    
    @override
    def handle_event(self, event: NetworkEvent):
        if event.type == "handshake":
            self._bus.emit(event.type, event.data)
        else:
            logging.warning(f"Unhandled event type: {event.type}")

    def _handle_handshake(self, event: NetworkEvent):
        handshake_data = HandshakeData(**event.data)
        logging.debug(f"Handling handshake for client ID: {handshake_data.client_id}")
        