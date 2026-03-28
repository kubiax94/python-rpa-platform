from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from shared.network.events.example_event import CancelTaskData, CancelTaskEvent
from vm_agent_server.src.api.schemas.query_params import AuditLogQuery, PipelineListQuery, TaskListQuery, TaskLogQuery
from vm_agent_server.src.api.schemas.task_responses import AuditEntryResponse, PipelineResponse, PipelineRunLaunchResponse, PipelineRunResponse, TaskCancelResponse, TaskLogResponse, TaskResponse
from vm_agent_server.src.api.schemas.task_requests import CreatePipelineRequest, CreateTaskRequest, RunPipelineRequest
from vm_agent_server.src.task_db import TaskDB
from vm_agent_server.src.task_factory import TaskFactory
from vm_agent_server.src.task_service import TaskService

SendToAgent = Callable[[str, object], Awaitable[bool]]


def build_task_router(task_service: TaskService, task_db: TaskDB, send_to_agent: SendToAgent) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/tasks", response_model=TaskResponse)
    async def api_create_task(body: CreateTaskRequest, request: Request):
        requested_from = request.client.host if request.client else ""
        task_spec = TaskFactory.create_agent_task_from_request(body, requested_from=requested_from)
        submission = await task_service.create_and_dispatch(task_spec)
        return submission.task

    @router.get("/tasks", response_model=list[TaskResponse])
    async def api_list_tasks(query: Annotated[TaskListQuery, Depends()]):
        return await task_db.get_tasks(query.agent_id, query.status, query.limit)

    @router.get("/tasks/{task_id}", response_model=TaskResponse)
    async def api_get_task(task_id: str):
        task = await task_db.get_task(task_id)
        if not task:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return task

    @router.post("/tasks/{task_id}/cancel", response_model=TaskCancelResponse)
    async def api_cancel_task(task_id: str, request: Request):
        task = await task_db.get_task(task_id)
        if not task:
            return JSONResponse({"error": "Not found"}, status_code=404)
        if task["status"] not in ("queued", "running"):
            return JSONResponse({"error": f"Cannot cancel task in status {task['status']}"}, status_code=400)

        sent = await send_to_agent(task["agent_id"], CancelTaskEvent(data=CancelTaskData(task_id=task_id)))
        if sent:
            await task_db.update_task_status(task_id, "cancelled", actor=request.client.host if request.client else "user")
        return {"ok": True, "sent": sent}

    @router.get("/tasks/{task_id}/log", response_model=TaskLogResponse)
    async def api_task_log(task_id: str, query: Annotated[TaskLogQuery, Depends()]):
        return task_db.read_log(task_id, query.offset, query.limit)

    @router.get("/tasks/{task_id}/log/raw")
    async def api_task_log_raw(task_id: str):
        result = task_db.read_log(task_id)
        return PlainTextResponse(result["content"], media_type="text/plain")

    @router.post("/pipelines", response_model=PipelineResponse)
    async def api_create_pipeline(body: CreatePipelineRequest):
        pipeline_id = uuid4().hex
        return await task_db.create_pipeline(
            pipeline_id,
            body.name,
            [step.model_dump() for step in body.steps],
            body.description,
            body.created_by,
        )

    @router.get("/pipelines", response_model=list[PipelineResponse])
    async def api_list_pipelines(query: Annotated[PipelineListQuery, Depends()]):
        return await task_db.get_pipelines(query.limit)

    @router.get("/pipelines/{pipeline_id}", response_model=PipelineResponse)
    async def api_get_pipeline(pipeline_id: str):
        pipeline = await task_db.get_pipeline(pipeline_id)
        if not pipeline:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return pipeline

    @router.post("/pipelines/{pipeline_id}/run", response_model=PipelineRunLaunchResponse)
    async def api_run_pipeline(pipeline_id: str, body: RunPipelineRequest, request: Request):
        requested_from = request.client.host if request.client else ""

        pipeline = await task_db.get_pipeline(pipeline_id)
        if not pipeline:
            return JSONResponse({"error": "Pipeline not found"}, status_code=404)

        steps = pipeline.get("steps", [])
        if not steps:
            return JSONResponse({"error": "Pipeline has no steps"}, status_code=400)

        run_id = uuid4().hex
        await task_db.create_pipeline_run(run_id, pipeline_id, body.agent_id, body.session, body.requested_by, requested_from)

        first_task = TaskFactory.create_pipeline_step_task(
            agent_id=body.agent_id,
            session=body.session,
            run_id=run_id,
            step=steps[0],
            requested_by=body.requested_by,
            requested_from=requested_from,
        )
        await task_db.update_pipeline_run_status(run_id, "running", 0)
        submission = await task_service.create_and_dispatch(first_task)
        if not submission.dispatch.accepted:
            await task_db.update_pipeline_run_status(run_id, "failed", 0)

        return {"run_id": run_id, "task_id": first_task.id, "sent": submission.dispatch.accepted}

    @router.get("/pipeline-runs/{run_id}", response_model=PipelineRunResponse)
    async def api_get_pipeline_run(run_id: str):
        run = await task_db.get_pipeline_run(run_id)
        if not run:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return run

    @router.get("/audit", response_model=list[AuditEntryResponse])
    async def api_audit_log(query: Annotated[AuditLogQuery, Depends()]):
        return await task_db.get_audit_log(query.entity_type, query.entity_id, query.limit)

    return router