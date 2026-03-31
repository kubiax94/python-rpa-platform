import unittest

from shared.network.events.example_event import CaptureProcessScreenshotData, CaptureProcessScreenshotEvent, StartProgramData, StartProgramEvent

from vm_agent_server.src.agents.command_handler import AgentCommandHandler
from vm_agent_server.src.network.context import AgentCommandContext


class AgentCommandHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.handler = AgentCommandHandler()
        self.forwarded = []
        self.rejected = []
        self.allowed = True
        self.ws = object()

    async def _forward(self, event_name, agent_id, event):
        self.forwarded.append(
            {
                "event_name": event_name,
                "agent_id": agent_id,
                "event_type": event.type,
            }
        )
        return True

    async def _reject(self, ws, minimum_role, event_type):
        self.rejected.append(
            {
                "ws": ws,
                "minimum_role": minimum_role,
                "event_type": event_type,
            }
        )

    def _has_role(self, ws, minimum_role):
        return self.allowed

    async def test_operator_command_forwards_when_role_present(self):
        event = StartProgramEvent(data=StartProgramData(agent_id="agent-1", exe="notepad.exe"))

        handled = await self.handler.handle(
            event,
            AgentCommandContext(
                ws=self.ws,
                forward_frontend_event=self._forward,
                reject_frontend_command=self._reject,
                websocket_has_minimum_role=self._has_role,
            ),
        )

        self.assertTrue(handled)
        self.assertEqual(self.forwarded[0]["event_name"], "start_program")
        self.assertEqual(self.forwarded[0]["agent_id"], "agent-1")
        self.assertEqual(len(self.rejected), 0)

    async def test_operator_command_rejects_when_role_missing(self):
        self.allowed = False
        event = StartProgramEvent(data=StartProgramData(agent_id="agent-2", exe="cmd.exe"))

        handled = await self.handler.handle(
            event,
            AgentCommandContext(
                ws=self.ws,
                forward_frontend_event=self._forward,
                reject_frontend_command=self._reject,
                websocket_has_minimum_role=self._has_role,
            ),
        )

        self.assertTrue(handled)
        self.assertEqual(len(self.forwarded), 0)
        self.assertEqual(self.rejected[0]["event_type"], "start_program")
        self.assertEqual(self.rejected[0]["minimum_role"], "operator")

    async def test_capture_screenshot_forwards_without_operator_role(self):
        self.allowed = False
        event = CaptureProcessScreenshotEvent(
            data=CaptureProcessScreenshotData(agent_id="agent-3", request_id="req-1")
        )

        handled = await self.handler.handle(
            event,
            AgentCommandContext(
                ws=self.ws,
                forward_frontend_event=self._forward,
                reject_frontend_command=self._reject,
                websocket_has_minimum_role=self._has_role,
            ),
        )

        self.assertTrue(handled)
        self.assertEqual(self.forwarded[0]["event_name"], "capture_process_screenshot")
        self.assertEqual(len(self.rejected), 0)


if __name__ == "__main__":
    unittest.main()