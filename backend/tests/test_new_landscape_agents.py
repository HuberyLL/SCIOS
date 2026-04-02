"""Unit tests for the new multi-agent landscape pipeline.

Covers:
- New schema validation (ScopeDefinition, PaperCorpus, QualityReport)
- Agent base class behaviour
- S2 client new methods (search_by_title, get_author, get_author_papers)
- Orchestrator import chain
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.models.landscape import (
    CollaborationNetwork,
    ResearchGaps,
    TechTree,
    TechTreeNode,
)
from src.models.paper import PaperResult

from src.agents.landscape.schemas import (
    AuthorProfile,
    CorpusStats,
    PaperCorpus,
    QualityIssue,
    QualityReport,
    ScopeDefinition,
    SeedPaper,
    SearchStrategy,
    SubField,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _paper(pid: str = "p1", title: str = "Paper", citations: int = 0) -> PaperResult:
    return PaperResult(
        paper_id=pid,
        title=title,
        authors=["Alice"],
        citation_count=citations,
        source="semantic_scholar",
    )


def _scope(topic: str = "LLM") -> ScopeDefinition:
    return ScopeDefinition(
        topic=topic,
        topic_description="Large Language Models",
        seed_papers=[
            SeedPaper(
                title="Attention Is All You Need",
                expected_authors=["Vaswani"],
                expected_year=2017,
                reason="Foundational Transformer paper",
            ),
        ],
        sub_fields=[
            SubField(name="Architecture", description="Model architecture", keywords=["transformer"]),
            SubField(name="Pre-training", description="Pre-training methods", keywords=["pre-training"]),
        ],
        time_range_start=2017,
        time_range_end=2026,
        search_strategies=[
            SearchStrategy(phase="foundational", queries=["attention mechanism transformer"]),
        ],
    )


def _corpus() -> PaperCorpus:
    return PaperCorpus(
        papers=[_paper("p1", "Attention Is All You Need", 90000)],
        seed_paper_map={"Attention Is All You Need": "p1"},
        stats=CorpusStats(
            total_papers=1,
            seed_papers_found=1,
            seed_papers_expected=1,
        ),
    )


# ===================================================================
# Schema tests
# ===================================================================

class TestScopeDefinition:
    def test_valid_construction(self):
        scope = _scope()
        assert scope.topic == "LLM"
        assert len(scope.seed_papers) == 1
        assert len(scope.sub_fields) == 2

    def test_json_round_trip(self):
        scope = _scope()
        restored = ScopeDefinition.model_validate_json(scope.model_dump_json())
        assert restored.topic == scope.topic
        assert len(restored.seed_papers) == len(scope.seed_papers)

    def test_min_sub_fields_enforced(self):
        """At least one sub-field is required."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ScopeDefinition(
                topic="X",
                seed_papers=[SeedPaper(title="T", reason="R")],
                sub_fields=[],
                time_range_start=2020,
                time_range_end=2026,
                search_strategies=[SearchStrategy(phase="foundational", queries=["q"])],
            )


class TestPaperCorpus:
    def test_valid_construction(self):
        corpus = _corpus()
        assert corpus.stats.total_papers == 1
        assert len(corpus.seed_paper_map) == 1
        assert corpus.seed_paper_ids == ["p1"]

    def test_empty_defaults(self):
        corpus = PaperCorpus()
        assert corpus.papers == []
        assert corpus.seed_paper_map == {}
        assert corpus.seed_paper_ids == []
        assert corpus.citation_graph == {}


class TestQualityReport:
    def test_passed_report(self):
        report = QualityReport(
            passed=True,
            scores={"seed_coverage": 0.9, "subfield_coverage": 0.8},
        )
        assert report.passed
        assert report.retry_targets == []

    def test_failed_report_with_targets(self):
        report = QualityReport(
            passed=False,
            issues=[QualityIssue(
                category="seed_coverage",
                severity="critical",
                description="Missing seed papers",
            )],
            retry_targets=["retrieval"],
            scores={"seed_coverage": 0.2},
        )
        assert not report.passed
        assert "retrieval" in report.retry_targets


class TestAuthorProfile:
    def test_valid_construction(self):
        profile = AuthorProfile(
            author_id="123",
            name="Alice",
            h_index=42,
            paper_count=100,
            citation_count=5000,
        )
        assert profile.h_index == 42


# ===================================================================
# S2 client new methods
# ===================================================================

class TestS2ClientNewMethods:
    @pytest.mark.asyncio
    async def test_search_by_title_exact_match(self):
        from src.agents.tools.s2_client import SemanticScholarClient

        mock_paper = _paper("p1", "Attention Is All You Need", 90000)

        async def mock_search(self, query, *, limit=10, **kwargs):
            from src.models.paper import SearchResult
            return SearchResult(query=query, total=1, papers=[mock_paper])

        with patch.object(SemanticScholarClient, "search_papers", mock_search):
            client = SemanticScholarClient(api_key="fake")
            result = await client.search_by_title("Attention Is All You Need")

        assert result is not None
        assert result.paper_id == "p1"

    @pytest.mark.asyncio
    async def test_search_by_title_no_match(self):
        from src.agents.tools.s2_client import SemanticScholarClient

        async def mock_search(self, query, *, limit=10, **kwargs):
            from src.models.paper import SearchResult
            return SearchResult(query=query, total=0, papers=[])

        with patch.object(SemanticScholarClient, "search_papers", mock_search):
            client = SemanticScholarClient(api_key="fake")
            result = await client.search_by_title("Nonexistent Paper Title XYZ")

        assert result is None

    def test_title_similarity(self):
        from src.agents.tools.s2_client import _title_similarity

        assert _title_similarity("attention is all you need", "attention is all you need") == 1.0
        assert _title_similarity("", "some text") == 0.0
        score = _title_similarity("attention is all you need", "attention is what you need")
        assert 0.5 < score < 1.0

    @pytest.mark.asyncio
    async def test_get_author_returns_dict(self):
        from src.agents.tools.s2_client import SemanticScholarClient

        mock_data = {
            "authorId": "123",
            "name": "Alice",
            "affiliations": ["MIT"],
            "paperCount": 50,
            "citationCount": 3000,
            "hIndex": 20,
        }

        async def mock_get(self, endpoint, params=None):
            return mock_data

        with patch.object(SemanticScholarClient, "_get", mock_get):
            client = SemanticScholarClient(api_key="fake")
            result = await client.get_author("123")

        assert result is not None
        assert result["name"] == "Alice"
        assert result["hIndex"] == 20

    @pytest.mark.asyncio
    async def test_get_author_papers(self):
        from src.agents.tools.s2_client import SemanticScholarClient

        mock_data = {
            "data": [
                {
                    "paperId": "p1",
                    "title": "Paper 1",
                    "abstract": "Abs",
                    "year": 2020,
                    "citationCount": 100,
                    "authors": [{"name": "Alice"}],
                    "url": "https://example.com",
                },
            ],
        }

        async def mock_get(self, endpoint, params=None):
            return mock_data

        with patch.object(SemanticScholarClient, "_get", mock_get):
            client = SemanticScholarClient(api_key="fake")
            papers = await client.get_author_papers("123")

        assert len(papers) == 1
        assert papers[0].title == "Paper 1"


# ===================================================================
# Agent base class
# ===================================================================

class TestBaseAgent:
    @pytest.mark.asyncio
    async def test_run_calls_execute_and_returns(self):
        from src.agents.landscape.agents.base import BaseAgent

        class DummyAgent(BaseAgent[str, PaperCorpus]):
            async def _execute(self, input_data, *, on_progress=None):
                return _corpus()

        agent = DummyAgent(name="TestAgent")
        result = await agent.run("test")
        assert isinstance(result, PaperCorpus)
        assert result.stats.total_papers == 1

    @pytest.mark.asyncio
    async def test_run_reports_progress(self):
        from src.agents.landscape.agents.base import BaseAgent

        events: list[dict] = []

        class DummyAgent(BaseAgent[str, PaperCorpus]):
            async def _execute(self, input_data, *, on_progress=None):
                await self._notify(on_progress, "working …")
                return _corpus()

        async def track(event: dict) -> None:
            events.append(event)

        agent = DummyAgent(name="TestAgent")
        await agent.run("test", on_progress=track)
        messages = [e.get("message", "") for e in events]
        assert any("starting" in m for m in messages)
        assert any("working" in m for m in messages)


# ===================================================================
# Critic (deterministic) tests
# ===================================================================

class TestCriticDeterministic:
    """The new Critic uses no LLM — only deterministic checks."""

    @pytest.mark.asyncio
    async def test_passes_with_healthy_data(self):
        from src.agents.landscape.agents.critic_agent import CriticAgent, CriticInput
        from src.models.landscape import CollaborationNetwork, ResearchGaps, TechTree

        scope = _scope()
        corpus = PaperCorpus(
            papers=[_paper(f"p{i}", f"Paper {i}") for i in range(15)],
            seed_paper_map={"Attention Is All You Need": "p0"},
            stats=CorpusStats(
                total_papers=15,
                seed_papers_found=1,
                seed_papers_expected=1,
            ),
        )
        tree = TechTree(nodes=[
            TechTreeNode(
                node_id="n1", label="Method", node_type="method",
                description="Desc", representative_paper_ids=["p0"],
            ),
        ], edges=[])

        agent = CriticAgent()
        report = await agent.run(CriticInput(
            scope=scope, corpus=corpus, tech_tree=tree,
            collaboration_network=CollaborationNetwork(),
            research_gaps=ResearchGaps(),
        ))
        assert report.passed

    @pytest.mark.asyncio
    async def test_fails_with_small_corpus(self):
        from src.agents.landscape.agents.critic_agent import CriticAgent, CriticInput
        from src.models.landscape import CollaborationNetwork, ResearchGaps, TechTree

        scope = _scope()
        corpus = PaperCorpus(
            papers=[_paper("p1")],
            seed_paper_map={"Attention Is All You Need": "p1"},
            stats=CorpusStats(total_papers=1, seed_papers_found=1, seed_papers_expected=1),
        )
        tree = TechTree(nodes=[
            TechTreeNode(
                node_id="n1", label="M", node_type="method",
                description="D", representative_paper_ids=["p1"],
            ),
        ], edges=[])

        agent = CriticAgent()
        report = await agent.run(CriticInput(
            scope=scope, corpus=corpus, tech_tree=tree,
            collaboration_network=CollaborationNetwork(),
            research_gaps=ResearchGaps(),
        ))
        assert not report.passed
        assert "retrieval" in report.retry_targets

    @pytest.mark.asyncio
    async def test_forwards_quality_flags(self):
        from src.agents.landscape.agents.critic_agent import CriticAgent, CriticInput
        from src.models.landscape import CollaborationNetwork, ResearchGaps, TechTree

        scope = _scope()
        corpus = PaperCorpus(
            papers=[_paper(f"p{i}") for i in range(15)],
            seed_paper_map={"Attention Is All You Need": "p0"},
            stats=CorpusStats(
                total_papers=15, seed_papers_found=1, seed_papers_expected=1,
                quality_flags=["low_seed_coverage"],
            ),
        )
        tree = TechTree(nodes=[
            TechTreeNode(
                node_id="n1", label="M", node_type="method",
                description="D", representative_paper_ids=["p0"],
            ),
        ], edges=[])

        agent = CriticAgent()
        report = await agent.run(CriticInput(
            scope=scope, corpus=corpus, tech_tree=tree,
            collaboration_network=CollaborationNetwork(),
            research_gaps=ResearchGaps(),
        ))
        flag_cats = [i.category for i in report.issues]
        assert any("low_seed_coverage" in c for c in flag_cats)


# ===================================================================
# Schema additions
# ===================================================================

class TestCorpusStatsQualityFlags:
    def test_default_empty(self):
        stats = CorpusStats()
        assert stats.quality_flags == []

    def test_serialisation_round_trip(self):
        stats = CorpusStats(quality_flags=["small_corpus", "low_seed_coverage"])
        restored = CorpusStats.model_validate_json(stats.model_dump_json())
        assert restored.quality_flags == ["small_corpus", "low_seed_coverage"]


class TestLandscapeMetaQuality:
    def test_default_complete(self):
        from src.models.landscape import LandscapeMeta
        from datetime import datetime, timezone
        meta = LandscapeMeta(topic="X", generated_at=datetime.now(timezone.utc))
        assert meta.quality == "complete"

    def test_degraded(self):
        from src.models.landscape import LandscapeMeta
        from datetime import datetime, timezone
        meta = LandscapeMeta(
            topic="X", generated_at=datetime.now(timezone.utc), quality="degraded",
        )
        assert meta.quality == "degraded"


class TestTechTreeNodeUnverified:
    def test_unverified_node_type(self):
        node = TechTreeNode(
            node_id="d1", label="Degraded", node_type="unverified",
            description="Fallback", representative_paper_ids=[],
        )
        assert node.node_type == "unverified"


# ===================================================================
# Orchestrator import chain
# ===================================================================

class TestOrchestratorImport:
    def test_public_import(self):
        from src.agents.landscape import run_landscape_pipeline
        assert callable(run_landscape_pipeline)

    def test_orchestrator_import(self):
        from src.agents.landscape.orchestrator import run_landscape_pipeline
        assert callable(run_landscape_pipeline)

    def test_task_manager_import(self):
        from src.services.task_manager import run_landscape_task
        assert callable(run_landscape_task)

    def test_pipeline_error_importable(self):
        from src.agents.landscape.orchestrator import LandscapePipelineError
        assert issubclass(LandscapePipelineError, Exception)
