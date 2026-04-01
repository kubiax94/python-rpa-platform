import unittest

from pyee import EventEmitter
from shared.network.events.example_event import CaptureProcessScreenshotData, CaptureProcessScreenshotEvent, ExecuteTaskData, ExecuteTaskEvent, HandshakeData, HandshakeEvent, StartProgramData, StartProgramEvent
from vm_agent.src.agents.command_handler import AgentCommandHandler
from vm_agent.src.agents.lifecycle_handler import AgentLifecycleHandler
from vm_agent.src.network.agent_session import AgentSession
from vm_agent.src.network.context import AgentSessionContext
from vm_agent.src.network.event_router import EventRouter
from vm_agent.src.process_monitoring.network_handler import ProcessMonitoringHandler
from vm_agent.src.tasks.network_handler import AgentTaskHandler


class RecordingHandler:
    event_types = ("handshake",)

    def __init__(self):
        self.events = []

    def handle_event(self, event, connection):
        self.events.append({"type": event.type, "client_id": event.data.client_id, "connection": connection})


class AgentSessionTests(unittest.IsolatedAsyncioTestCase):
    def _make_context(self):
        state = {"initialized": False, "sent": []}

        def send_event(event):
            state["sent"].append(event)

        def set_initialized(value: bool):
            state["initialized"] = value

        return AgentSessionContext(
            connection=object(),
            client_id="agent-test",
            initialized=state["initialized"],
            send_event=send_event,
            set_initialized=set_initialized,
        ), state

    async def test_process_uses_shared_parser_and_dispatches_to_registered_handler(self):
        router = EventRouter()
        handler = RecordingHandler()
        router.register(handler.event_types, handler.handle_event)
        session = AgentSession(router)
        context, _state = self._make_context()

        handled = await session.process(
            HandshakeEvent(data=HandshakeData(client_id="agent-123", hostname="host")).model_dump_json(),
            context,
        )

        self.assertTrue(handled)
        self.assertEqual(handler.events, [{"type": "handshake", "client_id": "agent-123", "connection": context}])

    async def test_lifecycle_handler_responds_to_handshake_via_session_context(self):
        router = EventRouter()
        bus = EventEmitter()
        handler = AgentLifecycleHandler(bus)
        context, state = self._make_context()

        router.register(handler.event_types, handler.handle_event)
        session = AgentSession(router)

        handled = await session.process(
            HandshakeEvent(data=HandshakeData(client_id="agent-456", hostname="host")).model_dump_json(),
            context,
        )

        self.assertTrue(handled)
        self.assertTrue(state["initialized"])
        self.assertEqual(len(state["sent"]), 1)
        self.assertIsInstance(state["sent"][0], HandshakeEvent)
        self.assertEqual(state["sent"][0].data.client_id, "agent-test")

    async def test_lifecycle_handler_ignores_duplicate_handshake_when_context_initialized(self):
        router = EventRouter()
        bus = EventEmitter()
        handler = AgentLifecycleHandler(bus)
        context, state = self._make_context()
        context.initialized = True

        router.register(handler.event_types, handler.handle_event)
        session = AgentSession(router)

        handled = await session.process(
            HandshakeEvent(data=HandshakeData(client_id="agent-789", hostname="host")).model_dump_json(),
            context,
        )

        self.assertTrue(handled)
        self.assertEqual(state["sent"], [])

    async def test_command_handler_accepts_typed_start_program_payload_from_shared_parser(self):
        router = EventRouter()
        bus = EventEmitter()
        received = []
        handler = AgentCommandHandler(bus)
        context, _state = self._make_context()

        bus.once("start_program", lambda payload: received.append(payload))
        router.register(handler.event_types, handler.handle_event)
        session = AgentSession(router)

        handled = await session.process(
            StartProgramEvent(data=StartProgramData(exe="notepad.exe", args="", cwd="", visible=True, session="")).model_dump_json(),
            context,
        )

        self.assertTrue(handled)
        self.assertEqual(len(received), 1)
        self.assertIsInstance(received[0], StartProgramData)
        self.assertEqual(received[0].exe, "notepad.exe")

    async def test_task_handler_accepts_typed_execute_task_payload_from_shared_parser(self):
        router = EventRouter()
        bus = EventEmitter()
        received = []
        handler = AgentTaskHandler(bus)
        context, _state = self._make_context()

        bus.once("execute_task", lambda payload: received.append(payload))
        router.register(handler.event_types, handler.handle_event)
        session = AgentSession(router)

        handled = await session.process(
            ExecuteTaskEvent(data=ExecuteTaskData(task_id="task-1", script="Write-Output hi", cwd="", timeout_sec=30, session="", env={})).model_dump_json(),
            context,
        )

        self.assertTrue(handled)
        self.assertEqual(len(received), 1)
        self.assertIsInstance(received[0], ExecuteTaskData)
        self.assertEqual(received[0].task_id, "task-1")

    async def test_process_monitoring_handler_accepts_typed_capture_payload_from_shared_parser(self):
        router = EventRouter()
        bus = EventEmitter()
        received = []
        handler = ProcessMonitoringHandler(bus)
        context, _state = self._make_context()

        bus.once("capture_process_screenshot", lambda payload: received.append(payload))
        router.register(handler.event_types, handler.handle_event)
        session = AgentSession(router)

        handled = await session.process(
            CaptureProcessScreenshotEvent(
                data=CaptureProcessScreenshotData(agent_id="agent-1", target_type="process", pid=42, request_id="req-1")
            ).model_dump_json(),
            context,
        )

        self.assertTrue(handled)
        self.assertEqual(len(received), 1)
        self.assertIsInstance(received[0], CaptureProcessScreenshotData)
        self.assertEqual(received[0].pid, 42)


if __name__ == "__main__":
    unittest.main()