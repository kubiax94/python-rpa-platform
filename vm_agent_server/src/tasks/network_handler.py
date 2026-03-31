from __future__ import annotations

from shared.network.events.example_event import TaskOutputEvent, TaskStatusEvent
from shared.protocol.network_event import NetworkEvent
from vm_agent_server.src.network.context import TaskEventContext

from vm_agent_server.src.tasks.db import TaskDB
from vm_agent_server.src.tasks.service import TaskService


class TaskNetworkHandler:
    event_types = ("task_output", "task_status")

    def __init__(self, task_db: TaskDB, task_service: TaskService):
        self._task_db = task_db
        self._task_service = task_service

    def can_handle(self, event: NetworkEvent) -> bool:
        return event.type in self.event_types

    async def handle(
        self,
        event: NetworkEvent,
        context: TaskEventContext,
    ) -> bool:
        if event.type == "task_output":
            return await self._handle_task_output(event, context)
        if event.type == "task_status":
            return await self._handle_task_status(event, context)
        return False

    async def _handle_task_output(
        self,
        event: NetworkEvent,
        context: TaskEventContext,
    ) -> bool:
        if not isinstance(event, TaskOutputEvent):
            return False

        self._task_db.append_log(
            event.data.task_id,
            event.data.stream,
            event.data.data,
            event.data.seq,
        )
        await context.broadcast_task_event(
            event.data.task_id,
            {
                "type": "task_output",
                "task_id": event.data.task_id,
                "stream": event.data.stream,
                "data": event.data.data,
                "seq": event.data.seq,
            },
        )
        return True

    async def _handle_task_status(
        self,
        event: NetworkEvent,
        context: TaskEventContext,
    ) -> bool:
        if not isinstance(event, TaskStatusEvent):
            return False

        await self._task_db.update_task_status(
            event.data.task_id,
            event.data.status,
            pid=event.data.pid,
            exit_code=event.data.exit_code,
            error=event.data.error,
            actor=context.client_id or "agent",
        )
        await context.broadcast_task_event(
            event.data.task_id,
            {
                "type": "task_status",
                "task_id": event.data.task_id,
                "status": event.data.status,
                "pid": event.data.pid,
                "exit_code": event.data.exit_code,
                "error": event.data.error,
            },
        )
        if event.data.status in ("completed", "failed", "timeout"):
            await self._task_service.advance_pipeline(event.data.task_id, event.data.status)
        return True