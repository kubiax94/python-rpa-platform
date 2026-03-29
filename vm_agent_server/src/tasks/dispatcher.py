from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from shared.network.events.example_event import ExecuteTaskData, ExecuteTaskEvent
from vm_agent_server.src.tasks.models import AgentTaskSpec, DeploymentTaskSpec, TaskSpec


@dataclass(frozen=True, slots=True)
class TaskDispatchResult:
    accepted: bool
    status: str | None = None
    error: str | None = None


TaskHandler = Callable[[TaskSpec], Awaitable[TaskDispatchResult]]
AgentSendEvent = Callable[[str, object], Awaitable[bool]]
DeploymentDispatch = Callable[[DeploymentTaskSpec], Awaitable[TaskDispatchResult]]


class TaskDispatcher:
    def __init__(self):
        self._handlers: dict[str, TaskHandler] = {}

    def register_handler(self, kind: str, handler: TaskHandler) -> None:
        self._handlers[kind] = handler

    async def dispatch(self, task: TaskSpec) -> TaskDispatchResult:
        handler = self._handlers.get(task.kind)
        if handler is None:
            return TaskDispatchResult(accepted=False, status="failed", error=f"No handler registered for task kind '{task.kind}'")
        return await handler(task)


def build_agent_task_handler(send_event: AgentSendEvent) -> TaskHandler:
    async def handle(task: TaskSpec) -> TaskDispatchResult:
        agent_task = task if isinstance(task, AgentTaskSpec) else AgentTaskSpec.from_task_spec(task)
        execution = agent_task.execution
        sent = await send_event(
            agent_task.agent_id,
            ExecuteTaskEvent(
                data=ExecuteTaskData(
                    task_id=agent_task.id,
                    script=execution["script"],
                    cwd=execution["cwd"],
                    timeout_sec=execution["timeout_sec"],
                    session=execution["session"],
                    env=execution["env"],
                )
            ),
        )
        if sent:
            return TaskDispatchResult(accepted=True, status="running")
        return TaskDispatchResult(accepted=False, status="failed", error="Agent not connected")

    return handle


def build_deployment_task_handler(dispatch_deployment: DeploymentDispatch) -> TaskHandler:
    async def handle(task: TaskSpec) -> TaskDispatchResult:
        deployment_task = task if isinstance(task, DeploymentTaskSpec) else DeploymentTaskSpec.from_task_spec(task)
        return await dispatch_deployment(deployment_task)

    return handle