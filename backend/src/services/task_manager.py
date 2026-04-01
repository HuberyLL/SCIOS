"""Task lifecycle management: DB CRUD + in-process SSE event bus.

The event bus uses per-task ``asyncio.Queue`` instances so that SSE
endpoints can ``await queue.get()`` without polling the database.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from src.agents.exploration import ExplorationReport, run_exploration
from src.agents.landscape import run_landscape_pipeline
from src.models.db import TaskRecord, TaskStatus, get_engine
from src.models.landscape import DynamicResearchLandscape

logger = logging.getLogger(__name__)

# ---- In-process pub/sub for SSE ----

_subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)


def _publish(task_id: str, event: dict[str, Any]) -> None:
    """Push *event* to every Queue subscribed to *task_id*."""
    for q in _subscribers[task_id]:
        q.put_nowait(event)


def subscribe(task_id: str) -> asyncio.Queue[dict[str, Any]]:
    """Create a new Queue for SSE consumption and register it."""
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _subscribers[task_id].append(q)
    return q


def unsubscribe(task_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
    """Remove a Queue when the SSE connection closes."""
    try:
        _subscribers[task_id].remove(q)
    except ValueError:
        pass
    if not _subscribers[task_id]:
        del _subscribers[task_id]


# ---- DB helpers ----

def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_task(topic: str) -> str:
    """Insert a new *pending* TaskRecord and return its id."""
    record = TaskRecord(topic=topic, status=TaskStatus.pending)
    with Session(get_engine()) as session:
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.id


def get_task(task_id: str) -> TaskRecord | None:
    """Fetch a single task by primary key."""
    with Session(get_engine()) as session:
        return session.get(TaskRecord, task_id)


def list_tasks(limit: int = 50) -> list[TaskRecord]:
    """Return recent landscape tasks ordered by created_at desc."""
    with Session(get_engine()) as session:
        statement = (
            select(TaskRecord)
            .order_by(TaskRecord.created_at.desc())
            .limit(limit)
        )
        return list(session.exec(statement).all())


def delete_task(task_id: str) -> bool:
    """Delete a task record by primary key. Returns True if deleted."""
    with Session(get_engine()) as session:
        record = session.get(TaskRecord, task_id)
        if record is None:
            return False
        session.delete(record)
        session.commit()
        return True


def _update_fields(task_id: str, **kwargs: Any) -> None:
    with Session(get_engine()) as session:
        record = session.get(TaskRecord, task_id)
        if record is None:
            return
        for key, value in kwargs.items():
            setattr(record, key, value)
        record.updated_at = _now()
        session.add(record)
        session.commit()


def update_task_progress(task_id: str, message: str) -> None:
    """Update the progress_message column and notify SSE subscribers."""
    _update_fields(task_id, progress_message=message)
    _publish(task_id, {"type": "progress", "message": message})


# ---- Background runner ----

async def run_exploration_task(task_id: str, topic: str) -> None:
    """Execute the exploration pipeline, persisting state to the DB.

    Designed to be called via ``BackgroundTasks.add_task()``.
    """
    _update_fields(task_id, status=TaskStatus.running)
    _publish(task_id, {"type": "status", "status": "running"})

    async def _on_progress(msg: str) -> None:
        update_task_progress(task_id, msg)

    try:
        report: ExplorationReport = await run_exploration(
            topic, on_progress=_on_progress,
        )
        result_dict = report.model_dump(mode="json")

        _update_fields(
            task_id,
            status=TaskStatus.completed,
            progress_message="Exploration completed",
            result=result_dict,
        )
        _publish(task_id, {
            "type": "complete",
            "status": "completed",
            "result": result_dict,
        })

    except Exception:
        logger.exception("Exploration task %s failed", task_id)
        _update_fields(
            task_id,
            status=TaskStatus.failed,
            progress_message="Task failed due to an internal error",
        )
        _publish(task_id, {
            "type": "error",
            "status": "failed",
            "message": "Task failed due to an internal error",
        })


async def run_landscape_task(task_id: str, topic: str) -> None:
    """Execute the DRL landscape pipeline, persisting state to the DB.

    Designed to be called via ``BackgroundTasks.add_task()``.
    """
    _update_fields(task_id, status=TaskStatus.running)
    _publish(task_id, {"type": "status", "status": "running"})

    async def _on_progress(msg: str) -> None:
        update_task_progress(task_id, msg)

    try:
        landscape: DynamicResearchLandscape = await run_landscape_pipeline(
            topic, on_progress=_on_progress,
        )
        result_dict = landscape.model_dump(mode="json")

        _update_fields(
            task_id,
            status=TaskStatus.completed,
            progress_message="Landscape analysis completed",
            result=result_dict,
        )
        _publish(task_id, {
            "type": "complete",
            "status": "completed",
            "result": result_dict,
        })

    except Exception:
        logger.exception("Landscape task %s failed", task_id)
        _update_fields(
            task_id,
            status=TaskStatus.failed,
            progress_message="Task failed due to an internal error",
        )
        _publish(task_id, {
            "type": "error",
            "status": "failed",
            "message": "Task failed due to an internal error",
        })
