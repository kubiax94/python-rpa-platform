import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vm_agent_server.src.api.routers.task_router import build_task_router
from vm_agent_server.src.task_dispatcher import TaskDispatchResult
from vm_agent_server.src.task_service import TaskSubmissionResult


class FakeTaskService:
    def __init__(self):
        self.submitted_task = None

    async def create_and_dispatch(self, task):
        self.submitted_task = task
        return TaskSubmissionResult(
            task={"id": task.id, "status": "running", "agent_id": task.agent_id, "script": task.script},
            dispatch=TaskDispatchResult(accepted=True, status="running"),
        )


class FakeTaskDB:
    def __init__(self):
        self.pipeline = None
        self.created_pipeline = None
        self.pipeline_run_updates = []

    async def get_tasks(self, agent_id=None, status=None, limit=50):
        return []

    async def get_task(self, task_id):
        return {"id": task_id, "status": "running", "agent_id": "agent-1"}

    async def update_task_status(self, task_id, status, pid=None, exit_code=None, error=None, actor="agent"):
        return None

    def read_log(self, task_id, offset=0, limit=0):
        return {"content": "", "offset": offset, "size": 0}

    async def create_pipeline(self, pipeline_id, name, steps, description, requested_by):
        self.created_pipeline = {
            "id": pipeline_id,
            "name": name,
            "steps": steps,
            "description": description,
            "requested_by": requested_by,
        }
        return {"id": pipeline_id, "name": name, "steps": len(steps)}

    async def get_pipelines(self, limit=50):
        return []

    async def get_pipeline(self, pipeline_id):
        return self.pipeline

    async def create_pipeline_run(self, run_id, pipeline_id, agent_id, session, requested_by, requested_from):
        return {"id": run_id}

    async def update_pipeline_run_status(self, run_id, status, current_step=None, actor="system"):
        self.pipeline_run_updates.append({"run_id": run_id, "status": status, "current_step": current_step, "actor": actor})

    async def get_pipeline_run(self, run_id):
        return {"id": run_id}

    async def get_audit_log(self, entity_type=None, entity_id=None, limit=100):
        return []


class TaskRouterTests(unittest.TestCase):
    def setUp(self):
        self.task_service = FakeTaskService()
        self.task_db = FakeTaskDB()

        async def send_to_agent(agent_id, event):
            return True

        app = FastAPI()
        app.include_router(build_task_router(self.task_service, self.task_db, send_to_agent))
        self.client = TestClient(app)

    def test_create_task_uses_pydantic_validation(self):
        response = self.client.post("/api/tasks", json={"agent_id": "agent-1"})

        self.assertEqual(response.status_code, 422)

    def test_create_task_builds_agent_task_spec(self):
        response = self.client.post(
            "/api/tasks",
            json={
                "agent_id": "agent-1",
                "script": "echo hello",
                "cwd": "C:/work",
                "timeout_sec": 15,
                "session": "console",
                "requested_by": "user",
                "env": {"DEMO": "1"},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.task_service.submitted_task.agent_id, "agent-1")
        self.assertEqual(self.task_service.submitted_task.script, "echo hello")
        self.assertEqual(self.task_service.submitted_task.cwd, "C:/work")
        self.assertEqual(self.task_service.submitted_task.timeout_sec, 15)
        self.assertEqual(self.task_service.submitted_task.session, "console")
        self.assertEqual(self.task_service.submitted_task.requested_from, "testclient")
        self.assertEqual(self.task_service.submitted_task.execution["env"], {"DEMO": "1"})

    def test_create_pipeline_uses_pydantic_step_validation(self):
        response = self.client.post(
            "/api/pipelines",
            json={"name": "Deploy", "steps": [{"step_index": 0}]},
        )

        self.assertEqual(response.status_code, 422)

    def test_run_pipeline_uses_factory_and_dispatch(self):
        self.task_db.pipeline = {
            "id": "pipe-1",
            "steps": [{"step_index": 0, "script": "echo one", "name": "Step 1", "cwd": "C:/app", "timeout_sec": 10}],
        }

        response = self.client.post(
            "/api/pipelines/pipe-1/run",
            json={"agent_id": "agent-7", "session": "console", "requested_by": "tester"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.task_service.submitted_task.agent_id, "agent-7")
        self.assertEqual(self.task_service.submitted_task.step_index, 0)
        self.assertEqual(self.task_service.submitted_task.cwd, "C:/app")
        self.assertEqual(self.task_db.pipeline_run_updates[0]["status"], "running")


if __name__ == "__main__":
    unittest.main()