import unittest

from vm_agent_server.src.task_dispatcher import TaskDispatchResult, TaskDispatcher
from vm_agent_server.src.task_service import TaskService


class FakeTaskDB:
    def __init__(self):
        self.task: dict | None = None
        self.pipeline_run: dict | None = None
        self.pipeline: dict | None = None
        self.created_tasks = []
        self.task_status_updates = []
        self.pipeline_run_status_updates = []

    async def create_task(self, task):
        self.created_tasks.append(task)
        return task.to_api_dict(status="queued", created_at=1)

    async def update_task_status(self, task_id, status, pid=None, exit_code=None, error=None, actor="agent"):
        self.task_status_updates.append(
            {
                "task_id": task_id,
                "status": status,
                "pid": pid,
                "exit_code": exit_code,
                "error": error,
                "actor": actor,
            }
        )

    async def get_task(self, task_id):
        return self.task

    async def get_pipeline_run(self, run_id):
        return self.pipeline_run

    async def get_pipeline(self, pipeline_id):
        return self.pipeline

    async def update_pipeline_run_status(self, run_id, status, current_step=None, actor="system"):
        self.pipeline_run_status_updates.append(
            {
                "run_id": run_id,
                "status": status,
                "current_step": current_step,
                "actor": actor,
            }
        )


class TaskServiceAdvancePipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = FakeTaskDB()
        self.dispatcher = TaskDispatcher()
        self.service = TaskService(self.db, self.dispatcher)

    async def test_advance_pipeline_marks_run_completed_when_last_step_finishes(self):
        self.db.task = {"id": "task-1", "pipeline_run_id": "run-1", "step_index": 1}
        self.db.pipeline_run = {"id": "run-1", "pipeline_id": "pipe-1", "agent_id": "agent-1", "session": "", "status": "running"}
        self.db.pipeline = {
            "id": "pipe-1",
            "steps": [
                {"step_index": 0, "script": "echo 0"},
                {"step_index": 1, "script": "echo 1"},
            ],
        }

        await self.service.advance_pipeline("task-1", "completed")

        self.assertEqual(len(self.db.created_tasks), 0)
        self.assertEqual(self.db.pipeline_run_status_updates[-1]["status"], "completed")
        self.assertEqual(self.db.pipeline_run_status_updates[-1]["current_step"], 1)

    async def test_advance_pipeline_creates_and_dispatches_next_step(self):
        async def handle_agent(task):
            return TaskDispatchResult(accepted=True, status="running")

        self.dispatcher.register_handler("agent", handle_agent)
        self.db.task = {"id": "task-0", "pipeline_run_id": "run-2", "step_index": 0}
        self.db.pipeline_run = {"id": "run-2", "pipeline_id": "pipe-2", "agent_id": "agent-2", "session": "console", "status": "running"}
        self.db.pipeline = {
            "id": "pipe-2",
            "steps": [
                {"step_index": 0, "script": "echo 0"},
                {"step_index": 1, "script": "echo 1", "cwd": "C:/tmp", "timeout_sec": 12, "name": "Step One"},
            ],
        }

        await self.service.advance_pipeline("task-0", "completed")

        self.assertEqual(len(self.db.created_tasks), 1)
        next_task = self.db.created_tasks[0]
        self.assertEqual(next_task.step_index, 1)
        self.assertEqual(next_task.name, "Step One")
        self.assertEqual(next_task.cwd, "C:/tmp")
        self.assertEqual(next_task.timeout_sec, 12)
        self.assertEqual(next_task.session, "console")
        self.assertEqual(self.db.pipeline_run_status_updates[0]["status"], "running")
        self.assertEqual(self.db.pipeline_run_status_updates[0]["current_step"], 1)
        self.assertEqual(self.db.task_status_updates[-1]["status"], "running")

    async def test_advance_pipeline_marks_run_failed_when_step_has_stop_policy(self):
        self.db.task = {"id": "task-stop", "pipeline_run_id": "run-3", "step_index": 0}
        self.db.pipeline_run = {"id": "run-3", "pipeline_id": "pipe-3", "agent_id": "agent-3", "session": "", "status": "running"}
        self.db.pipeline = {
            "id": "pipe-3",
            "steps": [
                {"step_index": 0, "script": "echo 0", "on_fail": "stop"},
                {"step_index": 1, "script": "echo 1"},
            ],
        }

        await self.service.advance_pipeline("task-stop", "failed")

        self.assertEqual(len(self.db.created_tasks), 0)
        self.assertEqual(self.db.pipeline_run_status_updates[-1]["status"], "failed")
        self.assertEqual(self.db.pipeline_run_status_updates[-1]["current_step"], 0)

    async def test_advance_pipeline_marks_run_failed_when_dispatch_rejected(self):
        async def reject_agent(task):
            return TaskDispatchResult(accepted=False, status="failed", error="offline")

        self.dispatcher.register_handler("agent", reject_agent)
        self.db.task = {"id": "task-offline", "pipeline_run_id": "run-4", "step_index": 0}
        self.db.pipeline_run = {"id": "run-4", "pipeline_id": "pipe-4", "agent_id": "agent-4", "session": "", "status": "running"}
        self.db.pipeline = {
            "id": "pipe-4",
            "steps": [
                {"step_index": 0, "script": "echo 0"},
                {"step_index": 1, "script": "echo 1"},
            ],
        }

        await self.service.advance_pipeline("task-offline", "completed")

        self.assertEqual(len(self.db.created_tasks), 1)
        self.assertEqual(self.db.task_status_updates[-1]["status"], "failed")
        self.assertEqual(self.db.task_status_updates[-1]["error"], "offline")
        self.assertEqual(self.db.pipeline_run_status_updates[-1]["status"], "failed")
        self.assertEqual(self.db.pipeline_run_status_updates[-1]["current_step"], 1)


if __name__ == "__main__":
    unittest.main()