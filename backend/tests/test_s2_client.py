"""T4-T7: Tests for s2_client.py — SemanticScholarClient."""

from __future__ import annotations

import httpx
import pytest
import respx

from src.agents.tools._schemas import PaperResult
from src.agents.tools.s2_client import SemanticScholarClient, _paper_from_api


# ------------------------------------------------------------------
# T4: Rate-limit degradation — get_paper returns None after retries
# ------------------------------------------------------------------

async def test_t4_get_paper_returns_none_on_persistent_429():
    client = SemanticScholarClient(api_key="test-key")

    with respx.mock:
        respx.get("https://api.semanticscholar.org/graph/v1/paper/fake-id").mock(
            return_value=httpx.Response(429, text="Rate limited")
        )
        result = await client.get_paper("fake-id")

    assert result is None


# ------------------------------------------------------------------
# T5: Malformed JSON parsing — missing fields use safe defaults
# ------------------------------------------------------------------

def test_t5_paper_from_api_handles_incomplete_json():
    raw = {"paperId": "abc123", "title": "Test Paper"}
    paper = _paper_from_api(raw)

    assert isinstance(paper, PaperResult)
    assert paper.paper_id == "abc123"
    assert paper.title == "Test Paper"
    assert paper.authors == []
    assert paper.doi == ""
    assert paper.pdf_url == ""
    assert paper.published_date == ""
    assert paper.citation_count == 0
    assert paper.source == "semantic_scholar"


def test_t5_paper_from_api_handles_null_fields():
    """Explicit None values in the API response should not crash."""
    raw = {
        "paperId": "x",
        "title": "T",
        "authors": None,
        "abstract": None,
        "externalIds": None,
        "openAccessPdf": None,
        "citationCount": None,
        "year": None,
        "publicationDate": None,
    }
    paper = _paper_from_api(raw)

    assert paper.authors == []
    assert paper.abstract == ""
    assert paper.doi == ""
    assert paper.pdf_url == ""
    assert paper.citation_count == 0


# ------------------------------------------------------------------
# T6: Live search query (requires SEMANTIC_SCHOLAR_API_KEY)
# ------------------------------------------------------------------

@pytest.mark.live
async def test_t6_live_search():
    client = SemanticScholarClient()
    result = await client.search_papers("Transformer models", limit=2)

    assert len(result.papers) >= 1
    for p in result.papers:
        assert p.title
        assert p.paper_id


# ------------------------------------------------------------------
# T7: Live citations & references
# ------------------------------------------------------------------

ATTENTION_PAPER_ID = "204e3073870fae3d05bcbc2f6a8e263d9b72e776"


@pytest.mark.live
async def test_t7_live_citations():
    client = SemanticScholarClient()
    citations = await client.get_paper_citations(ATTENTION_PAPER_ID, limit=3)

    assert len(citations) >= 1
    for c in citations:
        assert isinstance(c, PaperResult)
        assert c.title


@pytest.mark.live
async def test_t7_live_references():
    client = SemanticScholarClient()
    references = await client.get_paper_references(ATTENTION_PAPER_ID, limit=3)

    assert len(references) >= 1
    for r in references:
        assert isinstance(r, PaperResult)
        assert r.title
