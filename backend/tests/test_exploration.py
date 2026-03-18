"""Unit tests for the Exploration pipeline (planner / retriever / synthesizer / pipeline).

Every external dependency (LLM, Semantic Scholar, arXiv, Tavily) is mocked —
these tests verify Python-level correctness only.
"""

from __future__ import annotations

import pytest

from src.agents.exploration.schemas import (
    CoreConcept,
    ExplorationReport,
    RawRetrievedData,
    RecommendedPaper,
    ScholarProfile,
    SearchPlan,
    TrendsAndChallenges,
)
from src.agents.tools._schemas import (
    PaperResult,
    SearchResult,
    WebSearchItem,
    WebSearchResult,
)

# ---------------------------------------------------------------------------
# Reusable fake data factories
# ---------------------------------------------------------------------------

FAKE_SEARCH_PLAN = SearchPlan(
    paper_keywords=["transformer healthcare", "clinical NLP"],
    web_queries=["latest trends in medical AI"],
    focus_areas=["clinical NLP", "medical imaging"],
)


def _make_paper(id_: str, title: str, citations: int = 0) -> PaperResult:
    return PaperResult(
        paper_id=id_,
        title=title,
        authors=["Alice", "Bob"],
        abstract="A short abstract for testing purposes.",
        doi=f"10.1234/{id_}",
        published_date="2024-01-01",
        url=f"https://example.com/{id_}",
        source="semantic_scholar",
        citation_count=citations,
    )


FAKE_S2_RESULT = SearchResult(
    query="transformer healthcare",
    total=3,
    papers=[
        _make_paper("s2-1", "Transformers for EHR", citations=500),
        _make_paper("s2-2", "Clinical BERT", citations=300),
        _make_paper("s2-3", "Low-citation paper", citations=10),
    ],
)

FAKE_ARXIV_RESULT = SearchResult(
    query="transformer healthcare",
    total=1,
    papers=[_make_paper("ax-1", "ArXiv Med-NLP", citations=50)],
)

FAKE_WEB_RESULT = WebSearchResult(
    query="latest trends in medical AI",
    results=[
        WebSearchItem(
            title="Medical AI Trends 2024",
            url="https://example.com/trends",
            content="Medical AI is rapidly evolving...",
            score=0.95,
        ),
    ],
)

FAKE_CITATION_PAPERS = [
    _make_paper("cite-1", "Citing paper A", citations=20),
    _make_paper("cite-2", "Citing paper B", citations=15),
]

FAKE_REPORT = ExplorationReport(
    topic="Transformer in healthcare",
    core_concepts=[
        CoreConcept(term="Transformer", explanation="Self-attention architecture."),
    ],
    key_scholars=[
        ScholarProfile(
            name="Dr. Test",
            affiliation="Test University",
            representative_works=["Paper A"],
            contribution_summary="Pioneered test research.",
        ),
    ],
    must_read_papers=[
        RecommendedPaper(
            title="Attention Is All You Need",
            authors=["Vaswani et al."],
            year=2017,
            venue="NeurIPS",
            citation_count=90000,
            summary="Introduced the Transformer architecture.",
            url="https://arxiv.org/abs/1706.03762",
        ),
    ],
    trends_and_challenges=TrendsAndChallenges(
        recent_progress="Rapid adoption in clinical settings.",
        emerging_trends=["Multimodal medical AI"],
        open_challenges=["Data privacy"],
        future_directions="Federated learning for hospitals.",
    ),
    sources=["https://arxiv.org/abs/1706.03762"],
)


# ===================================================================
# Test 1: Planner
# ===================================================================

class TestPlanner:
    """generate_search_plan() should delegate to call_llm and return the plan."""

    async def test_returns_search_plan(self, mocker):
        mock_call = mocker.patch(
            "src.agents.exploration.planner.call_llm",
            return_value=FAKE_SEARCH_PLAN,
        )
        from src.agents.exploration.planner import generate_search_plan

        plan = await generate_search_plan("Transformer in healthcare")

        assert isinstance(plan, SearchPlan)
        assert plan.paper_keywords == ["transformer healthcare", "clinical NLP"]
        assert len(plan.web_queries) == 1
        assert len(plan.focus_areas) == 2

        mock_call.assert_awaited_once()
        args, kwargs = mock_call.call_args
        messages = args[0]
        response_fmt = args[1] if len(args) > 1 else kwargs.get("response_format")
        assert response_fmt is SearchPlan
        assert any("Transformer in healthcare" in m["content"] for m in messages)

    async def test_passes_different_topics(self, mocker):
        mock_call = mocker.patch(
            "src.agents.exploration.planner.call_llm",
            return_value=FAKE_SEARCH_PLAN,
        )
        from src.agents.exploration.planner import generate_search_plan

        await generate_search_plan("quantum computing error correction")

        messages = mock_call.call_args[0][0]
        assert any("quantum computing error correction" in m["content"] for m in messages)


# ===================================================================
# Test 2: Retriever
# ===================================================================

class TestRetrieverPickTopCited:
    """_pick_top_cited should deduplicate by paper_id and sort by citation_count."""

    def test_basic_ranking(self):
        from src.agents.exploration.retriever import _pick_top_cited

        results = [
            SearchResult(
                query="q1",
                papers=[
                    _make_paper("a", "Paper A", citations=10),
                    _make_paper("b", "Paper B", citations=100),
                    _make_paper("c", "Paper C", citations=50),
                ],
            ),
        ]
        top2 = _pick_top_cited(results, 2)
        assert len(top2) == 2
        assert top2[0].paper_id == "b"
        assert top2[1].paper_id == "c"

    def test_deduplication(self):
        from src.agents.exploration.retriever import _pick_top_cited

        results = [
            SearchResult(query="q1", papers=[_make_paper("dup", "Same", citations=10)]),
            SearchResult(query="q2", papers=[_make_paper("dup", "Same", citations=10)]),
        ]
        top = _pick_top_cited(results, 5)
        assert len(top) == 1

    def test_skips_empty_paper_id(self):
        from src.agents.exploration.retriever import _pick_top_cited

        results = [
            SearchResult(
                query="q",
                papers=[
                    PaperResult(paper_id="", title="No ID", citation_count=999),
                    _make_paper("valid", "Valid", citations=1),
                ],
            ),
        ]
        top = _pick_top_cited(results, 5)
        assert len(top) == 1
        assert top[0].paper_id == "valid"

    def test_empty_input(self):
        from src.agents.exploration.retriever import _pick_top_cited

        assert _pick_top_cited([], 3) == []

    def test_multiple_results_merged(self):
        from src.agents.exploration.retriever import _pick_top_cited

        results = [
            SearchResult(query="q1", papers=[_make_paper("x", "X", citations=5)]),
            SearchResult(query="q2", papers=[_make_paper("y", "Y", citations=15)]),
            SearchResult(query="q3", papers=[_make_paper("z", "Z", citations=10)]),
        ]
        top = _pick_top_cited(results, 2)
        assert [p.paper_id for p in top] == ["y", "z"]


class TestRetrieverFetchAll:
    """fetch_all_context() should aggregate results from mocked tool calls."""

    async def test_assembles_raw_data(self, mocker):
        mocker.patch(
            "src.agents.exploration.retriever.SemanticScholarClient"
        ).return_value = self._mock_s2_client(mocker)

        mocker.patch(
            "src.agents.exploration.retriever.PaperSearcher"
        ).return_value = self._mock_paper_searcher(mocker)

        mocker.patch(
            "src.agents.exploration.retriever.tavily_search",
            side_effect=self._mock_tavily,
        )

        from src.agents.exploration.retriever import fetch_all_context

        result = await fetch_all_context(FAKE_SEARCH_PLAN)

        assert isinstance(result, RawRetrievedData)
        assert len(result.s2_results) == len(FAKE_SEARCH_PLAN.paper_keywords)
        assert len(result.arxiv_results) == len(FAKE_SEARCH_PLAN.paper_keywords)
        assert len(result.web_results) == len(FAKE_SEARCH_PLAN.web_queries)

        total_s2_papers = sum(len(sr.papers) for sr in result.s2_results)
        assert total_s2_papers > 0

    async def test_handles_tool_exceptions_gracefully(self, mocker):
        """If all external tools raise, fetch_all_context still returns a valid object."""
        s2_mock = mocker.AsyncMock()
        s2_mock.search_papers = mocker.AsyncMock(side_effect=RuntimeError("S2 down"))
        s2_mock.get_paper_citations = mocker.AsyncMock(return_value=[])
        mocker.patch(
            "src.agents.exploration.retriever.SemanticScholarClient"
        ).return_value = s2_mock

        arxiv_mock = mocker.AsyncMock()
        arxiv_mock.search = mocker.AsyncMock(side_effect=RuntimeError("arXiv down"))
        mocker.patch(
            "src.agents.exploration.retriever.PaperSearcher"
        ).return_value = arxiv_mock

        mocker.patch(
            "src.agents.exploration.retriever.tavily_search",
            side_effect=RuntimeError("Tavily down"),
        )

        from src.agents.exploration.retriever import fetch_all_context

        result = await fetch_all_context(FAKE_SEARCH_PLAN)

        assert isinstance(result, RawRetrievedData)
        for sr in result.s2_results:
            assert sr.papers == []
        for sr in result.arxiv_results:
            assert sr.papers == []
        for wr in result.web_results:
            assert wr.results == []

    # -- helper mocks --

    @staticmethod
    def _mock_s2_client(mocker):
        client = mocker.AsyncMock()
        client.search_papers = mocker.AsyncMock(return_value=FAKE_S2_RESULT)
        client.get_paper_citations = mocker.AsyncMock(return_value=FAKE_CITATION_PAPERS)
        return client

    @staticmethod
    def _mock_paper_searcher(mocker):
        searcher = mocker.AsyncMock()
        searcher.search = mocker.AsyncMock(return_value=FAKE_ARXIV_RESULT)
        return searcher

    @staticmethod
    async def _mock_tavily(query: str, **kwargs) -> WebSearchResult:
        return FAKE_WEB_RESULT


# ===================================================================
# Test 3: Synthesizer _format_context
# ===================================================================

class TestFormatContext:
    """_format_context should serialize RawRetrievedData into a readable string."""

    def test_with_full_data(self):
        from src.agents.exploration.synthesizer import _format_context

        raw = RawRetrievedData(
            s2_results=[FAKE_S2_RESULT],
            arxiv_results=[FAKE_ARXIV_RESULT],
            web_results=[FAKE_WEB_RESULT],
            citation_map={"s2-1": FAKE_CITATION_PAPERS},
        )
        text = _format_context(raw)

        assert "## Papers" in text
        assert "Transformers for EHR" in text
        assert "ArXiv Med-NLP" in text
        assert "## Citation relationships" in text
        assert "s2-1 cited by:" in text
        assert "## Web:" in text
        assert "Medical AI Trends 2024" in text

    def test_deduplicates_papers(self):
        from src.agents.exploration.synthesizer import _format_context

        same_paper = _make_paper("dup-1", "Same Title")
        raw = RawRetrievedData(
            s2_results=[SearchResult(query="q", papers=[same_paper])],
            arxiv_results=[SearchResult(query="q", papers=[same_paper])],
        )
        text = _format_context(raw)
        assert text.count("[P") == 1

    def test_empty_data(self):
        from src.agents.exploration.synthesizer import _format_context

        raw = RawRetrievedData()
        text = _format_context(raw)
        assert text == "(No evidence retrieved.)"

    def test_truncates_long_abstract(self):
        from src.agents.exploration.synthesizer import MAX_ABSTRACT_CHARS, _format_context

        long_paper = _make_paper("long", "Long Abstract Paper")
        long_paper.abstract = "x" * 1000
        raw = RawRetrievedData(
            s2_results=[SearchResult(query="q", papers=[long_paper])],
        )
        text = _format_context(raw)
        assert "…" in text
        # The abstract portion should be truncated
        assert "x" * (MAX_ABSTRACT_CHARS + 1) not in text


# ===================================================================
# Test 4: Pipeline end-to-end (all mocked)
# ===================================================================

class TestPipeline:
    """run_exploration() should chain planner → retriever → synthesizer."""

    async def test_end_to_end(self, mocker):
        mocker.patch(
            "src.agents.exploration.pipeline.generate_search_plan",
            return_value=FAKE_SEARCH_PLAN,
        )
        mocker.patch(
            "src.agents.exploration.pipeline.fetch_all_context",
            return_value=RawRetrievedData(
                s2_results=[FAKE_S2_RESULT],
                arxiv_results=[FAKE_ARXIV_RESULT],
                web_results=[FAKE_WEB_RESULT],
                citation_map={},
            ),
        )
        mocker.patch(
            "src.agents.exploration.pipeline.synthesize_report",
            return_value=FAKE_REPORT,
        )

        from src.agents.exploration.pipeline import run_exploration

        report = await run_exploration("Transformer in healthcare")

        assert isinstance(report, ExplorationReport)
        assert report.topic == "Transformer in healthcare"
        assert len(report.core_concepts) >= 1
        assert len(report.key_scholars) >= 1
        assert len(report.must_read_papers) >= 1
        assert report.trends_and_challenges.recent_progress != ""
        assert len(report.sources) >= 1

    async def test_calls_stages_in_order(self, mocker):
        """Verify the three stages are called exactly once and in the right order."""
        call_order: list[str] = []

        async def mock_planner(topic):
            call_order.append("planner")
            return FAKE_SEARCH_PLAN

        async def mock_retriever(plan):
            call_order.append("retriever")
            return RawRetrievedData()

        async def mock_synthesizer(topic, raw_data):
            call_order.append("synthesizer")
            return FAKE_REPORT

        mocker.patch(
            "src.agents.exploration.pipeline.generate_search_plan",
            side_effect=mock_planner,
        )
        mocker.patch(
            "src.agents.exploration.pipeline.fetch_all_context",
            side_effect=mock_retriever,
        )
        mocker.patch(
            "src.agents.exploration.pipeline.synthesize_report",
            side_effect=mock_synthesizer,
        )

        from src.agents.exploration.pipeline import run_exploration

        await run_exploration("any topic")

        assert call_order == ["planner", "retriever", "synthesizer"]

    async def test_planner_output_feeds_retriever(self, mocker):
        """Verify that the SearchPlan from the planner is passed to the retriever."""
        captured_plan = {}

        async def mock_retriever(plan):
            captured_plan["plan"] = plan
            return RawRetrievedData()

        mocker.patch(
            "src.agents.exploration.pipeline.generate_search_plan",
            return_value=FAKE_SEARCH_PLAN,
        )
        mocker.patch(
            "src.agents.exploration.pipeline.fetch_all_context",
            side_effect=mock_retriever,
        )
        mocker.patch(
            "src.agents.exploration.pipeline.synthesize_report",
            return_value=FAKE_REPORT,
        )

        from src.agents.exploration.pipeline import run_exploration

        await run_exploration("test topic")

        assert captured_plan["plan"] is FAKE_SEARCH_PLAN
