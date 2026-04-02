"""Layer 3: Cross-run topic memory.

Stores lightweight metadata for each completed landscape analysis so that
a repeated (or very similar) topic query can be served instantly or
warm-started from a previous scope/corpus without re-running the full
pipeline.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlmodel import Session, select

from src.core.config import get_settings
from src.models.db import TopicSnapshot, TaskRecord, get_engine
from src.models.landscape import DynamicResearchLandscape

logger = logging.getLogger(__name__)


def normalize_topic(topic: str) -> str:
    """Deterministic normalization: lowercase, strip accents, collapse whitespace, sort words."""
    text = unicodedata.normalize("NFKD", topic)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    words = sorted(text.split())
    return " ".join(words)


class TopicStore:
    """CRUD for ``TopicSnapshot`` records."""

    def find(self, topic: str) -> TopicSnapshot | None:
        """Exact match on normalized topic. Returns the most recently updated snapshot."""
        norm = normalize_topic(topic)
        with Session(get_engine()) as session:
            row = session.exec(
                select(TopicSnapshot)
                .where(TopicSnapshot.topic_normalized == norm)
                .order_by(TopicSnapshot.updated_at.desc())
            ).first()
        return row

    def save(
        self,
        topic: str,
        scope_json: str,
        corpus_stats_json: str,
        task_id: str,
        paper_count: int,
    ) -> TopicSnapshot:
        """Insert or update a snapshot for *topic*."""
        norm = normalize_topic(topic)
        now = datetime.now(timezone.utc)
        with Session(get_engine()) as session:
            existing = session.exec(
                select(TopicSnapshot)
                .where(TopicSnapshot.topic_normalized == norm)
            ).first()
            if existing:
                existing.scope_json = scope_json
                existing.corpus_stats_json = corpus_stats_json
                existing.landscape_task_id = task_id
                existing.paper_count = paper_count
                existing.updated_at = now
                session.add(existing)
                session.commit()
                session.refresh(existing)
                logger.info("Updated topic snapshot for '%s' (task %s)", topic, task_id)
                return existing
            else:
                snap = TopicSnapshot(
                    topic_normalized=norm,
                    topic_original=topic,
                    scope_json=scope_json,
                    corpus_stats_json=corpus_stats_json,
                    landscape_task_id=task_id,
                    paper_count=paper_count,
                    created_at=now,
                    updated_at=now,
                )
                session.add(snap)
                session.commit()
                session.refresh(snap)
                logger.info("Created topic snapshot for '%s' (task %s)", topic, task_id)
                return snap

    def touch(self, snapshot: TopicSnapshot) -> None:
        """Refresh ``updated_at`` without changing any other fields (LRU-style keep-alive)."""
        with Session(get_engine()) as session:
            row = session.get(TopicSnapshot, snapshot.id)
            if row is not None:
                row.updated_at = datetime.now(timezone.utc)
                session.add(row)
                session.commit()

    def load_previous_landscape(self, snapshot: TopicSnapshot) -> DynamicResearchLandscape | None:
        """Load the full landscape from the linked TaskRecord."""
        with Session(get_engine()) as session:
            task = session.get(TaskRecord, snapshot.landscape_task_id)
        if task is None or task.result is None:
            return None
        try:
            return DynamicResearchLandscape.model_validate(task.result)
        except Exception:
            logger.warning(
                "Failed to deserialize landscape for task %s",
                snapshot.landscape_task_id,
            )
            return None

    @staticmethod
    def _age(snapshot: TopicSnapshot) -> timedelta:
        updated = snapshot.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - updated

    def is_fresh(self, snapshot: TopicSnapshot) -> bool:
        """True if the snapshot is within ``topic_cache_max_age_days``."""
        max_age = timedelta(days=get_settings().topic_cache_max_age_days)
        return self._age(snapshot) < max_age

    def is_warm_startable(self, snapshot: TopicSnapshot) -> bool:
        """True if the snapshot is within ``topic_warm_start_max_age_days``."""
        max_age = timedelta(days=get_settings().topic_warm_start_max_age_days)
        return self._age(snapshot) < max_age
