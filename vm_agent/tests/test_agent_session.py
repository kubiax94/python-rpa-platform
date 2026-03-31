import unittest

from pyee import EventEmitter
from shared.network.events.example_event import HandshakeData, HandshakeEvent
from vm_agent.src.network.agent_session import AgentSession
from vm_agent.src.network.event_router import EventRouter
from vm_agent.src.network.network_event_handler import NetworkEventHandler


class RecordingHandler:
    event_types = ("handshake",)

    def __init__(self):
        self.events = []

    def handle_event(self, event, connection):
        self.events.append({"type": event.type, "client_id": event.data.client_id, "connection": connection})


class AgentSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_uses_shared_parser_and_dispatches_to_registered_handler(self):
        router = EventRouter()
        handler = RecordingHandler()
        connection = object()
        router.register(handler.event_types, handler.handle_event)
        session = AgentSession(router)

        handled = await session.process(
            HandshakeEvent(data=HandshakeData(client_id="agent-123", hostname="host")).model_dump_json(),
            connection,
        )

        self.assertTrue(handled)
        self.assertEqual(handler.events, [{"type": "handshake", "client_id": "agent-123", "connection": connection}])

    async def test_network_event_handler_accepts_typed_handshake_payload_from_shared_parser(self):
        router = EventRouter()
        bus = EventEmitter()
        received = []
        connection = object()
        handler = NetworkEventHandler(bus)

        bus.once("handshake", lambda payload: received.append(payload))
        router.register(handler.event_types, handler.handle_event)
        session = AgentSession(router)

        handled = await session.process(
            HandshakeEvent(data=HandshakeData(client_id="agent-456", hostname="host")).model_dump_json(),
            connection,
        )

        self.assertTrue(handled)
        self.assertEqual(len(received), 1)
        self.assertIsInstance(received[0], HandshakeData)
        self.assertEqual(received[0].client_id, "agent-456")


if __name__ == "__main__":
    unittest.main()