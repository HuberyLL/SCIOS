"""SQLModel database models and SQLite engine configuration."""

from __future__ import annotations

import enum
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import JSON
from sqlalchemy import Enum as SAEnum
from sqlmodel import Column, Field, Session, SQLModel, create_engine

from src.core.config import get_settings
from src.models.assistant import AssistantMessage, AssistantSession  # noqa: F401

_engine = None
logger = logging.getLogger(__name__)


class TaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class TaskRecord(SQLModel, table=True):
    __tablename__ = "task_records"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    topic: str
    status: TaskStatus = Field(
        sa_column=Column(SAEnum(TaskStatus), nullable=False, default=TaskStatus.pending)
    )
    progress_message: str = ""
    progress_snapshot: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON),
        description="Latest structured progress event for SSE catch-up on reconnect.",
    )
    current_stage_id: str = Field(
        default="",
        description="Last reported stage_id from structured progress events.",
    )
    current_progress_pct: int = Field(
        default=0,
        description="Last reported overall pipeline progress percentage (0-100).",
    )
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PipelineCheckpoint(SQLModel, table=True):
    """Stores intermediate stage outputs so the pipeline can resume after a crash."""

    __tablename__ = "pipeline_checkpoints"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    task_id: str = Field(index=True)
    stage: str  # "scope", "retrieval", "taxonomy", "network", "gaps"
    data_json: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TopicSnapshot(SQLModel, table=True):
    """Lightweight index for cross-run topic memory (Layer 3).

    Full paper data lives in the linked ``TaskRecord.result``; this table
    only keeps lightweight metadata for quick lookup and warm-start decisions.
    """

    __tablename__ = "topic_snapshots"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    topic_normalized: str = Field(index=True)
    topic_original: str = ""
    scope_json: str = ""
    corpus_stats_json: str = ""
    landscape_task_id: str = ""
    paper_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def get_engine():
    """Return the singleton SQLite engine, creating the data directory if needed."""
    global _engine
    if _engine is None:
        db_path = Path(get_settings().db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
    return _engine


def apply_lightweight_migrations(engine) -> None:
    """Apply idempotent runtime DB migrations for backward compatibility.

    This project currently uses ``SQLModel.metadata.create_all()`` without a
    full migration framework. For existing SQLite files, ``create_all`` does
    not add newly introduced columns to existing tables. This helper patches
    those schema gaps safely at startup.
    """
    with engine.begin() as conn:
        table_row = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='task_records'",
        ).fetchone()
        if table_row is None:
            return

        columns = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(task_records)").fetchall()
        }

        if "progress_snapshot" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE task_records ADD COLUMN progress_snapshot JSON",
            )
            logger.info(
                "Applied lightweight DB migration: added task_records.progress_snapshot",
            )

        if "current_stage_id" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE task_records ADD COLUMN current_stage_id TEXT DEFAULT ''",
            )
            logger.info(
                "Applied lightweight DB migration: added task_records.current_stage_id",
            )

        if "current_progress_pct" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE task_records ADD COLUMN current_progress_pct INTEGER DEFAULT 0",
            )
            logger.info(
                "Applied lightweight DB migration: added task_records.current_progress_pct",
            )


def get_session():
    """Yield a new SQLModel session bound to the singleton engine."""
    with Session(get_engine()) as session:
        yield session
