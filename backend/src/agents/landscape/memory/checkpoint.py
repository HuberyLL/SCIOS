"""Layer 2: Pipeline checkpoint / resume.

After each pipeline stage the orchestrator calls ``save_checkpoint`` to
persist the Pydantic output.  If the pipeline is restarted for the same
``task_id``, ``load_checkpoints`` restores all completed stages so the
pipeline can skip ahead.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlmodel import Session, select

from src.models.db import PipelineCheckpoint, get_engine

logger = logging.getLogger(__name__)

STAGE_ORDER = ("scope", "retrieval", "taxonomy", "network", "gaps")


class CheckpointManager:
    """Save / load pipeline stage outputs keyed by ``task_id``."""

    def save(self, task_id: str, stage: str, data: BaseModel) -> None:
        """Persist a stage output.  Overwrites any existing checkpoint for the same stage."""
        with Session(get_engine()) as session:
            existing = session.exec(
                select(PipelineCheckpoint)
                .where(PipelineCheckpoint.task_id == task_id)
                .where(PipelineCheckpoint.stage == stage)
            ).first()
            if existing:
                existing.data_json = data.model_dump_json()
                existing.created_at = datetime.now(timezone.utc)
                session.add(existing)
            else:
                cp = PipelineCheckpoint(
                    task_id=task_id,
                    stage=stage,
                    data_json=data.model_dump_json(),
                )
                session.add(cp)
            session.commit()
        logger.debug("Checkpoint saved: task=%s stage=%s", task_id, stage)

    def load(self, task_id: str) -> dict[str, str]:
        """Return ``{stage: data_json}`` for all checkpoints of *task_id*."""
        with Session(get_engine()) as session:
            rows = session.exec(
                select(PipelineCheckpoint)
                .where(PipelineCheckpoint.task_id == task_id)
            ).all()
        result: dict[str, str] = {}
        for row in rows:
            result[row.stage] = row.data_json
        if result:
            logger.info("Loaded %d checkpoint(s) for task %s: %s", len(result), task_id, list(result.keys()))
        return result

    def clear(self, task_id: str) -> int:
        """Delete all checkpoints for *task_id*.  Returns count deleted."""
        with Session(get_engine()) as session:
            rows = session.exec(
                select(PipelineCheckpoint)
                .where(PipelineCheckpoint.task_id == task_id)
            ).all()
            count = len(rows)
            for row in rows:
                session.delete(row)
            session.commit()
        if count:
            logger.info("Cleared %d checkpoint(s) for task %s", count, task_id)
        return count
