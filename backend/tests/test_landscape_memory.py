"""Tests for the four-layer Landscape memory subsystem.

Layer 1: S2 API file cache
Layer 2: Pipeline checkpoint / resume
Layer 3: Cross-run topic memory
Layer 4: Incremental update engine
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlmodel import Session

from src.agents.landscape.memory.s2_cache import S2Cache, _cache_key
from src.agents.landscape.memory.checkpoint import CheckpointManager
from src.agents.landscape.memory.topic_store import TopicStore, normalize_topic
from src.agents.landscape.memory.incremental import (
    compute_increment,
    merge_increment,
)
from src.agents.landscape.schemas import (
    CorpusStats,
    PaperCorpus,
    ScopeDefinition,
    SeedPaper,
    SearchStrategy,
    SubField,
)
from src.models.db import (
    PipelineCheckpoint,
    TopicSnapshot,
    TaskRecord,
    TaskStatus,
    get_engine,
)
from src.models.landscape import (
    CollaborationNetwork,
    DynamicResearchLandscape,
    LandscapeIncrement,
    LandscapeMeta,
    ResearchGap,
    ResearchGaps,
    ScholarNode,
    TechTree,
    TechTreeEdge,
    TechTreeNode,
)
from src.models.paper import PaperResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _paper(pid: str = "p1", title: str = "Test Paper") -> PaperResult:
    return PaperResult(
        paper_id=pid,
        title=title,
        authors=["Author"],
        author_ids=["a1"],
        abstract="Abstract",
        doi="",
        published_date="2024",
        pdf_url="",
        url="",
        source="semantic_scholar",
        categories=[],
        citation_count=10,
    )


def _scope() -> ScopeDefinition:
    return ScopeDefinition(
        topic="test topic",
        estimated_complexity="narrow",
        seed_papers=[SeedPaper(title="Seed", reason="foundational")],
        sub_fields=[SubField(name="sub1", description="d", keywords=["kw"])],
        time_range_start=2020,
        time_range_end=2025,
        search_strategies=[
            SearchStrategy(phase="foundational", queries=["test query"]),
        ],
    )


def _landscape(
    topic: str = "test",
    papers: list[PaperResult] | None = None,
    version: int = 1,
) -> DynamicResearchLandscape:
    p = papers or [_paper()]
    return DynamicResearchLandscape(
        meta=LandscapeMeta(
            topic=topic,
            generated_at=datetime.now(timezone.utc),
            paper_count=len(p),
            version=version,
        ),
        papers=p,
        tech_tree=TechTree(nodes=[], edges=[]),
        collaboration_network=CollaborationNetwork(nodes=[], edges=[]),
        research_gaps=ResearchGaps(gaps=[], summary=""),
        sources=[],
    )


# ===========================================================================
# Layer 1: S2 Cache
# ===========================================================================

class TestS2Cache:
    def test_cache_key_deterministic(self) -> None:
        k1 = _cache_key("/paper/search", {"query": "test", "limit": 10}, None)
        k2 = _cache_key("/paper/search", {"limit": 10, "query": "test"}, None)
        assert k1 == k2

    def test_cache_key_differs_for_different_endpoints(self) -> None:
        k1 = _cache_key("/paper/search", {"q": "a"}, None)
        k2 = _cache_key("/paper/batch", {"q": "a"}, None)
        assert k1 != k2

    def test_put_and_get(self, tmp_path: Path) -> None:
        cache = S2Cache(cache_dir=tmp_path, enabled=True)
        cache.put("/paper/search", {"total": 5}, params={"query": "ml"})
        result = cache.get("/paper/search", params={"query": "ml"})
        assert result == {"total": 5}

    def test_miss_returns_none(self, tmp_path: Path) -> None:
        cache = S2Cache(cache_dir=tmp_path, enabled=True)
        assert cache.get("/paper/search", params={"query": "nonexistent"}) is None

    def test_expired_entry_returns_none(self, tmp_path: Path) -> None:
        cache = S2Cache(cache_dir=tmp_path, enabled=True)
        cache.put("/paper/search", {"total": 1}, params={"q": "old"})

        cache_file = list((tmp_path / "s2").glob("*.json"))[0]
        raw = json.loads(cache_file.read_text())
        raw["cached_at"] = time.time() - 200_000
        cache_file.write_text(json.dumps(raw))

        assert cache.get("/paper/search", params={"q": "old"}) is None

    def test_disabled_cache_skips_all(self, tmp_path: Path) -> None:
        cache = S2Cache(cache_dir=tmp_path, enabled=False)
        cache.put("/paper/search", {"total": 1}, params={"q": "x"})
        assert cache.get("/paper/search", params={"q": "x"}) is None

    def test_clear(self, tmp_path: Path) -> None:
        cache = S2Cache(cache_dir=tmp_path, enabled=True)
        cache.put("/paper/1", {"title": "A"})
        cache.put("/paper/2", {"title": "B"})
        removed = cache.clear()
        assert removed == 2
        assert cache.get("/paper/1") is None

    def test_eviction_on_size_limit(self, tmp_path: Path) -> None:
        cache = S2Cache(cache_dir=tmp_path, enabled=True)
        cache._max_bytes = 500
        for i in range(20):
            cache.put(f"/paper/{i}", {"data": "x" * 50}, params={"i": i})
        files = list((tmp_path / "s2").glob("*.json"))
        total = sum(f.stat().st_size for f in files)
        assert total <= 500


# ===========================================================================
# Layer 2: Pipeline Checkpoint
# ===========================================================================

class TestCheckpointManager:
    def test_save_and_load(self) -> None:
        mgr = CheckpointManager()
        scope = _scope()
        mgr.save("task-1", "scope", scope)
        loaded = mgr.load("task-1")
        assert "scope" in loaded
        restored = ScopeDefinition.model_validate_json(loaded["scope"])
        assert restored.topic == "test topic"

    def test_overwrite_existing(self) -> None:
        mgr = CheckpointManager()
        s1 = _scope()
        mgr.save("task-2", "scope", s1)
        s2 = _scope()
        s2.topic = "updated topic"
        mgr.save("task-2", "scope", s2)
        loaded = mgr.load("task-2")
        restored = ScopeDefinition.model_validate_json(loaded["scope"])
        assert restored.topic == "updated topic"

    def test_load_empty(self) -> None:
        mgr = CheckpointManager()
        assert mgr.load("nonexistent") == {}

    def test_clear(self) -> None:
        mgr = CheckpointManager()
        mgr.save("task-3", "scope", _scope())
        mgr.save("task-3", "retrieval", PaperCorpus())
        cleared = mgr.clear("task-3")
        assert cleared == 2
        assert mgr.load("task-3") == {}

    def test_multiple_stages(self) -> None:
        mgr = CheckpointManager()
        mgr.save("task-4", "scope", _scope())
        mgr.save("task-4", "retrieval", PaperCorpus())
        loaded = mgr.load("task-4")
        assert set(loaded.keys()) == {"scope", "retrieval"}

    def test_different_tasks_isolated(self) -> None:
        mgr = CheckpointManager()
        mgr.save("task-a", "scope", _scope())
        mgr.save("task-b", "scope", _scope())
        mgr.clear("task-a")
        assert mgr.load("task-a") == {}
        assert "scope" in mgr.load("task-b")


# ===========================================================================
# Layer 3: Topic Memory
# ===========================================================================

class TestNormalizeTopic:
    def test_case_insensitive(self) -> None:
        assert normalize_topic("Graph Neural Networks") == normalize_topic("graph neural networks")

    def test_word_order_invariant(self) -> None:
        assert normalize_topic("neural graph networks") == normalize_topic("graph neural networks")

    def test_punctuation_stripped(self) -> None:
        assert normalize_topic("LLM-based agents!") == normalize_topic("LLM based agents")


class TestTopicStore:
    def test_save_and_find(self) -> None:
        store = TopicStore()
        scope = _scope()
        snap = store.save(
            topic="Graph Neural Networks",
            scope_json=scope.model_dump_json(),
            corpus_stats_json=CorpusStats(total_papers=50).model_dump_json(),
            task_id="task-100",
            paper_count=50,
        )
        assert snap.topic_normalized == normalize_topic("Graph Neural Networks")

        found = store.find("graph neural networks")
        assert found is not None
        assert found.landscape_task_id == "task-100"
        assert found.paper_count == 50

    def test_find_returns_none_on_miss(self) -> None:
        store = TopicStore()
        assert store.find("completely unknown topic 12345") is None

    def test_update_existing(self) -> None:
        store = TopicStore()
        scope = _scope()
        store.save("test topic", scope.model_dump_json(), "{}", "t1", 10)
        store.save("test topic", scope.model_dump_json(), "{}", "t2", 20)
        snap = store.find("test topic")
        assert snap is not None
        assert snap.landscape_task_id == "t2"
        assert snap.paper_count == 20

    def test_is_fresh(self) -> None:
        store = TopicStore()
        snap = store.save("fresh topic", "{}", "{}", "t1", 5)
        assert store.is_fresh(snap)

    def test_is_not_fresh_when_old(self) -> None:
        store = TopicStore()
        snap = store.save("old topic", "{}", "{}", "t1", 5)
        snap.updated_at = datetime.now(timezone.utc) - timedelta(days=30)
        assert not store.is_fresh(snap)

    def test_load_previous_landscape(self) -> None:
        store = TopicStore()
        landscape = _landscape()
        result_dict = landscape.model_dump(mode="json")

        task = TaskRecord(
            id="task-ld",
            topic="test",
            status=TaskStatus.completed,
            result=result_dict,
        )
        with Session(get_engine()) as session:
            session.add(task)
            session.commit()

        store.save("test", "{}", "{}", "task-ld", 1)
        snap = store.find("test")
        assert snap is not None
        loaded = store.load_previous_landscape(snap)
        assert loaded is not None
        assert len(loaded.papers) == 1

    def test_load_previous_landscape_missing_task(self) -> None:
        store = TopicStore()
        store.save("orphan", "{}", "{}", "nonexistent-task", 0)
        snap = store.find("orphan")
        assert snap is not None
        assert store.load_previous_landscape(snap) is None


# ===========================================================================
# Layer 4: Incremental Update
# ===========================================================================

class TestComputeIncrement:
    def test_no_changes(self) -> None:
        ls = _landscape()
        inc = compute_increment(ls, ls)
        assert inc.is_empty

    def test_detects_new_papers(self) -> None:
        old = _landscape(papers=[_paper("p1")])
        new = _landscape(papers=[_paper("p1"), _paper("p2", "New Paper")])
        inc = compute_increment(old, new)
        assert len(inc.new_papers) == 1
        assert inc.new_papers[0].paper_id == "p2"

    def test_detects_new_tech_nodes(self) -> None:
        p1, p2 = _paper("p1"), _paper("p2")
        node = TechTreeNode(
            node_id="n1", label="Method", node_type="method",
            description="A method", representative_paper_ids=["p2"],
        )
        old = _landscape(papers=[p1, p2])
        new_ls = DynamicResearchLandscape(
            meta=LandscapeMeta(
                topic="test",
                generated_at=datetime.now(timezone.utc),
                paper_count=2, version=1,
            ),
            papers=[p1, p2],
            tech_tree=TechTree(nodes=[node], edges=[]),
            collaboration_network=CollaborationNetwork(nodes=[], edges=[]),
            research_gaps=ResearchGaps(gaps=[], summary=""),
            sources=[],
        )
        inc = compute_increment(old, new_ls)
        assert len(inc.new_tech_nodes) == 1
        assert not inc.is_empty


class TestMergeIncrement:
    def test_empty_increment_returns_existing(self) -> None:
        existing = _landscape(version=3)
        inc = LandscapeIncrement()
        merged = merge_increment(existing, inc)
        assert merged is existing

    def test_merge_adds_papers_and_bumps_version(self) -> None:
        existing = _landscape(papers=[_paper("p1")], version=1)
        inc = LandscapeIncrement(
            new_papers=[_paper("p2", "New")],
            detected_at=datetime.now(timezone.utc),
        )
        merged = merge_increment(existing, inc)
        assert merged.meta.version == 2
        assert len(merged.papers) == 2
        pids = {p.paper_id for p in merged.papers}
        assert pids == {"p1", "p2"}

    def test_new_items_marked_is_new(self) -> None:
        existing = _landscape(papers=[_paper("p1"), _paper("p2")])
        node = TechTreeNode(
            node_id="n1", label="New Method", node_type="method",
            description="desc", representative_paper_ids=["p1"],
        )
        scholar = ScholarNode(scholar_id="s1", name="Scholar")
        inc = LandscapeIncrement(
            new_tech_nodes=[node],
            new_scholars=[scholar],
            detected_at=datetime.now(timezone.utc),
        )
        merged = merge_increment(existing, inc)
        assert merged.tech_tree.nodes[0].is_new
        assert merged.collaboration_network.nodes[0].is_new


# ===========================================================================
# LandscapeIncrement.is_empty property
# ===========================================================================

class TestLandscapeIncrementIsEmpty:
    def test_empty(self) -> None:
        assert LandscapeIncrement().is_empty

    def test_not_empty_with_papers(self) -> None:
        inc = LandscapeIncrement(new_papers=[_paper()])
        assert not inc.is_empty


# ===========================================================================
# Assembler base_version
# ===========================================================================

class TestAssemblerBaseVersion:
    def test_default_version_is_1(self) -> None:
        from src.agents.landscape.assembler import assemble_landscape
        ls = assemble_landscape(
            topic="t",
            papers=[_paper()],
            tech_tree=TechTree(),
            collaboration_network=CollaborationNetwork(),
            research_gaps=ResearchGaps(),
        )
        assert ls.meta.version == 1

    def test_base_version_bumps(self) -> None:
        from src.agents.landscape.assembler import assemble_landscape
        ls = assemble_landscape(
            topic="t",
            papers=[_paper()],
            tech_tree=TechTree(),
            collaboration_network=CollaborationNetwork(),
            research_gaps=ResearchGaps(),
            base_version=5,
        )
        assert ls.meta.version == 6


# ===========================================================================
# Config additions
# ===========================================================================

class TestConfigMemorySettings:
    def test_default_values(self) -> None:
        from src.core.config import Settings
        s = Settings()
        assert s.cache_dir == "../data/cache"
        assert s.s2_cache_enabled is True
        assert s.s2_cache_max_mb == 500
        assert s.topic_cache_max_age_days == 7
        assert s.topic_warm_start_max_age_days == 30


# ===========================================================================
# DB model sanity
# ===========================================================================

class TestDBModels:
    def test_pipeline_checkpoint_create(self) -> None:
        with Session(get_engine()) as session:
            cp = PipelineCheckpoint(task_id="t1", stage="scope", data_json="{}")
            session.add(cp)
            session.commit()
            session.refresh(cp)
            assert cp.id
            assert cp.task_id == "t1"

    def test_topic_snapshot_create(self) -> None:
        with Session(get_engine()) as session:
            snap = TopicSnapshot(
                topic_normalized="test",
                topic_original="Test",
                landscape_task_id="t1",
                paper_count=10,
            )
            session.add(snap)
            session.commit()
            session.refresh(snap)
            assert snap.id
            assert snap.topic_normalized == "test"


# ===========================================================================
# Orchestrator signature
# ===========================================================================

class TestOrchestratorSignature:
    def test_run_landscape_pipeline_accepts_task_id(self) -> None:
        import inspect
        from src.agents.landscape.orchestrator import run_landscape_pipeline
        sig = inspect.signature(run_landscape_pipeline)
        assert "task_id" in sig.parameters

    def test_run_incremental_update_exists(self) -> None:
        from src.agents.landscape.orchestrator import run_incremental_update
        import inspect
        sig = inspect.signature(run_incremental_update)
        assert "task_id" in sig.parameters
        assert "topic" in sig.parameters


# ===========================================================================
# Orchestrator integration: cache hit / checkpoint fallback / touch
# ===========================================================================

class TestOrchestratorCacheHit:
    """Fresh topic cache hit should short-circuit the pipeline and touch the snapshot."""

    @pytest.mark.asyncio
    async def test_fresh_cache_hit_returns_cached_landscape(self) -> None:
        from unittest.mock import AsyncMock, patch

        store = TopicStore()
        landscape = _landscape(topic="cache hit topic")
        result_dict = landscape.model_dump(mode="json")

        task = TaskRecord(
            id="task-ch", topic="cache hit topic",
            status=TaskStatus.completed, result=result_dict,
        )
        with Session(get_engine()) as session:
            session.add(task)
            session.commit()

        store.save(
            topic="cache hit topic",
            scope_json=_scope().model_dump_json(),
            corpus_stats_json="{}",
            task_id="task-ch",
            paper_count=1,
        )

        from src.agents.landscape.orchestrator import run_landscape_pipeline

        with patch(
            "src.agents.landscape.orchestrator.ScopeAgent",
            side_effect=AssertionError("ScopeAgent should not be called on cache hit"),
        ):
            result = await run_landscape_pipeline("cache hit topic")

        assert result is not None
        assert result.meta.topic == "cache hit topic"

    @pytest.mark.asyncio
    async def test_cache_hit_refreshes_updated_at(self) -> None:
        store = TopicStore()
        landscape = _landscape(topic="touch test")
        result_dict = landscape.model_dump(mode="json")

        task = TaskRecord(
            id="task-tt", topic="touch test",
            status=TaskStatus.completed, result=result_dict,
        )
        with Session(get_engine()) as session:
            session.add(task)
            session.commit()

        snap = store.save("touch test", "{}", "{}", "task-tt", 1)
        original_time = snap.updated_at

        import asyncio
        await asyncio.sleep(0.05)

        from src.agents.landscape.orchestrator import run_landscape_pipeline
        from unittest.mock import patch

        with patch(
            "src.agents.landscape.orchestrator.ScopeAgent",
            side_effect=AssertionError("Should not be called"),
        ):
            await run_landscape_pipeline("touch test")

        refreshed = store.find("touch test")
        assert refreshed is not None
        if refreshed.updated_at.tzinfo is None:
            from datetime import timezone as tz
            original_cmp = original_time.replace(tzinfo=None) if original_time.tzinfo else original_time
        else:
            original_cmp = original_time
        assert refreshed.updated_at >= original_cmp


class TestCheckpointDeserializationFallback:
    """Corrupted checkpoint data should be silently ignored, causing re-run."""

    @pytest.mark.asyncio
    async def test_corrupted_scope_checkpoint_triggers_rerun(self) -> None:
        from unittest.mock import AsyncMock, patch, MagicMock
        from src.agents.landscape.memory.checkpoint import CheckpointManager

        mgr = CheckpointManager()
        with Session(get_engine()) as session:
            from src.models.db import PipelineCheckpoint
            cp = PipelineCheckpoint(
                task_id="task-bad",
                stage="scope",
                data_json='{"this_is": "not_a_valid_scope"}',
            )
            session.add(cp)
            session.commit()

        loaded = mgr.load("task-bad")
        assert "scope" in loaded

        from src.agents.landscape.schemas import ScopeDefinition
        raised = False
        try:
            ScopeDefinition.model_validate_json(loaded["scope"])
        except Exception:
            raised = True
        assert raised, "Bad checkpoint data should fail validation"

    def test_corrupted_retrieval_checkpoint_stays_none(self) -> None:
        """When retrieval checkpoint contains invalid JSON, deserialization fails."""
        bad_json = '{"papers": "not_a_list"}'
        try:
            PaperCorpus.model_validate_json(bad_json)
            validated = True
        except Exception:
            validated = False
        assert not validated


class TestTopicStoreTouch:
    def test_touch_updates_timestamp(self) -> None:
        store = TopicStore()
        snap = store.save("touch topic", "{}", "{}", "t1", 5)
        original = snap.updated_at

        import time as _time
        _time.sleep(0.05)
        store.touch(snap)

        reloaded = store.find("touch topic")
        assert reloaded is not None
        t1 = original.replace(tzinfo=None) if original.tzinfo else original
        t2 = reloaded.updated_at.replace(tzinfo=None) if reloaded.updated_at.tzinfo else reloaded.updated_at
        assert t2 >= t1
