"""Tests for the monitoring pipeline (src/agents/monitoring/pipeline.py).

All external calls (Semantic Scholar, Tavily, LLM) are fully mocked so
that no real network or API key is required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.agents.monitoring.pipeline import (
    _deduplicate_papers,
    _format_papers,
    _format_web,
    run_monitoring_scan,
)
from src.agents.monitoring.schemas import DailyBrief, HotPaper
from src.agents.tools._schemas import (
    PaperResult,
    SearchResult,
    WebSearchItem,
    WebSearchResult,
)

# ---------------------------------------------------------------------------
# Shared fake data
# ---------------------------------------------------------------------------

FAKE_PAPER = PaperResult(
    paper_id="abc123",
    title="Attention Is All You Need",
    authors=["Vaswani", "Shazeer", "Parmar"],
    abstract="We propose a new simple network architecture, the Transformer.",
    doi="10.1234/fake",
    published_date="2026",
    url="https://example.com/paper1",
    source="semantic_scholar",
    categories=[],
    citation_count=100,
)

FAKE_WEB_ITEM = WebSearchItem(
    title="Transformers are revolutionising AI",
    url="https://example.com/news",
    content="A recent blog post about transformers and their impact.",
    score=0.95,
)

FAKE_BRIEF = DailyBrief(
    topic="transformers",
    since_date="2026-03-17",
    new_hot_papers=[
        HotPaper(
            title="Attention Is All You Need",
            authors=["Vaswani", "Shazeer"],
            year=2026,
            url="https://example.com/paper1",
            citation_count=100,
            relevance_reason="Foundational transformer paper",
        )
    ],
    trend_summary="Transformers continue to dominate NLP research.",
    sources=["https://example.com/paper1"],
)


# ===================================================================
# Unit tests — helper functions
# ===================================================================


class TestFormatPapers:
    def test_empty_list(self):
        assert _format_papers([]) == "(no papers found)"

    def test_single_paper(self):
        text = _format_papers([FAKE_PAPER])
        assert "Attention Is All You Need" in text
        assert "Vaswani" in text
        assert "Citations: 100" in text

    def test_many_authors_truncated(self):
        paper = FAKE_PAPER.model_copy(
            update={"authors": ["A", "B", "C", "D", "E", "F", "G"]}
        )
        text = _format_papers([paper])
        assert "et al." in text


class TestFormatWeb:
    def test_empty_list(self):
        assert _format_web([]) == "(no web results)"

    def test_single_item(self):
        text = _format_web([FAKE_WEB_ITEM])
        assert "Transformers are revolutionising AI" in text
        assert "https://example.com/news" in text


class TestDeduplicatePapers:
    def test_removes_exact_title_duplicates(self):
        dup = FAKE_PAPER.model_copy(update={"paper_id": "dup999"})
        result = _deduplicate_papers([FAKE_PAPER, dup])
        assert len(result) == 1

    def test_case_insensitive(self):
        upper = FAKE_PAPER.model_copy(update={"title": "ATTENTION IS ALL YOU NEED"})
        result = _deduplicate_papers([FAKE_PAPER, upper])
        assert len(result) == 1

    def test_preserves_order(self):
        p1 = FAKE_PAPER.model_copy(update={"title": "First"})
        p2 = FAKE_PAPER.model_copy(update={"title": "Second"})
        result = _deduplicate_papers([p1, p2])
        assert [p.title for p in result] == ["First", "Second"]


# ===================================================================
# Integration tests — run_monitoring_scan
# ===================================================================


class TestRunMonitoringScan:
    async def test_happy_path(self, mocker):
        """S2 + Tavily + LLM all succeed -> valid DailyBrief."""
        mocker.patch(
            "src.agents.monitoring.pipeline._fetch_s2",
            new_callable=AsyncMock,
            return_value=[FAKE_PAPER],
        )
        mocker.patch(
            "src.agents.monitoring.pipeline._fetch_web",
            new_callable=AsyncMock,
            return_value=[FAKE_WEB_ITEM],
        )
        mocker.patch(
            "src.agents.monitoring.pipeline.call_llm",
            new_callable=AsyncMock,
            return_value=FAKE_BRIEF,
        )

        brief = await run_monitoring_scan("transformers", "2026-03-17")

        assert brief.topic == "transformers"
        assert brief.since_date == "2026-03-17"
        assert len(brief.new_hot_papers) == 1
        assert brief.trend_summary != ""

    async def test_s2_fails_tavily_succeeds(self, mocker):
        """Graceful degradation when S2 returns nothing."""
        mocker.patch(
            "src.agents.monitoring.pipeline._fetch_s2",
            new_callable=AsyncMock,
            return_value=[],
        )
        mocker.patch(
            "src.agents.monitoring.pipeline._fetch_web",
            new_callable=AsyncMock,
            return_value=[FAKE_WEB_ITEM],
        )
        mocker.patch(
            "src.agents.monitoring.pipeline.call_llm",
            new_callable=AsyncMock,
            return_value=FAKE_BRIEF,
        )

        brief = await run_monitoring_scan("transformers", "2026-03-17")
        assert brief.topic == "transformers"
        assert len(brief.new_hot_papers) >= 1

    async def test_tavily_fails_s2_succeeds(self, mocker):
        """Graceful degradation when Tavily returns nothing."""
        mocker.patch(
            "src.agents.monitoring.pipeline._fetch_s2",
            new_callable=AsyncMock,
            return_value=[FAKE_PAPER],
        )
        mocker.patch(
            "src.agents.monitoring.pipeline._fetch_web",
            new_callable=AsyncMock,
            return_value=[],
        )
        mocker.patch(
            "src.agents.monitoring.pipeline.call_llm",
            new_callable=AsyncMock,
            return_value=FAKE_BRIEF,
        )

        brief = await run_monitoring_scan("transformers", "2026-03-17")
        assert brief.topic == "transformers"

    async def test_both_sources_empty_returns_empty_brief(self, mocker):
        """Total retrieval failure -> empty DailyBrief, no LLM call."""
        mocker.patch(
            "src.agents.monitoring.pipeline._fetch_s2",
            new_callable=AsyncMock,
            return_value=[],
        )
        mocker.patch(
            "src.agents.monitoring.pipeline._fetch_web",
            new_callable=AsyncMock,
            return_value=[],
        )
        mock_llm = mocker.patch(
            "src.agents.monitoring.pipeline.call_llm",
            new_callable=AsyncMock,
        )

        brief = await run_monitoring_scan("transformers", "2026-03-17")

        assert brief.topic == "transformers"
        assert brief.since_date == "2026-03-17"
        assert brief.new_hot_papers == []
        assert brief.trend_summary == ""
        mock_llm.assert_not_called()

    async def test_llm_failure_returns_empty_brief(self, mocker):
        """LLM exception -> empty DailyBrief returned (no crash)."""
        mocker.patch(
            "src.agents.monitoring.pipeline._fetch_s2",
            new_callable=AsyncMock,
            return_value=[FAKE_PAPER],
        )
        mocker.patch(
            "src.agents.monitoring.pipeline._fetch_web",
            new_callable=AsyncMock,
            return_value=[FAKE_WEB_ITEM],
        )
        mocker.patch(
            "src.agents.monitoring.pipeline.call_llm",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM unavailable"),
        )

        brief = await run_monitoring_scan("transformers", "2026-03-17")

        assert brief.topic == "transformers"
        assert brief.new_hot_papers == []
        assert brief.trend_summary == ""

    async def test_duplicate_papers_are_deduplicated(self, mocker):
        """Papers with the same title should appear only once in context."""
        dup = FAKE_PAPER.model_copy(update={"paper_id": "dup999"})
        mocker.patch(
            "src.agents.monitoring.pipeline._fetch_s2",
            new_callable=AsyncMock,
            return_value=[FAKE_PAPER, dup],
        )
        mocker.patch(
            "src.agents.monitoring.pipeline._fetch_web",
            new_callable=AsyncMock,
            return_value=[],
        )
        mock_llm = mocker.patch(
            "src.agents.monitoring.pipeline.call_llm",
            new_callable=AsyncMock,
            return_value=FAKE_BRIEF,
        )

        await run_monitoring_scan("transformers", "2026-03-17")

        call_args = mock_llm.call_args
        user_msg = call_args[0][0][1]["content"]
        assert user_msg.count("Attention Is All You Need") == 1
