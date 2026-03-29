import unittest

from vm_agent_server.src.tasks.dispatcher import (
    TaskDispatchResult,
    TaskDispatcher,
    build_agent_task_handler,
    build_deployment_task_handler,
)
from vm_agent_server.src.tasks.models import DeploymentTaskSpec, TaskBuilder


class TaskDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_without_handler_returns_failed_result(self):
        dispatcher = TaskDispatcher()
        task = TaskBuilder.agent("agent-1", "echo ok").build()

        result = await dispatcher.dispatch(task)

        self.assertFalse(result.accepted)
        self.assertEqual(result.status, "failed")
        self.assertIn("No handler registered", result.error)

    async def test_agent_handler_builds_execute_event(self):
        captured: dict = {}

        async def send_event(agent_id: str, event: object) -> bool:
            captured["agent_id"] = agent_id
            captured["event"] = event
            return True

        handler = build_agent_task_handler(send_event)
        task = (
            TaskBuilder.agent("agent-42", "echo hello")
            .cwd("C:/work")
            .timeout(45)
            .session("console")
            .env({"HELLO": "WORLD"})
            .build()
        )

        result = await handler(task)

        self.assertTrue(result.accepted)
        self.assertEqual(result.status, "running")
        self.assertEqual(captured["agent_id"], "agent-42")
        self.assertEqual(captured["event"].data.task_id, task.id)
        self.assertEqual(captured["event"].data.script, "echo hello")
        self.assertEqual(captured["event"].data.cwd, "C:/work")
        self.assertEqual(captured["event"].data.timeout_sec, 45)
        self.assertEqual(captured["event"].data.session, "console")
        self.assertEqual(captured["event"].data.env, {"HELLO": "WORLD"})

    async def test_deployment_handler_converts_to_deployment_spec(self):
        captured: dict = {}

        async def dispatch_deployment(task: DeploymentTaskSpec) -> TaskDispatchResult:
            captured["task"] = task
            return TaskDispatchResult(accepted=True, status="running")

        handler = build_deployment_task_handler(dispatch_deployment)
        task = (
            TaskBuilder.deployment("agent-7", "prepare")
            .payload_field("deployment_id", "dep-7")
            .component("deployment", deployment_id="dep-7")
            .build()
        )

        result = await handler(task)

        self.assertTrue(result.accepted)
        self.assertIsInstance(captured["task"], DeploymentTaskSpec)
        self.assertEqual(captured["task"].operation, "prepare")
        self.assertEqual(captured["task"].payload["deployment_id"], "dep-7")

    async def test_dispatcher_routes_by_kind(self):
        dispatcher = TaskDispatcher()

        async def handle_agent(task):
            return TaskDispatchResult(accepted=True, status=f"agent:{task.kind}")

        dispatcher.register_handler("agent", handle_agent)
        task = TaskBuilder.agent("agent-9", "hostname").build()

        result = await dispatcher.dispatch(task)

        self.assertTrue(result.accepted)
        self.assertEqual(result.status, "agent:agent")


if __name__ == "__main__":
    unittest.main()