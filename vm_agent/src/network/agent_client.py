import asyncio
import logging
from uuid import uuid4
from pyee import EventEmitter
from websockets import ConnectionClosedError
from shared.core.event_handler import EventHandler
from shared.core.iprocesable import IProcesable
from shared.network.events.example_event import HandshakeData, HandshakeEvent
from shared.protocol.network_event import NetworkEvent
from shared.protocol.session import Session
from vm_agent.src.core.ievent_aware import IEventAware
from vm_agent.src.network.agent_connection import AgentConnection, AgentConnectionStatus
from vm_agent.src.network.network_event_handler import NetworkEventHandler


class AgentClient(IProcesable, IEventAware):
    
    def __init__(self):
        self.init = False
        self._connection: AgentConnection = None
        self._session: Session = None
        self._handler: EventHandler = None
        self.client_id: str = uuid4().hex
        self._connection_manager_task: asyncio.Task = None


    def start(self, bus: EventEmitter, config):
        if self._connection_manager_task and not self._connection_manager_task.done():
            logging.warning("AgentClient.start() called while connection manager is already running")
            return

        self._connection = AgentConnection(config=config)
        self._handler = NetworkEventHandler(bus)

        self._connection_manager_task = asyncio.create_task(self.connection_manager(self._connection, self, bus))

    async def connection_manager(self, agent_connection, client, bus):
        handshake_registered = False
        while True:
            try:
                await agent_connection.open(client)

                if not handshake_registered:
                    bus.once("handshake", client._handshake_handler)
                    handshake_registered = True

                await agent_connection._read_loop_task
                handshake_registered = False
            except Exception as e:
                logging.error(f"Connection manager error: {e}")
                await asyncio.sleep(agent_connection._retry_delay)

    def send_event(self, event: NetworkEvent):
        """
        Synchronous wrapper - schedules async send.
        Called from sync context (event handlers).
        """
        ev_parsed = event.model_dump_json()
        logging.debug(f"Scheduling event send: {ev_parsed}")
        
        if not self._connection or self._connection.get_status() != AgentConnectionStatus.CONNECTED:
            logging.error("Cannot send event, connection is not established")
            return
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._connection.send(ev_parsed))
            logging.debug(f"Event send task created: {task}")

        except RuntimeError as e:
            logging.error(f"No running event loop: {e}")

    def _handshake_handler(self, eventData: HandshakeEvent):
        logging.info(f"Handshake received: {eventData}")
        self.init = True
        self.send_event(HandshakeEvent(data=HandshakeData(
            client_id=self.client_id,
            capabilities=["ws"]
        )))

    async def process(self, event):
        ev = self._handler.parser(event)
        logging.debug(f"Processing: {ev}")
        
        self._handler.handle_event(ev, self._connection)

