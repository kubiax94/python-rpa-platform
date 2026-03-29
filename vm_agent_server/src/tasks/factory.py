from __future__ import annotations

from uuid import uuid4

from vm_agent_server.src.api.schemas.task_requests import CreateTaskRequest
from vm_agent_server.src.tasks.models import AgentTaskSpec, TaskBuilder


class TaskFactory:
    @staticmethod
    def create_agent_task_from_request(
        body: CreateTaskRequest,
        *,
        requested_from: str,
        task_id: str | None = None,
    ) -> AgentTaskSpec:
        task = (
            TaskBuilder.agent(body.agent_id, body.script, task_id=task_id or uuid4().hex)
            .name(body.name)
            .cwd(body.cwd)
            .timeout(body.timeout_sec)
            .session(body.session)
            .requested_by(body.requested_by)
            .requested_from(requested_from)
            .env(body.env)
            .build()
        )
        return AgentTaskSpec.from_task_spec(task)

    @staticmethod
    def create_pipeline_step_task(
        *,
        agent_id: str,
        session: str,
        run_id: str,
        step: dict,
        requested_by: str,
        requested_from: str,
        task_id: str | None = None,
    ) -> AgentTaskSpec:
        task = (
            TaskBuilder.agent(agent_id, step["script"], task_id=task_id or uuid4().hex)
            .name(step.get("name", f"Step {step.get('step_index', 0)}"))
            .cwd(step.get("cwd", ""))
            .timeout(step.get("timeout_sec", 300))
            .session(session)
            .pipeline(run_id, step.get("step_index", 0))
            .requested_by(requested_by)
            .requested_from(requested_from)
            .build()
        )
        return AgentTaskSpec.from_task_spec(task)