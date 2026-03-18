"""APScheduler integration for periodic monitoring scans.

The scheduler runs inside the FastAPI event loop and is started / stopped
via the application lifespan.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import Session, select

from src.agents.monitoring import run_monitoring_scan
from src.core.config import get_settings
from src.models.db import MonitorBrief, MonitorTask, get_engine
from src.services.notification import send_daily_brief_email

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def run_daily_jobs() -> None:
    """Execute monitoring scans for every active ``MonitorTask``.

    For each task the pipeline is invoked, the resulting brief is persisted
    and ``last_run_at`` is updated.
    """
    engine = get_engine()

    with Session(engine) as session:
        tasks = session.exec(
            select(MonitorTask).where(MonitorTask.is_active == True)  # noqa: E712
        ).all()

    if not tasks:
        logger.info("No active monitor tasks — skipping run")
        return

    logger.info("Running monitoring jobs for %d task(s)", len(tasks))

    for task in tasks:
        since = _compute_since_date(task)
        try:
            brief = await run_monitoring_scan(task.topic, since)
        except Exception:
            logger.exception("Monitoring scan failed for task %s", task.id)
            continue

        with Session(engine) as session:
            record = MonitorBrief(
                task_id=task.id,
                brief_content=brief.model_dump(mode="json"),
            )
            session.add(record)

            db_task = session.get(MonitorTask, task.id)
            if db_task is not None:
                db_task.last_run_at = datetime.now(timezone.utc)
                db_task.updated_at = datetime.now(timezone.utc)
                session.add(db_task)

            session.commit()

        logger.info("Stored brief for task %s (topic=%s)", task.id, task.topic)

        recipient = task.notify_email or get_settings().notification_email
        if recipient:
            await send_daily_brief_email(brief, recipient)


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
