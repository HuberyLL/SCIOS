"""Tests for the long-term memory system and context trimming."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from sqlmodel import Session, select

from src.agents.assistant.runner import AssistantRunner
from src.agents.assistant.tools.memory_tool import UpdateMemoryTool
from src.models.assistant import AssistantSession, Memory
from src.models.db import get_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_session() -> AssistantSession:
    s = AssistantSession(title="Test")
    with Session(get_engine()) as db:
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def _add_memory(content: str, category: str = "general") -> Memory:
    now = datetime.now(timezone.utc)
    mem = Memory(content=content, category=category, created_at=now, updated_at=now)
    with Session(get_engine()) as db:
        db.add(mem)
        db.commit()
        db.refresh(mem)
    return mem


# ---------------------------------------------------------------------------
# Memory Model CRUD
# ---------------------------------------------------------------------------

class TestMemoryModel:
    def test_create_and_read(self) -> None:
        mem = _add_memory("User prefers Markdown tables", "preference")
        with Session(get_engine()) as db:
            loaded = db.get(Memory, mem.id)
            assert loaded is not None
            assert loaded.content == "User prefers Markdown tables"
            assert loaded.category == "preference"

    def test_delete(self) -> None:
        mem = _add_memory("Temporary fact")
        with Session(get_engine()) as db:
            loaded = db.get(Memory, mem.id)
            assert loaded is not None
            db.delete(loaded)
            db.commit()
        with Session(get_engine()) as db:
            assert db.get(Memory, mem.id) is None

    def test_list_multiple(self) -> None:
        _add_memory("Fact A")
        _add_memory("Fact B")
        with Session(get_engine()) as db:
            rows = db.exec(select(Memory)).all()
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# update_memory Tool
# ---------------------------------------------------------------------------

class TestUpdateMemoryTool:
    @pytest.mark.asyncio
    async def test_add(self) -> None:
        tool = UpdateMemoryTool()
        result = await tool.execute(
            action="add",
            content="User researches graph neural networks",
            category="research_topic",
        )
        assert "Memory saved" in result
        with Session(get_engine()) as db:
            rows = db.exec(select(Memory)).all()
        assert len(rows) == 1
        assert rows[0].category == "research_topic"

    @pytest.mark.asyncio
    async def test_add_empty_content_rejected(self) -> None:
        tool = UpdateMemoryTool()
        result = await tool.execute(action="add", content="  ", category="general")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_delete_by_prefix(self) -> None:
        mem = _add_memory("Old fact")
        tool = UpdateMemoryTool()
        result = await tool.execute(
            action="delete", memory_id=mem.id[:8]
        )
        assert "deleted" in result
        with Session(get_engine()) as db:
            assert db.get(Memory, mem.id) is None

    @pytest.mark.asyncio
    async def test_delete_not_found(self) -> None:
        tool = UpdateMemoryTool()
        result = await tool.execute(action="delete", memory_id="nonexistent")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_delete_ambiguous_prefix_rejected(self) -> None:
        now = datetime.now(timezone.utc)
        m1 = Memory(
            id="abcd1234aaaaaaaaaaaaaaaaaaaaaaaa",
            content="Fact 1",
            category="general",
            created_at=now,
            updated_at=now,
        )
        m2 = Memory(
            id="abcd5678bbbbbbbbbbbbbbbbbbbbbbbb",
            content="Fact 2",
            category="general",
            created_at=now,
            updated_at=now,
        )
        with Session(get_engine()) as db:
            db.add(m1)
            db.add(m2)
            db.commit()

        tool = UpdateMemoryTool()
        result = await tool.execute(action="delete", memory_id="abcd")
        assert "ambiguous" in result.lower()


# ---------------------------------------------------------------------------
# System Prompt Injection
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    def test_no_memories_returns_base_prompt(self) -> None:
        session = _create_session()
        runner = AssistantRunner(session.id)
        prompt = runner._build_system_prompt()
        assert prompt == runner.system_prompt

    def test_with_memories_appends_facts(self) -> None:
        session = _create_session()
        _add_memory("User likes Chinese summaries", "preference")
        _add_memory("User studies GNN", "research_topic")
        runner = AssistantRunner(session.id)
        prompt = runner._build_system_prompt()
        assert "Known facts about the user" in prompt
        assert "Chinese summaries" in prompt
        assert "GNN" in prompt
        assert "preference" in prompt
        assert "research_topic" in prompt


# ---------------------------------------------------------------------------
# Context Trimming
# ---------------------------------------------------------------------------

def _msg(role: str, content: str, **extra: Any) -> dict[str, Any]:
    """Shortcut to build an OpenAI message dict."""
    m: dict[str, Any] = {"role": role, "content": content}
    m.update(extra)
    return m


class TestContextTrimming:
    def _runner(self) -> AssistantRunner:
        session = _create_session()
        r = AssistantRunner(session.id)
        r.max_context_tokens = 200
        return r

    def test_segment_simple_messages(self) -> None:
        history = [
            _msg("user", "Hello"),
            _msg("assistant", "Hi there"),
            _msg("user", "How are you?"),
        ]
        groups = AssistantRunner._segment_history(history)
        assert len(groups) == 3
        assert all(len(g) == 1 for g in groups)

    def test_segment_tool_call_group(self) -> None:
        history = [
            _msg("user", "Search something"),
            _msg("assistant", "", tool_calls=[{"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": "{}"}}]),
            _msg("tool", "result 1", tool_call_id="c1"),
            _msg("assistant", "Here is the result."),
        ]
        groups = AssistantRunner._segment_history(history)
        assert len(groups) == 3
        assert len(groups[0]) == 1  # user
        assert len(groups[1]) == 2  # assistant+tool
        assert len(groups[2]) == 1  # final assistant

    def test_trim_all_fits(self) -> None:
        r = self._runner()
        r.max_context_tokens = 100_000
        system = "You are a helpful assistant."
        history = [_msg("user", "hi"), _msg("assistant", "hello")]
        trimmed = r._trim_history(system, history)
        assert len(trimmed) == 2

    def test_trim_removes_oldest(self) -> None:
        r = self._runner()
        system = "system"
        sys_tokens = r._count_msg_tokens(_msg("system", system))
        r.max_context_tokens = sys_tokens + 15
        old = _msg("user", "This is a long old message that should be trimmed away")
        new = _msg("user", "short")
        trimmed = r._trim_history(system, [old, new])
        assert len(trimmed) == 1
        assert trimmed[0]["content"] == "short"

    def test_trim_keeps_tool_group_atomic(self) -> None:
        r = self._runner()
        r.max_context_tokens = 100_000
        system = "sys"
        history = [
            _msg("user", "q"),
            _msg("assistant", "", tool_calls=[{"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}]),
            _msg("tool", "r", tool_call_id="c1"),
            _msg("assistant", "answer"),
        ]
        trimmed = r._trim_history(system, history)
        assert len(trimmed) == 4

    def test_trim_drops_tool_group_entirely_when_budget_tight(self) -> None:
        r = self._runner()
        system = "system"
        sys_tokens = r._count_msg_tokens(_msg("system", system))
        r.max_context_tokens = sys_tokens + 30

        big_tool_result = "X" * 500
        history = [
            _msg("assistant", "", tool_calls=[{"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}]),
            _msg("tool", big_tool_result, tool_call_id="c1"),
            _msg("user", "ok"),
        ]
        trimmed = r._trim_history(system, history)
        roles = [m["role"] for m in trimmed]
        assert "tool" not in roles
        assert trimmed[-1]["content"] == "ok"

    def test_trim_empty_budget_returns_empty(self) -> None:
        r = self._runner()
        r.max_context_tokens = 5
        system = "A very long system prompt " * 100
        trimmed = r._trim_history(system, [_msg("user", "hi")])
        assert trimmed == []

    def test_trim_keeps_latest_user_message_when_too_large(self) -> None:
        r = self._runner()
        system = "system"
        sys_tokens = r._count_msg_tokens(_msg("system", system))
        r.max_context_tokens = sys_tokens + 20
        history = [_msg("user", "X" * 3000)]
        trimmed = r._trim_history(system, history)
        assert len(trimmed) == 1
        assert trimmed[0]["role"] == "user"
        assert isinstance(trimmed[0]["content"], str)
        assert len(trimmed[0]["content"]) > 0


# ---------------------------------------------------------------------------
# REST API: memories endpoints
# ---------------------------------------------------------------------------

class TestMemoryAPI:
    @pytest.mark.asyncio
    async def test_list_empty(self, client) -> None:
        resp = await client.get("/api/v1/assistant/memories")
        assert resp.status_code == 200
        assert resp.json()["memories"] == []

    @pytest.mark.asyncio
    async def test_crud_flow(self, client) -> None:
        mem = _add_memory("Fact 1", "preference")

        resp = await client.get("/api/v1/assistant/memories")
        assert resp.status_code == 200
        data = resp.json()["memories"]
        assert len(data) == 1
        assert data[0]["content"] == "Fact 1"

        resp = await client.put(
            f"/api/v1/assistant/memories/{mem.id}",
            json={"content": "Updated fact", "category": "research_topic"},
        )
        assert resp.status_code == 200
        assert resp.json()["content"] == "Updated fact"
        assert resp.json()["category"] == "research_topic"

        resp = await client.delete(f"/api/v1/assistant/memories/{mem.id}")
        assert resp.status_code == 204

        resp = await client.get("/api/v1/assistant/memories")
        assert resp.json()["memories"] == []

    @pytest.mark.asyncio
    async def test_delete_not_found(self, client) -> None:
        resp = await client.delete("/api/v1/assistant/memories/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_put_not_found(self, client) -> None:
        resp = await client.put(
            "/api/v1/assistant/memories/nonexistent",
            json={"content": "x"},
        )
        assert resp.status_code == 404
