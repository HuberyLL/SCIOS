"""Unit tests for AssistantRunner agent loop behavior."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any

import pytest
from sqlmodel import Session, select

import src.agents.assistant.tools  # noqa: F401 - ensure built-in tools are registered
from src.agents.assistant.runner import AssistantRunner
from src.models.assistant import AssistantMessage, AssistantSession
from src.models.db import get_engine


def _chunk(
    *,
    content: str | None = None,
    tool_calls: list[Any] | None = None,
    finish_reason: str | None = None,
) -> Any:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=tool_calls),
                finish_reason=finish_reason,
            )
        ]
    )


def _tool_delta(index: int, tool_call_id: str, name: str, arguments: str) -> Any:
    return SimpleNamespace(
        index=index,
        id=tool_call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


async def _to_async_iter(chunks: list[Any]) -> AsyncGenerator[Any, None]:
    for chunk in chunks:
        yield chunk


@pytest.mark.asyncio
async def test_runner_persists_messages_and_updates_session_timestamp(mocker) -> None:
    session = AssistantSession(title="Runner Test")
    with Session(get_engine()) as db:
        db.add(session)
        db.commit()
        db.refresh(session)
        initial_updated_at = session.updated_at

    round_1 = [
        _chunk(
            tool_calls=[
                _tool_delta(
                    index=0,
                    tool_call_id="call_1",
                    name="get_system_time",
                    arguments='{"timezone":"UTC"}',
                )
            ],
            finish_reason="tool_calls",
        )
    ]
    round_2 = [
        _chunk(content="The current UTC time has been fetched."),
        _chunk(finish_reason="stop"),
    ]

    mocker.patch(
        "litellm.acompletion",
        side_effect=[
            _to_async_iter(round_1),
            _to_async_iter(round_2),
        ],
    )

    runner = AssistantRunner(session.id)
    events = [event async for event in runner.stream_chat("What time is it now?")]
    event_types = [event["event"] for event in events]
    assert "tool_call_start" in event_types
    assert "tool_call_result" in event_types
    assert "text_delta" in event_types
    assert event_types[-1] == "message_complete"

    with Session(get_engine()) as db:
        saved_session = db.get(AssistantSession, session.id)
        assert saved_session is not None
        assert saved_session.updated_at >= initial_updated_at

        rows = db.exec(
            select(AssistantMessage)
            .where(AssistantMessage.session_id == session.id)
            .order_by(AssistantMessage.created_at)  # type: ignore[arg-type]
        ).all()
        roles = [row.role.value for row in rows]
        assert roles.count("user") == 1
        assert "tool" in roles
        assert roles.count("assistant") >= 1


@pytest.mark.asyncio
async def test_runner_reports_invalid_tool_json_arguments(mocker) -> None:
    session = AssistantSession(title="Invalid Args Test")
    with Session(get_engine()) as db:
        db.add(session)
        db.commit()
        db.refresh(session)

    round_1 = [
        _chunk(
            tool_calls=[
                _tool_delta(
                    index=0,
                    tool_call_id="call_bad_json",
                    name="get_system_time",
                    arguments='{"timezone":"UTC"',
                )
            ],
            finish_reason="tool_calls",
        )
    ]
    round_2 = [
        _chunk(content="I could not parse the tool arguments."),
        _chunk(finish_reason="stop"),
    ]

    mocker.patch(
        "litellm.acompletion",
        side_effect=[
            _to_async_iter(round_1),
            _to_async_iter(round_2),
        ],
    )

    runner = AssistantRunner(session.id)
    events = [event async for event in runner.stream_chat("Use tool with invalid args")]
    tool_results = [e for e in events if e["event"] == "tool_call_result"]

    assert len(tool_results) == 1
    result_text = tool_results[0]["data"]["result"]
    assert "invalid JSON arguments" in result_text


@pytest.mark.asyncio
async def test_runner_auto_updates_default_session_title_on_first_user_message(mocker) -> None:
    session = AssistantSession(title="New Chat")
    with Session(get_engine()) as db:
        db.add(session)
        db.commit()
        db.refresh(session)

    round_1 = [
        _chunk(content="Done."),
        _chunk(finish_reason="stop"),
    ]

    mocker.patch(
        "litellm.acompletion",
        side_effect=[
            _to_async_iter(round_1),
        ],
    )

    runner = AssistantRunner(session.id)
    user_input = "Write a small experiment script for image classification"
    _ = [event async for event in runner.stream_chat(user_input)]

    with Session(get_engine()) as db:
        saved = db.get(AssistantSession, session.id)
        assert saved is not None
        assert saved.title != "New Chat"
        assert saved.title.startswith("Write a small experiment script")
