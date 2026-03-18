"""T12-T13: Tests for web_search.py — Tavily integration."""

from __future__ import annotations

import pytest

from src.agents.tools._schemas import WebSearchResult
from src.agents.tools.web_search import tavily_search


# ------------------------------------------------------------------
# T12: Missing API key returns empty result, no exception
# ------------------------------------------------------------------

async def test_t12_missing_key_returns_empty(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    result = await tavily_search("test query")

    assert isinstance(result, WebSearchResult)
    assert result.query == "test query"
    assert result.results == []


# ------------------------------------------------------------------
# T13: Live web search (requires TAVILY_API_KEY)
# ------------------------------------------------------------------

@pytest.mark.live
async def test_t13_live_tavily_search():
    result = await tavily_search("latest breakthrough in AI 2024", max_results=3)

    assert len(result.results) >= 1
    for item in result.results:
        assert item.title
        assert item.url
        assert len(item.content) > 0
