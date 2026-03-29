from __future__ import annotations

from dataclasses import dataclass

from vm_agent_server.src.tasks.db import TaskDB
from vm_agent_server.src.tasks.dispatcher import TaskDispatchResult, TaskDispatcher
from vm_agent_server.src.tasks.factory import TaskFactory
from vm_agent_server.src.tasks.models import TaskSpec


@dataclass(frozen=True, slots=True)
class TaskSubmissionResult:
    task: dict
    dispatch: TaskDispatchResult


class TaskService:
    def __init__(self, task_db: TaskDB, dispatcher: TaskDispatcher):
        self._task_db = task_db
        self._dispatcher = dispatcher

    async def create_task(self, task: TaskSpec) -> dict:
        return await self._task_db.create_task(task)

    async def create_and_dispatch(self, task: TaskSpec, *, actor: str = "server") -> TaskSubmissionResult:
        created_task = await self._task_db.create_task(task)
        dispatch = await self.dispatch(task, actor=actor)
        if dispatch.status:
            created_task["status"] = dispatch.status
        if dispatch.error:
            created_task["error"] = dispatch.error
        return TaskSubmissionResult(task=created_task, dispatch=dispatch)

    async def dispatch(self, task: TaskSpec, *, actor: str = "server") -> TaskDispatchResult:
        result = await self._dispatcher.dispatch(task)
        if result.status is not None:
            await self._task_db.update_task_status(task.id, result.status, error=result.error, actor=actor)
        return result

    async def advance_pipeline(self, task_id: str, task_status: str) -> None:
        task = await self._task_db.get_task(task_id)
        if not task or not task.get("pipeline_run_id"):
            return

        run_id = task["pipeline_run_id"]
        run = await self._task_db.get_pipeline_run(run_id)
        if not run or run["status"] not in ("running", "queued"):
            return

        pipeline = await self._task_db.get_pipeline(run["pipeline_id"])
        if not pipeline:
            return

        steps = pipeline.get("steps", [])
        current_step = task["step_index"]

        if task_status in {"failed", "timeout"}:
            step_def = next((step for step in steps if step["step_index"] == current_step), None)
            on_fail = step_def.get("on_fail", "stop") if step_def else "stop"
            if on_fail == "stop":
                await self._task_db.update_pipeline_run_status(run_id, "failed", current_step)
                return

        next_index = current_step + 1
        next_step = next((step for step in steps if step["step_index"] == next_index), None)
        if not next_step:
            await self._task_db.update_pipeline_run_status(run_id, "completed", current_step)
            return

        next_task = TaskFactory.create_pipeline_step_task(
            agent_id=run["agent_id"],
            session=run.get("session", ""),
            run_id=run_id,
            step=next_step,
            requested_by="pipeline",
            requested_from="server",
        )

        await self._task_db.update_pipeline_run_status(run_id, "running", next_index)
        result = await self.create_and_dispatch(next_task)
        if not result.dispatch.accepted:
            await self._task_db.update_pipeline_run_status(run_id, "failed", next_index)