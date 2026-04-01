"""Landscape API — start DRL tasks, poll status, stream via SSE,
subscribe to incremental monitoring, and retrieve increments."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select
from starlette.responses import StreamingResponse

from src.models.db import (
    MonitorBrief,
    MonitorFrequency,
    MonitorTask,
    TaskStatus,
    get_engine,
)
from src.services import task_manager
from src.services.scheduler import (
    subscribe_monitoring_events,
    unsubscribe_monitoring_events,
)

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
    result: dict[str, Any] | None = None


class TaskStatusResponse(BaseModel):
    data: TaskStatusData
    meta: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


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


# ===========================================================================
# Subscription & incremental monitoring endpoints
# ===========================================================================


def _to_iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _is_empty_increment(payload: dict[str, Any]) -> bool:
    """Return True when an increment contains no actionable delta."""
    return not any(
        payload.get(key)
        for key in (
            "new_papers",
            "new_tech_nodes",
            "new_tech_edges",
            "new_scholars",
            "new_collab_edges",
            "new_comparisons",
            "new_gaps",
        )
    )


# -- request / response schemas --

class SubscribeRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    frequency: str = Field(default="daily", pattern=r"^(daily|weekly)$")


class SubscriptionData(BaseModel):
    id: str
    topic: str
    frequency: str
    is_active: bool
    last_run_at: str | None = None
    created_at: str


class SubscriptionResponse(BaseModel):
    data: SubscriptionData
    error: str | None = None


class SubscriptionCheckResponse(BaseModel):
    subscribed: bool
    data: SubscriptionData | None = None
    error: str | None = None


class IncrementData(BaseModel):
    id: str
    task_id: str
    increment: dict[str, Any]
    created_at: str


class IncrementListResponse(BaseModel):
    data: list[IncrementData]
    meta: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class DeleteSubscriptionData(BaseModel):
    id: str
    deleted: bool


class DeleteSubscriptionResponse(BaseModel):
    data: DeleteSubscriptionData
    error: str | None = None


def _task_to_subscription(t: MonitorTask) -> SubscriptionData:
    return SubscriptionData(
        id=t.id,
        topic=t.topic,
        frequency=t.frequency.value if isinstance(t.frequency, MonitorFrequency) else t.frequency,
        is_active=t.is_active,
        last_run_at=_to_iso_utc(t.last_run_at) if t.last_run_at else None,
        created_at=_to_iso_utc(t.created_at),
    )


# ---------------------------------------------------------------------------
# POST /subscribe
# ---------------------------------------------------------------------------

@router.post("/subscribe", response_model=SubscriptionResponse, status_code=201)
async def subscribe_landscape(body: SubscribeRequest) -> SubscriptionResponse:
    """Create an incremental-monitoring subscription for a topic."""
    task = MonitorTask(
        topic=body.topic,
        frequency=MonitorFrequency(body.frequency),
    )
    with Session(get_engine()) as session:
        session.add(task)
        session.commit()
        session.refresh(task)
        return SubscriptionResponse(data=_task_to_subscription(task))


# ---------------------------------------------------------------------------
# GET /subscription?topic=X
# ---------------------------------------------------------------------------

@router.get("/subscription", response_model=SubscriptionCheckResponse)
async def get_subscription(
    topic: str = Query(..., min_length=1),
    response: Response = None,  # type: ignore[assignment]
) -> SubscriptionCheckResponse:
    """Check whether a topic has an active subscription."""
    if response is not None:
        response.headers["Cache-Control"] = "no-store"
    with Session(get_engine()) as session:
        task = session.exec(
            select(MonitorTask).where(
                MonitorTask.topic == topic,
                MonitorTask.is_active == True,  # noqa: E712
            )
        ).first()
        if task is None:
            return SubscriptionCheckResponse(subscribed=False)
        return SubscriptionCheckResponse(
            subscribed=True,
            data=_task_to_subscription(task),
        )


# ---------------------------------------------------------------------------
# DELETE /subscribe/{task_id}
# ---------------------------------------------------------------------------

@router.delete("/subscribe/{task_id}", response_model=DeleteSubscriptionResponse)
async def unsubscribe_landscape(task_id: str) -> DeleteSubscriptionResponse:
    """Delete a monitoring subscription and its stored increments."""
    with Session(get_engine()) as session:
        task = session.get(MonitorTask, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Subscription not found")

        briefs = session.exec(
            select(MonitorBrief).where(MonitorBrief.task_id == task_id)
        ).all()
        for b in briefs:
            session.delete(b)
        session.delete(task)
        session.commit()

    return DeleteSubscriptionResponse(
        data=DeleteSubscriptionData(id=task_id, deleted=True),
    )


# ---------------------------------------------------------------------------
# GET /increments?topic=X&since=ISO
# ---------------------------------------------------------------------------

@router.get("/increments", response_model=IncrementListResponse)
async def list_increments(
    topic: str = Query(..., min_length=1),
    since: str | None = Query(default=None),
    response: Response = None,  # type: ignore[assignment]
) -> IncrementListResponse:
    """Return stored ``LandscapeIncrement`` entries for a topic."""
    if response is not None:
        response.headers["Cache-Control"] = "no-store"

    with Session(get_engine()) as session:
        task_ids = session.exec(
            select(MonitorTask.id).where(MonitorTask.topic == topic)
        ).all()
        if not task_ids:
            return IncrementListResponse(data=[], meta={"total": 0})

        stmt = (
            select(MonitorBrief)
            .where(col(MonitorBrief.task_id).in_(task_ids))
            .order_by(col(MonitorBrief.created_at).asc())
        )
        if since:
            try:
                since_dt = datetime.fromisoformat(since)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid 'since' ISO timestamp")
            stmt = stmt.where(MonitorBrief.created_at >= since_dt)

        briefs = session.exec(stmt).all()
        data = [
            IncrementData(
                id=b.id,
                task_id=b.task_id,
                increment=b.brief_content,
                created_at=_to_iso_utc(b.created_at),
            )
            for b in briefs
            if not _is_empty_increment(b.brief_content)
        ]
        return IncrementListResponse(data=data, meta={"total": len(data)})


# ---------------------------------------------------------------------------
# GET /monitor-stream  (SSE for increment_ready events)
# ---------------------------------------------------------------------------

@router.get("/monitor-stream")
async def monitor_stream() -> StreamingResponse:
    """SSE stream relaying ``increment_ready`` events from the scheduler."""

    async def _event_generator():
        q = subscribe_monitoring_events()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=20)
                except asyncio.TimeoutError:
                    yield _sse_line({"type": "ping"})
                    continue
                yield _sse_line(event)
        finally:
            unsubscribe_monitoring_events(q)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
