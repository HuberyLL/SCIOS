"""Enriched Retriever for the DRL Landscape pipeline.

Data sources: **Semantic Scholar only** for academic papers, **Tavily** for
web supplementation.  No multi-source PaperSearcher — S2 provides all the
structured metadata (authors, citations, references) needed for graph
construction.
"""

from __future__ import annotations

import asyncio
import logging

from src.models.paper import PaperResult, SearchResult, WebSearchResult

from ..exploration.schemas import SearchPlan
from ..tools import SemanticScholarClient, tavily_search
from ..tools.s2_client import ENRICHED_FIELDS, _extract_author_details
from .schemas import EnrichedPaper, EnrichedRetrievedData, S2AuthorDetail

logger = logging.getLogger(__name__)

S2_MAX_PER_KEYWORD = 20
ENRICH_TOP_N = 20
REFERENCE_TOP_N = 5
CITATION_LIMIT = 20
REFERENCE_LIMIT = 30


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _search_s2(keywords: list[str]) -> list[SearchResult]:
    client = SemanticScholarClient()
    tasks = [client.search_papers(kw, limit=S2_MAX_PER_KEYWORD) for kw in keywords]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: list[SearchResult] = []
    for kw, r in zip(keywords, results):
        if isinstance(r, Exception):
            logger.warning("S2 search failed for '%s': %s", kw, r)
            out.append(SearchResult(query=kw))
        else:
            out.append(r)
    return out


async def _search_web(queries: list[str]) -> list[WebSearchResult]:
    tasks = [tavily_search(q) for q in queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: list[WebSearchResult] = []
    for q, r in zip(queries, results):
        if isinstance(r, Exception):
            logger.warning("Web search failed for '%s': %s", q, r)
            out.append(WebSearchResult(query=q))
        else:
            out.append(r)
    return out


def _dedup_papers(results: list[SearchResult]) -> list[PaperResult]:
    """Deduplicate papers across all search results by title."""
    seen: set[str] = set()
    unique: list[PaperResult] = []
    for sr in results:
        for p in sr.papers:
            key = p.title.strip().lower()
            if key not in seen:
                seen.add(key)
                unique.append(p)
    return unique


def _pick_top_cited(papers: list[PaperResult], n: int) -> list[PaperResult]:
    """Select the *n* most-cited papers (must have a paper_id)."""
    with_id = [p for p in papers if p.paper_id]
    with_id.sort(key=lambda p: p.citation_count, reverse=True)
    return with_id[:n]


async def _enrich_authors(
    papers: list[PaperResult],
) -> dict[str, list[S2AuthorDetail]]:
    """Fetch enriched author details for a batch of papers via S2 batch API.

    Returns a mapping ``paper_id -> [S2AuthorDetail, ...]``.
    """
    if not papers:
        return {}
    client = SemanticScholarClient()
    ids = [p.paper_id for p in papers if p.paper_id]
    if not ids:
        return {}

    raw_list = await client.get_papers_batch(ids, fields=ENRICHED_FIELDS)

    result: dict[str, list[S2AuthorDetail]] = {}
    for raw in raw_list:
        pid = raw.get("paperId", "")
        if not pid:
            continue
        details = _extract_author_details(raw)
        result[pid] = [S2AuthorDetail(**d) for d in details]
    return result


async def _fetch_references(
    papers: list[PaperResult],
) -> dict[str, list[PaperResult]]:
    """Fetch reference lists for a set of papers."""
    if not papers:
        return {}
    client = SemanticScholarClient()
    tasks = [
        client.get_paper_references(p.paper_id, limit=REFERENCE_LIMIT)
        for p in papers
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    ref_map: dict[str, list[PaperResult]] = {}
    for paper, res in zip(papers, results):
        if isinstance(res, Exception):
            logger.warning("Reference fetch failed for %s: %s", paper.paper_id, res)
            ref_map[paper.paper_id] = []
        else:
            ref_map[paper.paper_id] = res
    return ref_map


async def _fetch_citations(
    papers: list[PaperResult],
) -> dict[str, list[PaperResult]]:
    """Fetch citation lists for a set of papers."""
    if not papers:
        return {}
    client = SemanticScholarClient()
    tasks = [
        client.get_paper_citations(p.paper_id, limit=CITATION_LIMIT)
        for p in papers
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    cite_map: dict[str, list[PaperResult]] = {}
    for paper, res in zip(papers, results):
        if isinstance(res, Exception):
            logger.warning("Citation fetch failed for %s: %s", paper.paper_id, res)
            cite_map[paper.paper_id] = []
        else:
            cite_map[paper.paper_id] = res
    return cite_map


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_enriched_context(
    plan: SearchPlan,
    *,
    enrich_top_n: int = ENRICH_TOP_N,
    reference_top_n: int = REFERENCE_TOP_N,
) -> EnrichedRetrievedData:
    """Execute the search plan and return enriched data for the landscape.

    Data sources: Semantic Scholar (academic) + Tavily (web).

    Steps:
    1. Fan-out S2 paper search + Tavily web search in parallel.
    2. Deduplicate and pick top-cited papers.
    3. Enrich top-N papers with author details (``get_papers_batch``).
    4. Fetch references for top-cited papers (for TechTree signals).
    5. Fetch citations for top-cited papers.
    """
    s2_results, web_results = await asyncio.gather(
        _search_s2(plan.paper_keywords),
        _search_web(plan.web_queries),
    )

    all_papers = _dedup_papers(s2_results)
    top_for_enrich = _pick_top_cited(all_papers, enrich_top_n)
    top_for_refs = _pick_top_cited(all_papers, reference_top_n)

    author_map, reference_map, citation_map = await asyncio.gather(
        _enrich_authors(top_for_enrich),
        _fetch_references(top_for_refs),
        _fetch_citations(top_for_refs),
    )

    enriched_papers: list[EnrichedPaper] = []
    for paper in all_papers:
        enriched_papers.append(
            EnrichedPaper(
                paper=paper,
                author_details=author_map.get(paper.paper_id, []),
            )
        )

    total_papers = len(enriched_papers)
    total_web = sum(len(wr.results) for wr in web_results)
    enriched_count = sum(1 for ep in enriched_papers if ep.author_details)
    logger.info(
        "EnrichedRetriever  papers=%d  enriched=%d  web_snippets=%d  "
        "reference_chains=%d  citation_chains=%d",
        total_papers, enriched_count, total_web,
        len(reference_map), len(citation_map),
    )

    return EnrichedRetrievedData(
        enriched_papers=enriched_papers,
        web_results=web_results,
        citation_map=citation_map,
        reference_map=reference_map,
    )
