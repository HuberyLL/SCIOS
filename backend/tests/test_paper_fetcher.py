"""T8-T11: Tests for paper_fetcher.py — multi-source search & PDF degradation."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from src.agents.tools._schemas import PaperResult
from src.agents.tools.paper_fetcher import (
    PaperSearcher,
    _deduplicate,
)
from src.agents.tools.sources.arxiv import ArxivFetcher
from src.agents.tools.sources.pubmed import PubMedFetcher


def _make_paper(**overrides) -> PaperResult:
    defaults = dict(paper_id="id", title="Title", source="arxiv")
    defaults.update(overrides)
    return PaperResult(**defaults)


# ------------------------------------------------------------------
# T8: Partial source failure — PubMed down, arXiv still returns
# ------------------------------------------------------------------

async def test_t8_partial_source_failure(monkeypatch):
    arxiv_papers = [
        _make_paper(paper_id="a1", title="Arxiv Paper 1", source="arxiv"),
        _make_paper(paper_id="a2", title="Arxiv Paper 2", source="arxiv"),
    ]

    async def arxiv_search(self, query, *, max_results=10):
        return arxiv_papers

    async def pubmed_search(self, query, *, max_results=10):
        raise httpx.ReadTimeout("simulated PubMed timeout")

    monkeypatch.setattr(ArxivFetcher, "search", arxiv_search)
    monkeypatch.setattr(PubMedFetcher, "search", pubmed_search)

    searcher = PaperSearcher(fetchers={
        "arxiv": ArxivFetcher(),
        "pubmed": PubMedFetcher(),
    })
    result = await searcher.search("test query", sources=["arxiv", "pubmed"])

    assert len(result.papers) == 2
    assert all(p.source == "arxiv" for p in result.papers)


# ------------------------------------------------------------------
# T9: PDF extraction degradation — 404 falls back to abstract
# ------------------------------------------------------------------

async def test_t9_pdf_fallback_to_abstract():
    paper = _make_paper(
        paper_id="test",
        title="T",
        pdf_url="https://arxiv.org/pdf/test.pdf",
        abstract="fallback abstract",
        source="arxiv",
    )

    with respx.mock:
        respx.get("https://arxiv.org/pdf/test.pdf").mock(
            return_value=httpx.Response(404, text="Not Found")
        )
        text = await ArxivFetcher().fetch_full_text(paper)

    assert text == "fallback abstract"


async def test_t9_no_pdf_url_returns_abstract():
    paper = _make_paper(pdf_url="", abstract="just the abstract")
    text = await ArxivFetcher().fetch_full_text(paper)
    assert text == "just the abstract"


# ------------------------------------------------------------------
# T10: Deduplication logic (three-level)
# ------------------------------------------------------------------

def test_t10_dedup_by_doi():
    p1 = _make_paper(paper_id="1", doi="10.1/a", title="Paper A", source="arxiv", url="https://a.com/1")
    p2 = _make_paper(paper_id="2", doi="10.1/a", title="Paper A from PubMed", source="pubmed", url="https://b.com/2")

    result = _deduplicate([p1, p2])
    assert len(result) == 1
    assert result[0].paper_id == "1"


def test_t10_dedup_by_url():
    p1 = _make_paper(paper_id="1", doi="", title="Paper A", url="https://example.com/paper/1")
    p2 = _make_paper(paper_id="2", doi="", title="Different Title", url="https://example.com/paper/1")

    result = _deduplicate([p1, p2])
    assert len(result) == 1


def test_t10_dedup_by_title_year():
    p1 = _make_paper(paper_id="1", doi="", title="Paper B", source="arxiv", url="https://a.com", published_date="2024-01-01")
    p2 = _make_paper(paper_id="2", doi="", title="paper b", source="pubmed", url="https://b.com", published_date="2024-06-15")

    result = _deduplicate([p1, p2])
    assert len(result) == 1
    assert result[0].paper_id == "1"


def test_t10_dedup_empty_input():
    assert _deduplicate([]) == []


def test_t10_different_years_kept():
    p1 = _make_paper(paper_id="1", doi="", title="Paper C", url="https://a.com", published_date="2023-01-01")
    p2 = _make_paper(paper_id="2", doi="", title="Paper C", url="https://b.com", published_date="2024-01-01")

    result = _deduplicate([p1, p2])
    assert len(result) == 2


# ------------------------------------------------------------------
# T11: Live arXiv connectivity
# ------------------------------------------------------------------

@pytest.mark.live
async def test_t11_live_arxiv_search():
    fetcher = ArxivFetcher()
    papers = await fetcher.search("quantum computing", max_results=1)

    assert len(papers) >= 1
    assert "arxiv.org/pdf/" in papers[0].pdf_url
