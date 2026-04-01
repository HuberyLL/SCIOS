"""APScheduler integration for periodic incremental landscape scans.

The scheduler runs inside the FastAPI event loop and is started / stopped
via the application lifespan.  It calls the incremental landscape pipeline
(``run_incremental_scan``) and stores the resulting ``LandscapeIncrement``
as ``MonitorBrief.brief_content``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import Session, col, select

from src.agents.landscape import run_incremental_scan
from src.core.config import get_settings
from src.models.db import MonitorBrief, MonitorTask, TaskRecord, TaskStatus, get_engine

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_monitor_subscribers: list[asyncio.Queue[dict[str, Any]]] = []


def subscribe_monitoring_events() -> asyncio.Queue[dict[str, Any]]:
    """Register a queue consumer for monitoring scheduler events."""
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _monitor_subscribers.append(q)
    return q


def unsubscribe_monitoring_events(q: asyncio.Queue[dict[str, Any]]) -> None:
    """Remove a queue consumer when the SSE connection closes."""
    try:
        _monitor_subscribers.remove(q)
    except ValueError:
        pass


def _publish_monitoring_event(event: dict[str, Any]) -> None:
    """Broadcast event payload to all monitoring SSE subscribers."""
    for q in list(_monitor_subscribers):
        q.put_nowait(event)


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


def _collect_existing_paper_ids(topic: str) -> set[str]:
    """Gather paper_ids from the most recent landscape TaskRecord and
    all prior MonitorBrief increments for *topic*.
    """
    engine = get_engine()
    paper_ids: set[str] = set()

    with Session(engine) as session:
        landscape_task = session.exec(
            select(TaskRecord)
            .where(TaskRecord.topic == topic, TaskRecord.status == TaskStatus.completed)
            .order_by(col(TaskRecord.created_at).desc())
        ).first()
        if landscape_task and landscape_task.result:
            for p in landscape_task.result.get("papers", []):
                pid = p.get("paper_id", "")
                if pid:
                    paper_ids.add(pid)

        task_ids = session.exec(
            select(MonitorTask.id).where(MonitorTask.topic == topic)
        ).all()
        if task_ids:
            briefs = session.exec(
                select(MonitorBrief)
                .where(col(MonitorBrief.task_id).in_(task_ids))
            ).all()
            for brief in briefs:
                for p in brief.brief_content.get("new_papers", []):
                    pid = p.get("paper_id", "")
                    if pid:
                        paper_ids.add(pid)

    return paper_ids


def _collect_existing_node_ids(topic: str) -> list[str]:
    """Get existing tech tree node IDs from the most recent landscape for *topic*."""
    engine = get_engine()
    with Session(engine) as session:
        landscape_task = session.exec(
            select(TaskRecord)
            .where(TaskRecord.topic == topic, TaskRecord.status == TaskStatus.completed)
            .order_by(col(TaskRecord.created_at).desc())
        ).first()
        if landscape_task and landscape_task.result:
            nodes = landscape_task.result.get("tech_tree", {}).get("nodes", [])
            return [n.get("node_id", "") for n in nodes if n.get("node_id")]
    return []


async def run_daily_jobs() -> None:
    """Execute incremental landscape scans for every active ``MonitorTask``.

    For each task the incremental pipeline is invoked, the resulting
    ``LandscapeIncrement`` is persisted as ``MonitorBrief.brief_content``
    and an ``increment_ready`` SSE event is broadcast.
    """
    engine = get_engine()

    with Session(engine) as session:
        tasks = session.exec(
            select(MonitorTask).where(MonitorTask.is_active == True)  # noqa: E712
        ).all()

    if not tasks:
        logger.info("No active monitor tasks — skipping run")
        return

    logger.info("Running incremental scans for %d task(s)", len(tasks))

    for task in tasks:
        since = _compute_since_date(task)
        _publish_monitoring_event({
            "type": "task_started",
            "task_id": task.id,
            "topic": task.topic,
            "since_date": since,
            "at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            existing_ids = _collect_existing_paper_ids(task.topic)
            existing_nodes = _collect_existing_node_ids(task.topic)

            increment = await run_incremental_scan(
                topic=task.topic,
                since_date=since.split("-")[0],
                existing_paper_ids=existing_ids,
                existing_node_ids=existing_nodes,
                keywords=[task.topic],
            )
        except Exception:
            logger.exception("Incremental scan failed for task %s", task.id)
            _publish_monitoring_event({
                "type": "task_failed",
                "task_id": task.id,
                "topic": task.topic,
                "at": datetime.now(timezone.utc).isoformat(),
            })
            continue

        increment_dict = increment.model_dump(mode="json")
        if _is_empty_increment(increment_dict):
            logger.info("No incremental delta for task %s (topic=%s)", task.id, task.topic)
            with Session(engine) as session:
                db_task = session.get(MonitorTask, task.id)
                if db_task is not None:
                    db_task.last_run_at = datetime.now(timezone.utc)
                    db_task.updated_at = datetime.now(timezone.utc)
                    session.add(db_task)
                    session.commit()
            continue

        with Session(engine) as session:
            record = MonitorBrief(
                task_id=task.id,
                brief_content=increment_dict,
            )
            session.add(record)

            db_task = session.get(MonitorTask, task.id)
            if db_task is not None:
                db_task.last_run_at = datetime.now(timezone.utc)
                db_task.updated_at = datetime.now(timezone.utc)
                session.add(db_task)

            session.commit()

        logger.info("Stored increment for task %s (topic=%s)", task.id, task.topic)
        _publish_monitoring_event({
            "type": "increment_ready",
            "increment_id": record.id,
            "task_id": task.id,
            "topic": task.topic,
            "increment": increment_dict,
            "at": datetime.now(timezone.utc).isoformat(),
        })


def _compute_since_date(task: MonitorTask) -> str:
    """Determine the start date for the monitoring window."""
    if task.last_run_at is not None:
        return task.last_run_at.strftime("%Y-%m-%d")
    if task.frequency.value == "weekly":
        return (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def start_scheduler() -> None:
    """Create and start the ``AsyncIOScheduler``."""
    global _scheduler

    cfg = get_settings()
    _scheduler = AsyncIOScheduler()

    if cfg.monitoring_interval_minutes is not None:
        trigger = IntervalTrigger(minutes=cfg.monitoring_interval_minutes)
        label = f"every {cfg.monitoring_interval_minutes} min"
    else:
        trigger = CronTrigger(hour=cfg.monitoring_cron_hour, minute=cfg.monitoring_cron_minute)
        label = f"daily at {cfg.monitoring_cron_hour:02d}:{cfg.monitoring_cron_minute:02d}"

    _scheduler.add_job(
        run_daily_jobs,
        trigger=trigger,
        id="monitoring_daily",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Monitoring scheduler started (%s)", label)


def shutdown_scheduler() -> None:
    """Gracefully shut down the scheduler if it is running."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        logger.info("Monitoring scheduler stopped")
        _scheduler = None
