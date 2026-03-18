"""Monitoring API — CRUD for monitor tasks and their generated briefs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from src.models.db import MonitorBrief, MonitorFrequency, MonitorTask, get_engine

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class CreateMonitorRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    frequency: str = Field(default="daily", pattern=r"^(daily|weekly)$")
    notify_email: str | None = None


class MonitorTaskData(BaseModel):
    id: str
    topic: str
    frequency: str
    is_active: bool
    notify_email: str | None
    last_run_at: str | None
    created_at: str


class MonitorTaskResponse(BaseModel):
    data: MonitorTaskData
    meta: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class MonitorTaskListResponse(BaseModel):
    data: list[MonitorTaskData]
    meta: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class BriefData(BaseModel):
    id: str
    task_id: str
    brief_content: dict[str, Any]
    created_at: str


class BriefListResponse(BaseModel):
    data: list[BriefData]
    meta: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task_to_data(t: MonitorTask) -> MonitorTaskData:
    return MonitorTaskData(
        id=t.id,
        topic=t.topic,
        frequency=t.frequency.value if isinstance(t.frequency, MonitorFrequency) else t.frequency,
        is_active=t.is_active,
        notify_email=t.notify_email,
        last_run_at=t.last_run_at.isoformat() if t.last_run_at else None,
        created_at=t.created_at.isoformat(),
    )


def _brief_to_data(b: MonitorBrief) -> BriefData:
    return BriefData(
        id=b.id,
        task_id=b.task_id,
        brief_content=b.brief_content,
        created_at=b.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# POST /tasks — create a monitoring subscription
# ---------------------------------------------------------------------------


@router.post("/tasks", response_model=MonitorTaskResponse, status_code=201)
async def create_monitor_task(body: CreateMonitorRequest) -> MonitorTaskResponse:
    """Create a new monitoring task (subscription)."""
    task = MonitorTask(
        topic=body.topic,
        frequency=MonitorFrequency(body.frequency),
        notify_email=body.notify_email,
    )
    with Session(get_engine()) as session:
        session.add(task)
        session.commit()
        session.refresh(task)
        return MonitorTaskResponse(data=_task_to_data(task))


# ---------------------------------------------------------------------------
# GET /tasks — list all subscriptions
# ---------------------------------------------------------------------------


@router.get("/tasks", response_model=MonitorTaskListResponse)
async def list_monitor_tasks() -> MonitorTaskListResponse:
    """Return all monitoring subscriptions."""
    with Session(get_engine()) as session:
        tasks = session.exec(select(MonitorTask)).all()
        return MonitorTaskListResponse(
            data=[_task_to_data(t) for t in tasks],
            meta={"total": len(tasks)},
        )


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}/briefs — list briefs for a subscription
# ---------------------------------------------------------------------------


@router.get("/tasks/{task_id}/briefs", response_model=BriefListResponse)
async def list_briefs(task_id: str) -> BriefListResponse:
    """Return all generated briefs for a given monitoring task."""
    with Session(get_engine()) as session:
        task = session.get(MonitorTask, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Monitor task not found")

        briefs = session.exec(
            select(MonitorBrief)
            .where(MonitorBrief.task_id == task_id)
            .order_by(MonitorBrief.created_at.desc())  # type: ignore[union-attr]
        ).all()

        return BriefListResponse(
            data=[_brief_to_data(b) for b in briefs],
            meta={"total": len(briefs)},
        )
