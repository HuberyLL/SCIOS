"""SQLModel database models and SQLite engine configuration."""

from __future__ import annotations

import enum
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
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Monitoring models
# ---------------------------------------------------------------------------


class MonitorFrequency(str, enum.Enum):
    daily = "daily"
    weekly = "weekly"


class MonitorTask(SQLModel, table=True):
    __tablename__ = "monitor_tasks"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    topic: str
    frequency: MonitorFrequency = Field(
        sa_column=Column(
            SAEnum(MonitorFrequency),
            nullable=False,
            default=MonitorFrequency.daily,
        )
    )
    is_active: bool = True
    notify_email: str | None = None
    last_run_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MonitorBrief(SQLModel, table=True):
    __tablename__ = "monitor_briefs"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    task_id: str = Field(foreign_key="monitor_tasks.id", index=True)
    brief_content: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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


def get_session():
    """Yield a new SQLModel session bound to the singleton engine."""
    with Session(get_engine()) as session:
        yield session
