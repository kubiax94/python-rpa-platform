import unittest

from shared.network.events.example_event import ProcessScreenshotData, ProcessScreenshotEvent

from vm_agent_server.src.network.context import ProcessScreenshotContext
from vm_agent_server.src.process_monitoring.network_handler import ProcessMonitoringNetworkHandler


class ProcessMonitoringNetworkHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sent_events = []
        self.process_manager_watchers = {}
        self.frontend_watched_agents = {}

        async def send_to_agent(agent_id, event):
            self.sent_events.append(
                {
                    "agent_id": agent_id,
                    "event_type": event.type,
                    "enabled": getattr(event.data, "enabled", None),
                }
            )
            return True

        self.handler = ProcessMonitoringNetworkHandler(
            send_to_agent,
            self.process_manager_watchers,
            self.frontend_watched_agents,
        )
        self.broadcasts = []

    async def _broadcast(self, payload):
        self.broadcasts.append(payload)

    async def test_handle_broadcasts_process_screenshot(self):
        event = ProcessScreenshotEvent(
            data=ProcessScreenshotData(
                agent_id="",
                target_type="process",
                pid=123,
                request_id="req-1",
                status="completed",
                image_base64="abc",
            )
        )

        handled = await self.handler.handle(
            event,
            ProcessScreenshotContext(
                client_id="agent-1",
                broadcast_process_screenshot=self._broadcast,
            ),
        )

        self.assertTrue(handled)
        self.assertEqual(self.broadcasts[0]["agent_id"], "agent-1")
        self.assertEqual(self.broadcasts[0]["pid"], 123)

    async def test_add_and_remove_watcher_toggle_window_tracking_once_per_agent(self):
        ws = object()

        await self.handler.add_watcher(ws, "agent-2")
        await self.handler.add_watcher(ws, "agent-2")
        await self.handler.remove_watcher(ws, "agent-2")

        self.assertEqual(len(self.sent_events), 2)
        self.assertEqual(self.sent_events[0]["event_type"], "set_window_tracking")
        self.assertTrue(self.sent_events[0]["enabled"])
        self.assertFalse(self.sent_events[1]["enabled"])
        self.assertNotIn("agent-2", self.process_manager_watchers)


if __name__ == "__main__":
    unittest.main()