"""Tests for SearchAcademicPapersTool and WebSearchTool."""

from __future__ import annotations

import json

import pytest

from src.agents.tools._schemas import (
    PaperResult,
    SearchResult,
    WebSearchItem,
    WebSearchResult,
)
from src.agents.assistant.tools.academic_tools import (
    SearchAcademicPapersTool,
    WebSearchTool,
    _ABSTRACT_CHAR_LIMIT,
    _WEB_CONTENT_CHAR_LIMIT,
)


# ── Fixtures ────────────────────────────────────────────────────────────


def _make_paper(title: str = "A Paper", abstract: str = "Short abstract.") -> PaperResult:
    return PaperResult(
        paper_id="abc123",
        title=title,
        authors=["Alice", "Bob", "Charlie"],
        abstract=abstract,
        doi="10.1234/test",
        published_date="2024-01-15",
        pdf_url="https://example.com/paper.pdf",
        url="https://example.com/paper",
        source="semantic_scholar",
        categories=[],
        citation_count=42,
    )


# ── SearchAcademicPapersTool ────────────────────────────────────────────


class TestSearchAcademicPapersTool:
    @pytest.fixture
    def tool(self):
        return SearchAcademicPapersTool()

    @pytest.mark.asyncio
    async def test_returns_papers(self, tool, monkeypatch):
        fake_result = SearchResult(
            query="transformers",
            total=1,
            papers=[_make_paper()],
        )

        async def _fake_search(self, query, *, limit=10, **kw):
            return fake_result

        monkeypatch.setattr(
            "src.agents.assistant.tools.academic_tools.SemanticScholarClient.search_papers",
            _fake_search,
        )

        raw = await tool.execute(query="transformers", limit=5)
        data = json.loads(raw)

        assert data["total"] == 1
        assert len(data["papers"]) == 1
        paper = data["papers"][0]
        assert paper["title"] == "A Paper"
        assert paper["citation_count"] == 42
        assert paper["pdf_url"] == "https://example.com/paper.pdf"
        assert paper["year"] == "2024"

    @pytest.mark.asyncio
    async def test_abstract_truncation(self, tool, monkeypatch):
        long_abstract = "x" * 500
        fake_result = SearchResult(
            query="test",
            total=1,
            papers=[_make_paper(abstract=long_abstract)],
        )

        async def _fake_search(self, query, *, limit=10, **kw):
            return fake_result

        monkeypatch.setattr(
            "src.agents.assistant.tools.academic_tools.SemanticScholarClient.search_papers",
            _fake_search,
        )

        raw = await tool.execute(query="test")
        data = json.loads(raw)
        abstract = data["papers"][0]["abstract"]
        assert len(abstract) == _ABSTRACT_CHAR_LIMIT + 3  # +3 for "..."
        assert abstract.endswith("...")

    @pytest.mark.asyncio
    async def test_empty_results(self, tool, monkeypatch):
        async def _fake_search(self, query, *, limit=10, **kw):
            return SearchResult(query=query)

        monkeypatch.setattr(
            "src.agents.assistant.tools.academic_tools.SemanticScholarClient.search_papers",
            _fake_search,
        )

        raw = await tool.execute(query="nonexistent_topic_xyz")
        data = json.loads(raw)
        assert data["total"] == 0
        assert data["papers"] == []

    @pytest.mark.asyncio
    async def test_network_error(self, tool, monkeypatch):
        async def _boom(self, query, *, limit=10, **kw):
            raise ConnectionError("network down")

        monkeypatch.setattr(
            "src.agents.assistant.tools.academic_tools.SemanticScholarClient.search_papers",
            _boom,
        )

        result = await tool.execute(query="test")
        assert "Search failed" in result


# ── WebSearchTool ───────────────────────────────────────────────────────


class TestWebSearchTool:
    @pytest.fixture
    def tool(self):
        return WebSearchTool()

    @pytest.mark.asyncio
    async def test_returns_results(self, tool, monkeypatch):
        fake_result = WebSearchResult(
            query="deep learning tutorial",
            results=[
                WebSearchItem(
                    title="DL Guide",
                    url="https://example.com",
                    content="A great guide to deep learning.",
                    score=0.95,
                ),
            ],
        )

        async def _fake_tavily(query, **kw):
            return fake_result

        monkeypatch.setattr(
            "src.agents.assistant.tools.academic_tools.tavily_search",
            _fake_tavily,
        )

        raw = await tool.execute(query="deep learning tutorial")
        data = json.loads(raw)
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "DL Guide"

    @pytest.mark.asyncio
    async def test_content_truncation(self, tool, monkeypatch):
        long_content = "y" * 800
        fake_result = WebSearchResult(
            query="test",
            results=[
                WebSearchItem(title="T", url="https://x.com", content=long_content, score=0.5),
            ],
        )

        async def _fake_tavily(query, **kw):
            return fake_result

        monkeypatch.setattr(
            "src.agents.assistant.tools.academic_tools.tavily_search",
            _fake_tavily,
        )

        raw = await tool.execute(query="test")
        data = json.loads(raw)
        content = data["results"][0]["content"]
        assert len(content) == _WEB_CONTENT_CHAR_LIMIT + 3
        assert content.endswith("...")

    @pytest.mark.asyncio
    async def test_empty_results(self, tool, monkeypatch):
        async def _fake_tavily(query, **kw):
            return WebSearchResult(query=query)

        monkeypatch.setattr(
            "src.agents.assistant.tools.academic_tools.tavily_search",
            _fake_tavily,
        )

        raw = await tool.execute(query="nonexistent")
        data = json.loads(raw)
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_network_error(self, tool, monkeypatch):
        async def _boom(query, **kw):
            raise ConnectionError("tavily down")

        monkeypatch.setattr(
            "src.agents.assistant.tools.academic_tools.tavily_search",
            _boom,
        )

        result = await tool.execute(query="test")
        assert "Web search failed" in result
