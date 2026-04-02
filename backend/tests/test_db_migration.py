"""Tests for lightweight runtime DB migrations."""

from __future__ import annotations

from sqlmodel import create_engine

from src.models.db import apply_lightweight_migrations


def _column_names(engine, table: str) -> set[str]:
    with engine.begin() as conn:
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def test_adds_progress_snapshot_column_for_legacy_task_records() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE task_records (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                status TEXT NOT NULL,
                progress_message TEXT NOT NULL DEFAULT '',
                result JSON,
                created_at TEXT,
                updated_at TEXT
            )
            """,
        )

    assert "progress_snapshot" not in _column_names(engine, "task_records")

    apply_lightweight_migrations(engine)

    assert "progress_snapshot" in _column_names(engine, "task_records")


def test_migration_is_idempotent() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE task_records (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                status TEXT NOT NULL,
                progress_message TEXT NOT NULL DEFAULT '',
                progress_snapshot JSON,
                result JSON,
                created_at TEXT,
                updated_at TEXT
            )
            """,
        )

    apply_lightweight_migrations(engine)
    apply_lightweight_migrations(engine)

    assert "progress_snapshot" in _column_names(engine, "task_records")
