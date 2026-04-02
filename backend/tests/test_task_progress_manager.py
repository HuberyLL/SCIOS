"""Regression tests for task progress persistence and recovery."""

from __future__ import annotations

import json

from sqlmodel import SQLModel, Session, create_engine

from src.models import db as db_module
from src.models.db import TaskRecord, TaskStatus, apply_lightweight_migrations
from src.services import task_manager


def _bind_temp_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test_progress.db")
    SQLModel.metadata.create_all(engine)
    apply_lightweight_migrations(engine)
    db_module._engine = engine  # noqa: SLF001 - test-only rebinding
    return engine


def test_update_task_progress_persists_pct_and_snapshot(tmp_path) -> None:
    engine = _bind_temp_engine(tmp_path)

    task_id = task_manager.create_task("LLM")
    with Session(engine) as session:
        rec = session.get(TaskRecord, task_id)
        assert rec is not None
        rec.status = TaskStatus.running
        session.add(rec)
        session.commit()

    task_manager.update_task_progress(task_id, {
        "type": "progress",
        "stage_id": "scope",
        "stage_index": 1,
        "status": "running",
        "message": "Defining research scope …",
        "progress_pct": 0,
    })
    task_manager.update_task_progress(task_id, {
        "type": "progress",
        "stage_id": "retrieval",
        "stage_index": 2,
        "status": "running",
        "message": "Retrieving papers …",
        "progress_pct": 25,
    })

    record = task_manager.get_task(task_id)
    assert record is not None
    assert record.current_stage_id == "retrieval"
    assert record.current_progress_pct == 25
    snap = task_manager._coerce_snapshot(record.progress_snapshot)  # noqa: SLF001
    assert set(snap.keys()) >= {"scope", "retrieval"}
    assert snap["retrieval"]["progress_pct"] == 25


def test_update_task_progress_handles_string_snapshot(tmp_path) -> None:
    engine = _bind_temp_engine(tmp_path)
    task_id = task_manager.create_task("NLP")

    with Session(engine) as session:
        rec = session.get(TaskRecord, task_id)
        assert rec is not None
        rec.status = TaskStatus.running
        rec.progress_snapshot = json.dumps({
            "scope": {
                "type": "progress",
                "stage_id": "scope",
                "stage_index": 1,
                "message": "scope",
                "progress_pct": 10,
            },
        })
        session.add(rec)
        session.commit()

    task_manager.update_task_progress(task_id, {
        "type": "progress",
        "stage_id": "taxonomy",
        "stage_index": 3,
        "status": "running",
        "message": "Building taxonomy …",
        "progress_pct": 60,
    })

    record = task_manager.get_task(task_id)
    assert record is not None
    snap = task_manager._coerce_snapshot(record.progress_snapshot)  # noqa: SLF001
    assert "scope" in snap
    assert "taxonomy" in snap
    assert record.current_progress_pct == 60
