import unittest

from shared.network.events.example_event import HandshakeData, HandshakeEvent
from vm_agent.src.network.agent_session import AgentSession
from vm_agent.src.network.event_router import EventRouter


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


if __name__ == "__main__":
    unittest.main()