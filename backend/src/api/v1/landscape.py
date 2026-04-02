"""Landscape API — start DRL tasks, poll status, or stream via SSE."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from src.models.db import TaskStatus
from src.services import task_manager

router = APIRouter(prefix="/api/v1/landscape", tags=["landscape"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class _StartData(BaseModel):
    task_id: str


class StartRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)


class StartResponse(BaseModel):
    data: _StartData
    meta: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class TaskStatusData(BaseModel):
    task_id: str
    status: TaskStatus
    progress_message: str
    current_stage_id: str = ""
    current_progress_pct: int = 0
    progress_snapshot: dict[str, dict[str, Any]] = Field(default_factory=dict)
    result: dict[str, Any] | None = None


class TaskStatusResponse(BaseModel):
    data: TaskStatusData
    meta: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class TaskListItem(BaseModel):
    task_id: str
    topic: str
    status: TaskStatus
    progress_message: str
    has_result: bool
    created_at: str
    updated_at: str


class TaskListResponse(BaseModel):
    data: list[TaskListItem]
    meta: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class DeleteTaskData(BaseModel):
    task_id: str
    deleted: bool


class DeleteTaskResponse(BaseModel):
    data: DeleteTaskData
    meta: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


# ---------------------------------------------------------------------------
# GET /tasks  (list recent landscape tasks)
# ---------------------------------------------------------------------------

@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(limit: int = 50) -> TaskListResponse:
    """Return recent landscape tasks (without full result payloads)."""
    records = task_manager.list_tasks(limit=min(limit, 200))
    items = [
        TaskListItem(
            task_id=r.id,
            topic=r.topic,
            status=r.status,
            progress_message=r.progress_message,
            has_result=r.result is not None,
            created_at=r.created_at.isoformat(),
            updated_at=r.updated_at.isoformat(),
        )
        for r in records
    ]
    return TaskListResponse(data=items)


# ---------------------------------------------------------------------------
# DELETE /{task_id}
# ---------------------------------------------------------------------------

@router.delete("/{task_id}", response_model=DeleteTaskResponse)
async def delete_landscape_task(task_id: str) -> DeleteTaskResponse:
    """Delete a landscape task record."""
    deleted = task_manager.delete_task(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    return DeleteTaskResponse(data=DeleteTaskData(task_id=task_id, deleted=True))


# ---------------------------------------------------------------------------
# POST /start
# ---------------------------------------------------------------------------

@router.post("/start", response_model=StartResponse, status_code=202)
async def start_landscape(
    body: StartRequest,
    background_tasks: BackgroundTasks,
) -> StartResponse:
    """Create a landscape task and run the pipeline in the background."""
    task_id = task_manager.create_task(body.topic)
    background_tasks.add_task(task_manager.run_landscape_task, task_id, body.topic)
    return StartResponse(data=_StartData(task_id=task_id))


# ---------------------------------------------------------------------------
# GET /{task_id}/status
# ---------------------------------------------------------------------------

@router.get("/{task_id}/status", response_model=TaskStatusResponse)
async def get_status(task_id: str) -> TaskStatusResponse:
    """Return the current snapshot of a landscape task."""
    record = task_manager.get_task(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskStatusResponse(
        data=TaskStatusData(
            task_id=record.id,
            status=record.status,
            progress_message=record.progress_message,
            current_stage_id=record.current_stage_id,
            current_progress_pct=record.current_progress_pct,
            progress_snapshot=task_manager._coerce_snapshot(record.progress_snapshot),
            result=record.result,
        )
    )


# ---------------------------------------------------------------------------
# GET /{task_id}/stream  (SSE)
# ---------------------------------------------------------------------------

def _sse_line(event_data: dict[str, Any]) -> str:
    return f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"


@router.get("/{task_id}/stream")
async def stream_status(task_id: str) -> StreamingResponse:
    """Server-Sent Events stream for real-time landscape task progress."""
    if task_manager.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")

    async def _event_generator():
        queue = task_manager.subscribe(task_id)

        try:
            # --- Initial catch-up from DB (sent exactly once) ---
            record = task_manager.get_task(task_id)
            if record is None:
                yield _sse_line({
                    "type": "error", "status": "failed",
                    "message": "Task not found",
                })
                return

            yield _sse_line({"type": "status", "status": record.status.value})

            # Replay accumulated stage events so the stepper can reconstruct
            snapshot: dict[str, dict[str, Any]] = task_manager._coerce_snapshot(
                record.progress_snapshot,
            )
            if snapshot:
                stage_events = list(snapshot.values())
                stage_events.sort(
                    key=lambda e: (
                        int(e.get("stage_index") or 999),
                        int(e.get("progress_pct") or 0),
                        str(e.get("stage_id") or ""),
                    ),
                )
                for stage_event in stage_events:
                    yield _sse_line(stage_event)
            elif record.progress_message:
                yield _sse_line({
                    "type": "progress",
                    "message": record.progress_message,
                })

            if record.status == TaskStatus.completed:
                yield _sse_line({
                    "type": "complete", "status": "completed",
                    "result": record.result,
                })
                return

            if record.status == TaskStatus.failed:
                yield _sse_line({
                    "type": "error", "status": "failed",
                    "message": record.progress_message or "Task failed",
                })
                return

            # --- Live stream: only forward queue events ---
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=8)
                except asyncio.TimeoutError:
                    # Heartbeat: check if task finished while we waited
                    record = task_manager.get_task(task_id)
                    if record is None:
                        yield _sse_line({
                            "type": "error", "status": "failed",
                            "message": "Task not found",
                        })
                        break
                    if record.status == TaskStatus.completed:
                        yield _sse_line({
                            "type": "complete", "status": "completed",
                            "result": record.result,
                        })
                        break
                    if record.status == TaskStatus.failed:
                        yield _sse_line({
                            "type": "error", "status": "failed",
                            "message": record.progress_message or "Task failed",
                        })
                        break
                    continue

                yield _sse_line(event)
                if event.get("type") in ("complete", "error"):
                    break
        finally:
            task_manager.unsubscribe(task_id, queue)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
