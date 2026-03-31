import logging
import unittest
from types import SimpleNamespace

from fastapi import WebSocketDisconnect

from shared.network.events.example_event import HandshakeData, HandshakeEvent, StartProgramData, StartProgramEvent, TaskOutputData, TaskOutputEvent, WatchProcessManagerData, WatchProcessManagerEvent
from vm_agent_server.src.network.agent_session import run_agent_ws_session
from vm_agent_server.src.network.context import AgentSessionDependencies, FrontendSessionDependencies
from vm_agent_server.src.network.frontend_session import run_frontend_ws_session


class FakeSnapshotEvent:
    def __init__(self):
        self.set_calls = 0

    def set(self):
        self.set_calls += 1


class FakeWebSocket:
    def __init__(self, messages):
        self._messages = list(messages)
        self.sent_json = []
        self.sent_text = []
        self.closed = []
        self.state = SimpleNamespace()

    async def receive_text(self):
        if not self._messages:
            raise WebSocketDisconnect()
        return self._messages.pop(0)

    async def send_json(self, payload):
        self.sent_json.append(payload)

    async def send_text(self, payload):
        self.sent_text.append(payload)

    async def close(self, code=None, reason=None):
        self.closed.append({"code": code, "reason": reason})


class FakeLifecycleHandler:
    event_types = ("handshake", "heartbeat")

    def __init__(self):
        self.handled = []
        self.cleanup_calls = 0

    async def handle(self, event, context):
        self.handled.append(event.type)
        if event.type == "handshake":
            context.state.authenticated = True
            context.state.client_id = event.data.client_id
        return True

    async def cleanup_connection(self, context):
        self.cleanup_calls += 1
        return True


class FakeTaskHandler:
    event_types = ("task_output", "task_status")

    def __init__(self):
        self.handled = []

    async def handle(self, event, context):
        self.handled.append({"type": event.type, "client_id": context.client_id})
        return True


class FakeProcessMonitoringHandler:
    agent_event_types = ("process_screenshot",)
    frontend_event_types = ("watch_process_manager", "unwatch_process_manager")

    def __init__(self):
        self.handled = []
        self.watcher_calls = []

    async def handle(self, event, context):
        self.handled.append({"type": event.type, "client_id": context.client_id})
        return True

    async def add_watcher(self, ws, agent_id):
        self.watcher_calls.append({"action": "add", "agent_id": agent_id})

    async def remove_watcher(self, ws, agent_id):
        self.watcher_calls.append({"action": "remove", "agent_id": agent_id})

    async def remove_all_watchers(self, ws):
        self.watcher_calls.append({"action": "remove_all"})


class FakeUserService:
    def get_session(self, access_token):
        if access_token == "valid-token":
            return SimpleNamespace(user=SimpleNamespace(roles=["operator"]))
        return None


class FakeAgentRuntime:
    def __init__(self):
        self.latest_stats = {"agent-1": {}}

    def build_frontend_snapshot(self):
        return {"agent-1": {"status": "online"}}


class FakeAgentCommandHandler:
    event_types = ("start_program", "start_monitored_process", "create_session", "capture_process_screenshot")

    def __init__(self):
        self.handled = []

    async def handle(self, event, context):
        self.handled.append({"type": event.type, "ws": context.ws})
        await context.forward_frontend_event(event.type, getattr(event.data, "agent_id", ""), event)
        return True


class NetworkSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_session_routes_handshake_then_task_event(self):
        lifecycle_handler = FakeLifecycleHandler()
        task_handler = FakeTaskHandler()
        process_handler = FakeProcessMonitoringHandler()
        snapshot_event = FakeSnapshotEvent()
        frontend_fallback_calls = []

        async def broadcast_task_event(task_id, payload):
            return None

        async def broadcast_process_screenshot(payload):
            return None

        async def set_window_tracking(agent_id, enabled):
            return True

        async def run_frontend_fallback(ws, payload):
            frontend_fallback_calls.append(payload)

        ws = FakeWebSocket(
            [
                HandshakeEvent(data=HandshakeData(client_id="agent-7", hostname="vm-1")).model_dump_json(),
                TaskOutputEvent(data=TaskOutputData(task_id="task-1", data="hello", seq=1)).model_dump_json(),
            ]
        )

        deps = AgentSessionDependencies(
            create_lifecycle_handler=lambda: lifecycle_handler,
            task_network_handler=task_handler,
            create_process_monitoring_handler=lambda: process_handler,
            set_window_tracking=set_window_tracking,
            broadcast_task_event=broadcast_task_event,
            broadcast_process_screenshot=broadcast_process_screenshot,
            run_frontend_ws_session=run_frontend_fallback,
            frontend_snapshot_event=snapshot_event,
            logger=logging.getLogger("test.agent_session"),
        )

        await run_agent_ws_session(ws, "token", deps)

        self.assertEqual(lifecycle_handler.handled, ["handshake"])
        self.assertEqual(task_handler.handled[0]["type"], "task_output")
        self.assertEqual(task_handler.handled[0]["client_id"], "agent-7")
        self.assertEqual(snapshot_event.set_calls, 1)
        self.assertEqual(frontend_fallback_calls, [])

    async def test_frontend_session_routes_command_and_watcher_event(self):
        process_handler = FakeProcessMonitoringHandler()
        command_handler = FakeAgentCommandHandler()
        forwarded = []
        frontend_clients = set()
        frontend_watched_agents = {}

        async def forward_frontend_event(event_name, agent_id, event):
            forwarded.append({"event_name": event_name, "agent_id": agent_id})
            return True

        async def reject_frontend_command(ws, minimum_role, event_type):
            raise AssertionError("command should not be rejected")

        def websocket_has_minimum_role(ws, minimum_role):
            return True

        ws = FakeWebSocket(
            [
                StartProgramEvent(data=StartProgramData(agent_id="agent-1", exe="notepad.exe")).model_dump_json(),
                WatchProcessManagerEvent(data=WatchProcessManagerData(agent_id="agent-1")).model_dump_json(),
            ]
        )

        deps = FrontendSessionDependencies(
            user_service=FakeUserService(),
            agent_runtime=FakeAgentRuntime(),
            frontend_clients=frontend_clients,
            frontend_watched_agents=frontend_watched_agents,
            create_process_monitoring_handler=lambda: process_handler,
            agent_command_handler=command_handler,
            forward_frontend_event=forward_frontend_event,
            reject_frontend_command=reject_frontend_command,
            websocket_has_minimum_role=websocket_has_minimum_role,
            logger=logging.getLogger("test.frontend_session"),
        )

        await run_frontend_ws_session(ws, {"access_token": "valid-token"}, deps)

        self.assertEqual(ws.sent_json[0]["kind"], "auth_ok")
        self.assertEqual(ws.sent_json[1]["kind"], "agents_snapshot")
        self.assertEqual(command_handler.handled[0]["type"], "start_program")
        self.assertEqual(forwarded[0]["event_name"], "start_program")
        self.assertEqual(process_handler.watcher_calls[0], {"action": "add", "agent_id": "agent-1"})
        self.assertEqual(process_handler.watcher_calls[-1], {"action": "remove_all"})


if __name__ == "__main__":
    unittest.main()