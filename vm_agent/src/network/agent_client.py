import asyncio
import logging
from uuid import uuid4
from pyee import EventEmitter
from shared.core.iprocesable import IProcesable
from shared.network.events.example_event import HandshakeData, HandshakeEvent
from shared.protocol.network_event import NetworkEvent
from shared.protocol.session import Session
from vm_agent.src.agents.command_handler import AgentCommandHandler
from vm_agent.src.agents.lifecycle_handler import AgentLifecycleHandler
from vm_agent.src.core.ievent_aware import IEventAware
from vm_agent.src.network.context import AgentSessionContext
from vm_agent.src.network.agent_connection import AgentConnection, AgentConnectionStatus
from vm_agent.src.network.agent_session import AgentSession
from vm_agent.src.network.event_router import EventRouter
from vm_agent.src.process_monitoring.network_handler import ProcessMonitoringHandler
from vm_agent.src.tasks.network_handler import AgentTaskHandler


class AgentClient(IProcesable, IEventAware):
    
    def __init__(self):
        self.init = False
        self._connection: AgentConnection = None
        self._session: Session = None
        self._lifecycle_handler: AgentLifecycleHandler | None = None
        self._command_handler: AgentCommandHandler | None = None
        self._task_handler: AgentTaskHandler | None = None
        self._process_monitoring_handler: ProcessMonitoringHandler | None = None
        self._agent_session: AgentSession | None = None
        self.client_id: str = uuid4().hex
        self._connection_manager_task: asyncio.Task = None
        self._fatal_error_reason: str | None = None


    def start(self, bus: EventEmitter, config):
        if self._connection_manager_task and not self._connection_manager_task.done():
            logging.warning("AgentClient.start() called while connection manager is already running")
            return

        configured_client_id = config.get("client_id") if isinstance(config, dict) else None
        if configured_client_id:
            self.client_id = configured_client_id

        self._connection = AgentConnection(config=config)
        self._lifecycle_handler = AgentLifecycleHandler(bus)
        self._command_handler = AgentCommandHandler(bus)
        self._task_handler = AgentTaskHandler(bus)
        self._process_monitoring_handler = ProcessMonitoringHandler(bus)
        router = EventRouter()
        router.register(self._lifecycle_handler.event_types, self._lifecycle_handler.handle_event)
        router.register(self._command_handler.event_types, self._command_handler.handle_event)
        router.register(self._task_handler.event_types, self._task_handler.handle_event)
        router.register(self._process_monitoring_handler.event_types, self._process_monitoring_handler.handle_event)
        self._agent_session = AgentSession(router, logger=logging.getLogger(__name__))

        self._connection_manager_task = asyncio.create_task(self.connection_manager(self._connection, self, bus))

    def update_credentials(self, *, access_token: str | None = None, secret: str | None = None, bootstrap_token: str | None = None):
        if self._connection:
            self._connection.update_credentials(access_token=access_token, secret=secret, bootstrap_token=bootstrap_token)

    def stop(self, reason: str | None = None):
        self._fatal_error_reason = reason
        if self._connection:
            self._connection.stop(reason)

    def get_fatal_error_reason(self) -> str | None:
        if self._fatal_error_reason:
            return self._fatal_error_reason
        if self._connection:
            return self._connection.get_fatal_error_reason()
        return None

    async def connection_manager(self, agent_connection, client, bus):
        while True:
            try:
                self.init = False
                await agent_connection.open(client)

                await agent_connection._read_loop_task
                if agent_connection.get_status() == AgentConnectionStatus.STOP:
                    self._fatal_error_reason = agent_connection.get_fatal_error_reason()
                    logging.error(f"Stopping connection manager due to fatal connection error: {self._fatal_error_reason}")
                    break

                if agent_connection.get_status() != AgentConnectionStatus.CONNECTED:
                    agent_connection._status = AgentConnectionStatus.RECONNECTING
                    logging.warning(
                        "Connection loop ended with status %s. Retrying in %ss.",
                        agent_connection.get_status().name,
                        agent_connection._retry_delay,
                    )
                    await asyncio.sleep(agent_connection._retry_delay)
            except Exception as e:
                if agent_connection.get_status() == AgentConnectionStatus.STOP:
                    self._fatal_error_reason = agent_connection.get_fatal_error_reason() or str(e)
                    logging.error(f"Stopping connection manager due to fatal connection error: {self._fatal_error_reason}")
                    break
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

    async def process(self, event):
        if self._agent_session is None:
            raise RuntimeError("Agent session is not initialized")

        context = AgentSessionContext(
            connection=self._connection,
            client_id=self.client_id,
            initialized=self.init,
            send_event=self.send_event,
            set_initialized=self._set_initialized,
        )
        await self._agent_session.process(event, context)

    def _set_initialized(self, value: bool):
        self.init = value

