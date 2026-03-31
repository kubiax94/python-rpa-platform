import unittest

from shared.network.events.example_event import TaskOutputData, TaskOutputEvent, TaskStatusData, TaskStatusEvent

from vm_agent_server.src.network.context import TaskEventContext
from vm_agent_server.src.tasks.network_handler import TaskNetworkHandler


class FakeTaskDB:
    def __init__(self):
        self.logs = []
        self.status_updates = []

    def append_log(self, task_id, stream, data, seq):
        self.logs.append(
            {
                "task_id": task_id,
                "stream": stream,
                "data": data,
                "seq": seq,
            }
        )

    async def update_task_status(self, task_id, status, pid=None, exit_code=None, error=None, actor="agent"):
        self.status_updates.append(
            {
                "task_id": task_id,
                "status": status,
                "pid": pid,
                "exit_code": exit_code,
                "error": error,
                "actor": actor,
            }
        )


class FakeTaskService:
    def __init__(self):
        self.advance_pipeline_calls = []

    async def advance_pipeline(self, task_id, task_status):
        self.advance_pipeline_calls.append({"task_id": task_id, "task_status": task_status})


class TaskNetworkHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.task_db = FakeTaskDB()
        self.task_service = FakeTaskService()
        self.handler = TaskNetworkHandler(self.task_db, self.task_service)
        self.broadcasts = []

    async def _broadcast(self, task_id, payload):
        self.broadcasts.append({"task_id": task_id, "payload": payload})

    async def test_handle_appends_task_output_and_broadcasts(self):
        event = TaskOutputEvent(
            data=TaskOutputData(task_id="task-1", stream="stdout", data="hello", seq=3)
        )

        handled = await self.handler.handle(
            event,
            TaskEventContext(
                client_id="agent-1",
                broadcast_task_event=self._broadcast,
            ),
        )

        self.assertTrue(handled)
        self.assertEqual(self.task_db.logs[0]["task_id"], "task-1")
        self.assertEqual(self.task_db.logs[0]["data"], "hello")
        self.assertEqual(self.broadcasts[0]["payload"]["type"], "task_output")

    async def test_handle_updates_task_status_and_advances_pipeline(self):
        event = TaskStatusEvent(
            data=TaskStatusData(task_id="task-2", status="completed", pid=123, exit_code=0)
        )

        handled = await self.handler.handle(
            event,
            TaskEventContext(
                client_id="agent-7",
                broadcast_task_event=self._broadcast,
            ),
        )

        self.assertTrue(handled)
        self.assertEqual(self.task_db.status_updates[0]["task_id"], "task-2")
        self.assertEqual(self.task_db.status_updates[0]["actor"], "agent-7")
        self.assertEqual(self.broadcasts[0]["payload"]["type"], "task_status")
        self.assertEqual(self.task_service.advance_pipeline_calls[0]["task_id"], "task-2")


if __name__ == "__main__":
    unittest.main()