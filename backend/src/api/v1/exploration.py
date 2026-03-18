"""Exploration API — start tasks, poll status, or stream via SSE."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from src.models.db import TaskStatus
from src.services import task_manager

router = APIRouter(prefix="/api/v1/exploration", tags=["exploration"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class StartRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)


class StartResponse(BaseModel):
    data: _StartData
    meta: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class _StartData(BaseModel):
    task_id: str


class TaskStatusData(BaseModel):
    task_id: str
    status: TaskStatus
    progress_message: str
    result: dict[str, Any] | None = None


class TaskStatusResponse(BaseModel):
    data: TaskStatusData
    meta: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


# Reorder so StartResponse can reference _StartData via forward ref
StartResponse.model_rebuild()


# ---------------------------------------------------------------------------
# POST /start
# ---------------------------------------------------------------------------

@router.post("/start", response_model=StartResponse, status_code=202)
async def start_exploration(
    body: StartRequest,
    background_tasks: BackgroundTasks,
) -> StartResponse:
    """Create an exploration task and run the pipeline in the background."""
    task_id = task_manager.create_task(body.topic)
    background_tasks.add_task(task_manager.run_exploration_task, task_id, body.topic)
    return StartResponse(data=_StartData(task_id=task_id))


# ---------------------------------------------------------------------------
# GET /{task_id}/status
# ---------------------------------------------------------------------------

@router.get("/{task_id}/status", response_model=TaskStatusResponse)
async def get_status(task_id: str) -> TaskStatusResponse:
    """Return the current snapshot of a task (status, progress, result)."""
    record = task_manager.get_task(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskStatusResponse(
        data=TaskStatusData(
            task_id=record.id,
            status=record.status,
            progress_message=record.progress_message,
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
    """Server-Sent Events stream for real-time task progress."""
    if task_manager.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")

    async def _event_generator():
        # Subscribe first, then always push a DB snapshot. This avoids race
        # conditions where terminal events are published before subscription.
        queue = task_manager.subscribe(task_id)
        last_status: str | None = None
        last_progress: str | None = None

        try:
            while True:
                record = task_manager.get_task(task_id)
                if record is None:
                    yield _sse_line({
                        "type": "error",
                        "status": "failed",
                        "message": "Task not found",
                    })
                    break

                status_value = record.status.value
                if status_value != last_status:
                    yield _sse_line({"type": "status", "status": status_value})
                    last_status = status_value

                progress_message = record.progress_message or ""
                if progress_message and progress_message != last_progress:
                    yield _sse_line({"type": "progress", "message": progress_message})
                    last_progress = progress_message

                if record.status == TaskStatus.completed:
                    yield _sse_line({
                        "type": "complete",
                        "status": "completed",
                        "result": record.result,
                    })
                    break

                if record.status == TaskStatus.failed:
                    yield _sse_line({
                        "type": "error",
                        "status": "failed",
                        "message": progress_message or "Task failed",
                    })
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=8)
                except asyncio.TimeoutError:
                    # No new queue event in this window; loop back to emit fresh
                    # DB snapshot and keep the stream alive.
                    continue

                yield _sse_line(event)
                if event.get("type") in ("complete", "error"):
                    break
                if event.get("type") == "status":
                    last_status = str(event.get("status"))
                if event.get("type") == "progress":
                    last_progress = str(event.get("message") or "")
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
