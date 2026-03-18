"""Tests for the monitoring API routes and the scheduler's run_daily_jobs.

All external calls are mocked.  Tests run against an in-memory SQLite
database provided by the shared ``_test_db`` fixture in conftest.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session, select

from src.agents.monitoring.schemas import DailyBrief, HotPaper
from src.models.db import MonitorBrief, MonitorFrequency, MonitorTask, get_engine

# ---------------------------------------------------------------------------
# Shared fake data
# ---------------------------------------------------------------------------

FAKE_BRIEF = DailyBrief(
    topic="transformers",
    since_date="2026-03-17",
    new_hot_papers=[
        HotPaper(
            title="Attention Is All You Need",
            authors=["Vaswani"],
            year=2026,
            url="https://example.com/paper1",
            citation_count=100,
            relevance_reason="Foundational paper",
        )
    ],
    trend_summary="Transformers continue to dominate.",
    sources=["https://example.com/paper1"],
)


# ===================================================================
# API — POST /api/v1/monitoring/tasks
# ===================================================================


class TestCreateMonitorTask:
    async def test_returns_201_with_correct_data(self, client):
        resp = await client.post(
            "/api/v1/monitoring/tasks",
            json={"topic": "LLM safety", "frequency": "daily"},
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["topic"] == "LLM safety"
        assert data["frequency"] == "daily"
        assert data["is_active"] is True
        assert data["notify_email"] is None
        assert data["last_run_at"] is None
        assert resp.json()["error"] is None

    async def test_weekly_frequency(self, client):
        resp = await client.post(
            "/api/v1/monitoring/tasks",
            json={"topic": "quantum computing", "frequency": "weekly"},
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["frequency"] == "weekly"

    async def test_default_frequency_is_daily(self, client):
        resp = await client.post(
            "/api/v1/monitoring/tasks",
            json={"topic": "NLP"},
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["frequency"] == "daily"

    async def test_with_notify_email(self, client):
        resp = await client.post(
            "/api/v1/monitoring/tasks",
            json={"topic": "RL", "notify_email": "team@example.com"},
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["notify_email"] == "team@example.com"

    async def test_rejects_empty_topic(self, client):
        resp = await client.post(
            "/api/v1/monitoring/tasks",
            json={"topic": "", "frequency": "daily"},
        )
        assert resp.status_code == 422

    async def test_rejects_invalid_frequency(self, client):
        resp = await client.post(
            "/api/v1/monitoring/tasks",
            json={"topic": "AI", "frequency": "hourly"},
        )
        assert resp.status_code == 422


# ===================================================================
# API — GET /api/v1/monitoring/tasks
# ===================================================================


class TestListMonitorTasks:
    async def test_empty_list(self, client):
        resp = await client.get("/api/v1/monitoring/tasks")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == []
        assert body["meta"]["total"] == 0
        assert body["error"] is None

    async def test_list_after_create(self, client):
        await client.post(
            "/api/v1/monitoring/tasks",
            json={"topic": "NLP"},
        )
        await client.post(
            "/api/v1/monitoring/tasks",
            json={"topic": "CV", "frequency": "weekly"},
        )

        resp = await client.get("/api/v1/monitoring/tasks")
        body = resp.json()
        assert body["meta"]["total"] == 2
        topics = {t["topic"] for t in body["data"]}
        assert topics == {"NLP", "CV"}


# ===================================================================
# API — GET /api/v1/monitoring/tasks/{task_id}/briefs
# ===================================================================


class TestListBriefs:
    async def test_404_for_unknown_task(self, client):
        resp = await client.get("/api/v1/monitoring/tasks/nonexistent/briefs")
        assert resp.status_code == 404

    async def test_empty_briefs_for_new_task(self, client):
        create_resp = await client.post(
            "/api/v1/monitoring/tasks",
            json={"topic": "AI safety"},
        )
        task_id = create_resp.json()["data"]["id"]

        resp = await client.get(f"/api/v1/monitoring/tasks/{task_id}/briefs")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == []
        assert body["meta"]["total"] == 0

    async def test_returns_inserted_brief(self, client):
        create_resp = await client.post(
            "/api/v1/monitoring/tasks",
            json={"topic": "robotics"},
        )
        task_id = create_resp.json()["data"]["id"]

        engine = get_engine()
        with Session(engine) as session:
            brief = MonitorBrief(
                task_id=task_id,
                brief_content=FAKE_BRIEF.model_dump(mode="json"),
            )
            session.add(brief)
            session.commit()

        resp = await client.get(f"/api/v1/monitoring/tasks/{task_id}/briefs")
        body = resp.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["task_id"] == task_id
        assert body["data"][0]["brief_content"]["topic"] == "transformers"
        assert len(body["data"][0]["brief_content"]["new_hot_papers"]) == 1


# ===================================================================
# API — DELETE /api/v1/monitoring/tasks/{task_id}
# ===================================================================


class TestDeleteMonitorTask:
    async def test_404_for_unknown_task(self, client):
        resp = await client.delete("/api/v1/monitoring/tasks/no-such-id")
        assert resp.status_code == 404

    async def test_delete_task_and_related_briefs(self, client):
        create_resp = await client.post(
            "/api/v1/monitoring/tasks",
            json={"topic": "deletable topic", "frequency": "daily"},
        )
        task_id = create_resp.json()["data"]["id"]

        engine = get_engine()
        with Session(engine) as session:
            session.add(
                MonitorBrief(
                    task_id=task_id,
                    brief_content=FAKE_BRIEF.model_dump(mode="json"),
                )
            )
            session.commit()

        delete_resp = await client.delete(f"/api/v1/monitoring/tasks/{task_id}")
        assert delete_resp.status_code == 200
        payload = delete_resp.json()["data"]
        assert payload["id"] == task_id
        assert payload["deleted"] is True

        with Session(engine) as session:
            task = session.get(MonitorTask, task_id)
            briefs = session.exec(
                select(MonitorBrief).where(MonitorBrief.task_id == task_id)
            ).all()
            assert task is None
            assert briefs == []


# ===================================================================
# Scheduler — run_daily_jobs
# ===================================================================


class TestRunDailyJobs:
    async def test_creates_brief_and_updates_last_run_at(self, mocker):
        """Insert an active task with per-task email, verify brief + email sent."""
        mocker.patch(
            "src.services.scheduler.run_monitoring_scan",
            new_callable=AsyncMock,
            return_value=FAKE_BRIEF,
        )
        mock_send_email = mocker.patch(
            "src.services.scheduler.send_daily_brief_email",
            new_callable=AsyncMock,
            return_value=True,
        )

        engine = get_engine()
        with Session(engine) as session:
            task = MonitorTask(
                topic="transformers",
                frequency=MonitorFrequency.daily,
                notify_email="per-task@example.com",
            )
            session.add(task)
            session.commit()
            session.refresh(task)
            task_id = task.id
            assert task.last_run_at is None

        from src.services.scheduler import run_daily_jobs

        await run_daily_jobs()

        with Session(engine) as session:
            briefs = session.exec(
                select(MonitorBrief).where(MonitorBrief.task_id == task_id)
            ).all()
            assert len(briefs) == 1
            assert briefs[0].brief_content["topic"] == "transformers"
            assert len(briefs[0].brief_content["new_hot_papers"]) == 1

            updated_task = session.get(MonitorTask, task_id)
            assert updated_task.last_run_at is not None
            assert updated_task.updated_at >= updated_task.created_at

        mock_send_email.assert_called_once_with(FAKE_BRIEF, "per-task@example.com")

    async def test_skips_inactive_tasks(self, mocker):
        """Inactive tasks should not trigger a monitoring scan."""
        mock_scan = mocker.patch(
            "src.services.scheduler.run_monitoring_scan",
            new_callable=AsyncMock,
            return_value=FAKE_BRIEF,
        )

        engine = get_engine()
        with Session(engine) as session:
            task = MonitorTask(
                topic="ignored",
                frequency=MonitorFrequency.daily,
                is_active=False,
            )
            session.add(task)
            session.commit()

        from src.services.scheduler import run_daily_jobs

        await run_daily_jobs()

        mock_scan.assert_not_called()

    async def test_no_active_tasks_is_noop(self, mocker):
        """When the DB has no active tasks the job finishes without error."""
        mock_scan = mocker.patch(
            "src.services.scheduler.run_monitoring_scan",
            new_callable=AsyncMock,
        )

        from src.services.scheduler import run_daily_jobs

        await run_daily_jobs()

        mock_scan.assert_not_called()

    async def test_scan_failure_does_not_block_other_tasks(self, mocker):
        """If one scan raises, subsequent tasks should still be processed."""
        call_count = 0

        async def _side_effect(topic: str, since: str) -> DailyBrief:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("boom")
            return FAKE_BRIEF

        mocker.patch(
            "src.services.scheduler.run_monitoring_scan",
            new_callable=AsyncMock,
            side_effect=_side_effect,
        )
        mocker.patch(
            "src.services.scheduler.send_daily_brief_email",
            new_callable=AsyncMock,
            return_value=True,
        )

        engine = get_engine()
        with Session(engine) as session:
            t1 = MonitorTask(topic="will-fail", frequency=MonitorFrequency.daily)
            t2 = MonitorTask(topic="will-succeed", frequency=MonitorFrequency.daily)
            session.add(t1)
            session.add(t2)
            session.commit()
            session.refresh(t2)
            t2_id = t2.id

        from src.services.scheduler import run_daily_jobs

        await run_daily_jobs()

        with Session(engine) as session:
            briefs = session.exec(select(MonitorBrief)).all()
            assert len(briefs) == 1
            assert briefs[0].task_id == t2_id

    async def test_multiple_active_tasks_all_get_briefs(self, mocker):
        """Every active task should receive its own brief."""
        mocker.patch(
            "src.services.scheduler.run_monitoring_scan",
            new_callable=AsyncMock,
            return_value=FAKE_BRIEF,
        )
        mocker.patch(
            "src.services.scheduler.send_daily_brief_email",
            new_callable=AsyncMock,
            return_value=True,
        )

        engine = get_engine()
        with Session(engine) as session:
            t1 = MonitorTask(topic="NLP", frequency=MonitorFrequency.daily)
            t2 = MonitorTask(topic="CV", frequency=MonitorFrequency.weekly)
            session.add(t1)
            session.add(t2)
            session.commit()

        from src.services.scheduler import run_daily_jobs

        await run_daily_jobs()

        with Session(engine) as session:
            briefs = session.exec(select(MonitorBrief)).all()
            assert len(briefs) == 2
            task_ids = {b.task_id for b in briefs}
            tasks = session.exec(select(MonitorTask)).all()
            expected_ids = {t.id for t in tasks}
            assert task_ids == expected_ids

    async def test_email_sent_with_global_fallback(self, mocker):
        """When task has no notify_email, fall back to Settings.notification_email."""
        mocker.patch(
            "src.services.scheduler.run_monitoring_scan",
            new_callable=AsyncMock,
            return_value=FAKE_BRIEF,
        )
        mock_send_email = mocker.patch(
            "src.services.scheduler.send_daily_brief_email",
            new_callable=AsyncMock,
            return_value=True,
        )
        mock_settings = mocker.MagicMock(notification_email="global@example.com")
        mocker.patch("src.services.scheduler.get_settings", return_value=mock_settings)

        engine = get_engine()
        with Session(engine) as session:
            task = MonitorTask(topic="RL", frequency=MonitorFrequency.daily)
            session.add(task)
            session.commit()

        from src.services.scheduler import run_daily_jobs

        await run_daily_jobs()

        mock_send_email.assert_called_once_with(FAKE_BRIEF, "global@example.com")

    async def test_no_email_when_neither_configured(self, mocker):
        """No email sent when both task.notify_email and global are empty."""
        mocker.patch(
            "src.services.scheduler.run_monitoring_scan",
            new_callable=AsyncMock,
            return_value=FAKE_BRIEF,
        )
        mock_send_email = mocker.patch(
            "src.services.scheduler.send_daily_brief_email",
            new_callable=AsyncMock,
            return_value=True,
        )

        engine = get_engine()
        with Session(engine) as session:
            task = MonitorTask(topic="robotics", frequency=MonitorFrequency.daily)
            session.add(task)
            session.commit()

        from src.services.scheduler import run_daily_jobs

        await run_daily_jobs()

        mock_send_email.assert_not_called()
