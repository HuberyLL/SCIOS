"""T8-T11: Tests for paper_fetcher.py — multi-source search & PDF degradation."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from src.agents.tools._schemas import PaperResult
from src.agents.tools.paper_fetcher import (
    ArxivFetcher,
    PaperSearcher,
    PubMedFetcher,
    _deduplicate,
)


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

    searcher = PaperSearcher()
    result = await searcher.search("test query")

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
# T10: Deduplication logic
# ------------------------------------------------------------------

def test_t10_dedup_by_doi_and_title():
    p1 = _make_paper(paper_id="1", doi="10.1/a", title="Paper A", source="arxiv")
    p2 = _make_paper(paper_id="2", doi="10.1/a", title="Paper A from PubMed", source="pubmed")
    p3 = _make_paper(paper_id="3", doi="", title="Paper B", source="arxiv")
    p4 = _make_paper(paper_id="4", doi="", title="paper b", source="pubmed")

    result = _deduplicate([p1, p2, p3, p4])

    assert len(result) == 2
    assert result[0].paper_id == "1"
    assert result[1].paper_id == "3"


def test_t10_dedup_empty_input():
    assert _deduplicate([]) == []


# ------------------------------------------------------------------
# T11: Live arXiv connectivity
# ------------------------------------------------------------------

@pytest.mark.live
async def test_t11_live_arxiv_search():
    fetcher = ArxivFetcher()
    papers = await fetcher.search("quantum computing", max_results=1)

    assert len(papers) >= 1
    assert "arxiv.org/pdf/" in papers[0].pdf_url
