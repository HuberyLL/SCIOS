"""Integration tests for TaskManager CRUD, pub/sub, and API routes.

All tests run against an in-memory SQLite database (see conftest._test_db).
The exploration pipeline is mocked so no real LLM / network calls are made.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from src.agents.exploration.schemas import (
    CoreConcept,
    ExplorationReport,
    RecommendedPaper,
    ScholarProfile,
    TrendsAndChallenges,
)
from src.models.db import TaskStatus
from src.services import task_manager
from src.services.task_manager import (
    _publish,
    _subscribers,
    _update_fields,
    create_task,
    get_task,
    subscribe,
    unsubscribe,
    update_task_progress,
)

# ---------------------------------------------------------------------------
# Shared fake data
# ---------------------------------------------------------------------------

FAKE_REPORT = ExplorationReport(
    topic="test-topic",
    core_concepts=[CoreConcept(term="AI", explanation="Artificial Intelligence")],
    key_scholars=[
        ScholarProfile(
            name="A. Turing",
            affiliation="Cambridge",
            representative_works=["On Computable Numbers"],
            contribution_summary="Father of CS",
        ),
    ],
    must_read_papers=[
        RecommendedPaper(
            title="Attention Is All You Need",
            authors=["Vaswani et al."],
            year=2017,
            venue="NeurIPS",
            citation_count=50000,
            summary="Introduced the Transformer architecture",
            url="https://arxiv.org/abs/1706.03762",
        ),
    ],
    trends_and_challenges=TrendsAndChallenges(
        recent_progress="Large Language Models",
        emerging_trends=["Multimodal AI"],
        open_challenges=["Alignment"],
        future_directions="Towards AGI",
    ),
    sources=["https://example.com"],
)


# ===================================================================
# TaskManager — CRUD
# ===================================================================

class TestTaskManagerCRUD:
    def test_create_and_get(self):
        task_id = create_task("Quantum Computing")
        record = get_task(task_id)
        assert record is not None
        assert record.topic == "Quantum Computing"
        assert record.status == TaskStatus.pending
        assert record.progress_message == ""
        assert record.result is None

    def test_get_returns_none_for_unknown_id(self):
        assert get_task("nonexistent") is None

    def test_update_progress(self):
        task_id = create_task("NLP")
        update_task_progress(task_id, "Stage 1 done")
        record = get_task(task_id)
        assert record.progress_message == "Stage 1 done"
        assert record.updated_at >= record.created_at

    def test_update_fields_sets_status(self):
        task_id = create_task("CV")
        _update_fields(task_id, status=TaskStatus.running)
        assert get_task(task_id).status == TaskStatus.running


# ===================================================================
# TaskManager — Pub/Sub
# ===================================================================

class TestPubSub:
    async def test_subscribe_receives_published_event(self):
        task_id = create_task("test")
        queue = subscribe(task_id)
        _publish(task_id, {"type": "progress", "message": "hello"})
        event = queue.get_nowait()
        assert event == {"type": "progress", "message": "hello"}

    async def test_multiple_subscribers(self):
        task_id = create_task("test")
        q1 = subscribe(task_id)
        q2 = subscribe(task_id)
        _publish(task_id, {"type": "progress", "message": "x"})
        assert q1.get_nowait()["message"] == "x"
        assert q2.get_nowait()["message"] == "x"

    async def test_unsubscribe_removes_queue(self):
        task_id = create_task("test")
        q = subscribe(task_id)
        assert len(_subscribers[task_id]) == 1
        unsubscribe(task_id, q)
        assert task_id not in _subscribers

    async def test_unsubscribe_keeps_other_queues(self):
        task_id = create_task("test")
        q1 = subscribe(task_id)
        q2 = subscribe(task_id)
        unsubscribe(task_id, q1)
        assert len(_subscribers[task_id]) == 1
        assert _subscribers[task_id][0] is q2

    async def test_unsubscribe_nonexistent_is_safe(self):
        q: asyncio.Queue = asyncio.Queue()
        unsubscribe("no-such-task", q)


# ===================================================================
# TaskManager — run_exploration_task
# ===================================================================

class TestRunExplorationTask:
    async def test_success_stores_result(self, mocker):
        mocker.patch(
            "src.services.task_manager.run_exploration",
            new_callable=AsyncMock,
            return_value=FAKE_REPORT,
        )
        task_id = create_task("test-topic")
        await task_manager.run_exploration_task(task_id, "test-topic")

        record = get_task(task_id)
        assert record.status == TaskStatus.completed
        assert record.progress_message == "Exploration completed"
        assert record.result["topic"] == "test-topic"
        assert len(record.result["must_read_papers"]) == 1

    async def test_failure_marks_failed(self, mocker):
        mocker.patch(
            "src.services.task_manager.run_exploration",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        )
        task_id = create_task("will-fail")
        await task_manager.run_exploration_task(task_id, "will-fail")

        record = get_task(task_id)
        assert record.status == TaskStatus.failed
        assert "internal error" in record.progress_message.lower()
        assert record.result is None

    async def test_publishes_events_during_run(self, mocker):
        mocker.patch(
            "src.services.task_manager.run_exploration",
            new_callable=AsyncMock,
            return_value=FAKE_REPORT,
        )
        task_id = create_task("test")
        queue = subscribe(task_id)
        await task_manager.run_exploration_task(task_id, "test")

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        types = [e["type"] for e in events]
        assert "status" in types
        assert "complete" in types


# ===================================================================
# API — POST /start
# ===================================================================

class TestStartEndpoint:
    async def test_returns_202_with_task_id(self, client, mocker):
        mocker.patch(
            "src.services.task_manager.run_exploration",
            new_callable=AsyncMock,
            return_value=FAKE_REPORT,
        )
        resp = await client.post(
            "/api/v1/exploration/start",
            json={"topic": "Quantum Computing"},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["error"] is None
        task_id = body["data"]["task_id"]
        assert isinstance(task_id, str) and len(task_id) > 0

    async def test_background_task_completes(self, client, mocker):
        """After POST returns, the background task should have executed."""
        mocker.patch(
            "src.services.task_manager.run_exploration",
            new_callable=AsyncMock,
            return_value=FAKE_REPORT,
        )
        resp = await client.post(
            "/api/v1/exploration/start",
            json={"topic": "test"},
        )
        task_id = resp.json()["data"]["task_id"]
        record = get_task(task_id)
        assert record.status == TaskStatus.completed

    async def test_rejects_empty_topic(self, client):
        resp = await client.post(
            "/api/v1/exploration/start",
            json={"topic": ""},
        )
        assert resp.status_code == 422


# ===================================================================
# API — GET /status
# ===================================================================

class TestStatusEndpoint:
    async def test_returns_pending_task(self, client):
        task_id = create_task("test")
        resp = await client.get(f"/api/v1/exploration/{task_id}/status")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["task_id"] == task_id
        assert data["status"] == "pending"
        assert data["result"] is None

    async def test_returns_completed_task_with_result(self, client, mocker):
        mocker.patch(
            "src.services.task_manager.run_exploration",
            new_callable=AsyncMock,
            return_value=FAKE_REPORT,
        )
        post_resp = await client.post(
            "/api/v1/exploration/start",
            json={"topic": "test"},
        )
        task_id = post_resp.json()["data"]["task_id"]

        resp = await client.get(f"/api/v1/exploration/{task_id}/status")
        data = resp.json()["data"]
        assert data["status"] == "completed"
        assert data["result"]["topic"] == FAKE_REPORT.topic

    async def test_404_for_unknown_task(self, client):
        resp = await client.get("/api/v1/exploration/no-such-id/status")
        assert resp.status_code == 404


# ===================================================================
# API — GET /stream  (SSE)
# ===================================================================

def _parse_sse_events(text: str) -> list[dict]:
    """Extract JSON payloads from raw SSE text."""
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


class TestStreamEndpoint:
    async def test_404_for_unknown_task(self, client):
        resp = await client.get("/api/v1/exploration/no-such-id/stream")
        assert resp.status_code == 404

    async def test_completed_task_sends_final_event(self, client, mocker):
        """A completed task should immediately yield one event and close."""
        mocker.patch(
            "src.services.task_manager.run_exploration",
            new_callable=AsyncMock,
            return_value=FAKE_REPORT,
        )
        post_resp = await client.post(
            "/api/v1/exploration/start",
            json={"topic": "done"},
        )
        task_id = post_resp.json()["data"]["task_id"]

        resp = await client.get(f"/api/v1/exploration/{task_id}/stream")
        assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"
        events = _parse_sse_events(resp.text)
        assert len(events) == 1
        assert events[0]["type"] == "complete"
        assert events[0]["status"] == "completed"

    async def test_failed_task_sends_error_event(self, client, mocker):
        mocker.patch(
            "src.services.task_manager.run_exploration",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        )
        post_resp = await client.post(
            "/api/v1/exploration/start",
            json={"topic": "fail"},
        )
        task_id = post_resp.json()["data"]["task_id"]

        resp = await client.get(f"/api/v1/exploration/{task_id}/stream")
        events = _parse_sse_events(resp.text)
        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert events[0]["status"] == "failed"

    async def test_live_events_streamed_to_client(self, client):
        """Simulate a running task pushing events via the pub/sub bus."""
        task_id = create_task("live")
        _update_fields(task_id, status=TaskStatus.running)

        async def _push_events():
            await asyncio.sleep(0.05)
            _publish(task_id, {"type": "progress", "message": "Planning"})
            await asyncio.sleep(0.05)
            _publish(task_id, {"type": "progress", "message": "Retrieving"})
            await asyncio.sleep(0.05)
            _publish(task_id, {"type": "complete", "status": "completed"})

        publisher = asyncio.create_task(_push_events())

        collected: list[dict] = []
        async with client.stream(
            "GET", f"/api/v1/exploration/{task_id}/stream"
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    collected.append(event)
                    if event.get("type") in ("complete", "error"):
                        break

        await publisher

        assert len(collected) == 3
        assert collected[0] == {"type": "progress", "message": "Planning"}
        assert collected[1] == {"type": "progress", "message": "Retrieving"}
        assert collected[2]["type"] == "complete"
