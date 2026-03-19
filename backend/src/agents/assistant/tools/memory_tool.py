"""Tool that lets the LLM persist or remove long-term memory facts."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel
from sqlmodel import Session, select

from src.agents.assistant.tools.base import BaseTool
from src.models.assistant import Memory
from src.models.db import get_engine

logger = logging.getLogger(__name__)


class UpdateMemoryArgs(BaseModel):
    action: Literal["add", "delete"]
    content: str = ""
    category: str = "general"
    memory_id: str = ""


class UpdateMemoryTool(BaseTool):
    name = "update_memory"
    description = (
        "Save or delete a long-term memory fact about the user that persists "
        "across sessions. Use action='add' to store a new fact (e.g. research "
        "interests, language preferences, formatting rules). Use "
        "action='delete' with memory_id to remove an outdated fact. "
        "Recommended categories: 'preference', 'research_topic', 'general'."
    )
    args_schema = UpdateMemoryArgs

    async def execute(self, **kwargs: Any) -> str:
        args = UpdateMemoryArgs.model_validate(kwargs)

        if args.action == "add":
            return self._add(args.content, args.category)
        if args.action == "delete":
            return self._delete(args.memory_id)
        return f"Error: unknown action '{args.action}'"

    @staticmethod
    def _add(content: str, category: str) -> str:
        if not content.strip():
            return "Error: content must not be empty for action='add'."
        now = datetime.now(timezone.utc)
        mem = Memory(
            content=content.strip(),
            category=category.strip() or "general",
            created_at=now,
            updated_at=now,
        )
        with Session(get_engine()) as db:
            db.add(mem)
            db.commit()
            db.refresh(mem)
        logger.info("Memory added id=%s category=%s", mem.id, mem.category)
        return f"Memory saved (id={mem.id[:8]}): {mem.content}"

    @staticmethod
    def _delete(memory_id: str) -> str:
        if not memory_id.strip():
            return "Error: memory_id must not be empty for action='delete'."
        prefix = memory_id.strip()
        with Session(get_engine()) as db:
            stmt = select(Memory).where(Memory.id.startswith(prefix))
            matches = list(db.exec(stmt).all())
            if not matches:
                return f"Error: no memory found with id starting with '{memory_id}'."
            if len(matches) > 1:
                options = ", ".join(m.id[:8] for m in matches[:5])
                return (
                    "Error: ambiguous memory_id prefix; multiple matches found. "
                    f"Use a longer id. Matches: {options}"
                )
            mem = matches[0]
            full_id = mem.id
            db.delete(mem)
            db.commit()
        logger.info("Memory deleted id=%s", full_id)
        return f"Memory deleted (id={full_id[:8]})."
