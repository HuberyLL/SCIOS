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

from src.agents.landscape import run_landscape_pipeline
from src.models.db import TaskRecord, TaskStatus, get_engine
from src.models.landscape import DynamicResearchLandscape

logger = logging.getLogger(__name__)

# ---- In-process pub/sub for SSE ----

_subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)
_STAGE_ORDER: dict[str, int] = {
    "scope": 1,
    "retrieval": 2,
    "taxonomy": 3,
    "network": 4,
    "gaps": 4,
    "critic": 5,
    "assembler": 6,
}


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


def _coerce_snapshot(raw: Any) -> dict[str, dict[str, Any]]:
    """Normalize DB JSON payload into a dict[str, event-dict]."""
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    elif isinstance(raw, dict):
        parsed = raw
    else:
        return {}

    if not isinstance(parsed, dict):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for key, value in parsed.items():
        if isinstance(key, str) and isinstance(value, dict):
            result[key] = dict(value)
    return result


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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


def update_task_progress(task_id: str, event: dict[str, Any]) -> None:
    """Persist both the human-readable message and the accumulated stage snapshot,
    then push the complete event to SSE subscribers.

    ``progress_snapshot`` is a dict mapping ``stage_id`` to the latest event for
    that stage.  On SSE reconnect the endpoint replays these events so the
    frontend can fully reconstruct the pipeline stepper state.
    """
    message = str(event.get("message", ""))
    event = dict(event)
    event.setdefault("type", "progress")

    stage_id = event.get("stage_id")
    if stage_id:
        with Session(get_engine()) as session:
            record = session.get(TaskRecord, task_id)
            if record is not None:
                snapshot = _coerce_snapshot(record.progress_snapshot)
                snapshot[str(stage_id)] = dict(event)

                stage_rank = _STAGE_ORDER.get(str(stage_id), 0)
                current_rank = _STAGE_ORDER.get(record.current_stage_id or "", 0)
                incoming_pct = _safe_int(event.get("progress_pct"), record.current_progress_pct)
                bounded_pct = max(0, min(100, incoming_pct))

                record.progress_message = message
                record.progress_snapshot = snapshot
                if stage_rank >= current_rank:
                    record.current_stage_id = str(stage_id)
                record.current_progress_pct = max(record.current_progress_pct, bounded_pct)
                record.updated_at = _now()
                session.add(record)
                session.commit()
    else:
        _update_fields(task_id, progress_message=message)

    _publish(task_id, event)


# ---- Background runner ----

async def run_landscape_task(task_id: str, topic: str) -> None:
    """Execute the DRL landscape pipeline, persisting state to the DB.

    Designed to be called via ``BackgroundTasks.add_task()``.
    """
    _update_fields(
        task_id,
        status=TaskStatus.running,
        current_stage_id="",
        current_progress_pct=0,
        progress_snapshot={},
    )
    _publish(task_id, {"type": "status", "status": "running"})

    async def _on_progress(event: dict[str, Any]) -> None:
        update_task_progress(task_id, event)

    try:
        landscape: DynamicResearchLandscape = await run_landscape_pipeline(
            topic, task_id=task_id, on_progress=_on_progress,
        )
        result_dict = landscape.model_dump(mode="json")

        _update_fields(
            task_id,
            status=TaskStatus.completed,
            progress_message="Landscape analysis completed",
            current_stage_id="assembler",
            current_progress_pct=100,
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
