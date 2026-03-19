"""Assistant-mode database models: sessions and messages."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON
from sqlalchemy import Enum as SAEnum
from sqlmodel import Column, Field, SQLModel


class MessageRole(str, enum.Enum):
    system = "system"
    user = "user"
    assistant = "assistant"
    tool = "tool"


class AssistantSession(SQLModel, table=True):
    __tablename__ = "assistant_sessions"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    title: str = "New Chat"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Memory(SQLModel, table=True):
    """A single long-term fact the assistant remembers across sessions."""

    __tablename__ = "assistant_memories"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    content: str
    category: str = "general"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AssistantMessage(SQLModel, table=True):
    __tablename__ = "assistant_messages"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    session_id: str = Field(foreign_key="assistant_sessions.id", index=True)
    role: MessageRole = Field(
        sa_column=Column(SAEnum(MessageRole), nullable=False)
    )
    content: str = ""
    tool_calls: list[dict[str, Any]] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    tool_call_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
