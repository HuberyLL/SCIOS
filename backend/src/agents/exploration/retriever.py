"""Retriever stage: fan-out tool calls to gather raw academic data.

No LLM is involved here — just concurrent I/O via asyncio.gather with
graceful degradation (empty results never crash the pipeline).
"""

from __future__ import annotations

import asyncio
import logging

from ..tools import PaperSearcher, SemanticScholarClient, tavily_search
from ..tools._schemas import PaperResult, SearchResult, WebSearchResult
from ..tools.sources import DEFAULT_SOURCES
from .schemas import RawRetrievedData, SearchPlan

logger = logging.getLogger(__name__)

S2_MAX_PER_KEYWORD = 10
PAPER_MAX_PER_KEYWORD = 10
TOP_N_FOR_CITATIONS = 3
CITATION_LIMIT = 20


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _search_s2(keywords: list[str]) -> list[SearchResult]:
    """Search Semantic Scholar for each keyword concurrently."""
    client = SemanticScholarClient()
    tasks = [
        client.search_papers(kw, limit=S2_MAX_PER_KEYWORD)
        for kw in keywords
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: list[SearchResult] = []
    for kw, r in zip(keywords, results):
        if isinstance(r, Exception):
            logger.warning("S2 search failed for '%s': %s", kw, r)
            out.append(SearchResult(query=kw))
        else:
            out.append(r)
    return out


async def _search_papers(keywords: list[str]) -> list[SearchResult]:
    """Search multi-source papers for each keyword concurrently."""
    searcher = PaperSearcher()
    tasks = [
        searcher.search(kw, sources=DEFAULT_SOURCES, max_results=PAPER_MAX_PER_KEYWORD)
        for kw in keywords
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: list[SearchResult] = []
    for kw, r in zip(keywords, results):
        if isinstance(r, Exception):
            logger.warning("Multi-source paper search failed for '%s': %s", kw, r)
            out.append(SearchResult(query=kw))
        else:
            out.append(r)
    return out


async def _search_web(queries: list[str]) -> list[WebSearchResult]:
    """Run Tavily web search for each query concurrently."""
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


def _pick_top_cited(results: list[SearchResult], n: int) -> list[PaperResult]:
    """Select the *n* most-cited papers across all search results."""
    all_papers: list[PaperResult] = []
    for sr in results:
        all_papers.extend(sr.papers)

    seen: set[str] = set()
    unique: list[PaperResult] = []
    for p in all_papers:
        if p.paper_id in seen or not p.paper_id:
            continue
        seen.add(p.paper_id)
        unique.append(p)

    unique.sort(key=lambda p: p.citation_count, reverse=True)
    return unique[:n]


async def _fetch_citations(
    s2_results: list[SearchResult],
) -> dict[str, list[PaperResult]]:
    """For top-cited S2 papers, fetch their citing papers."""
    top_papers = _pick_top_cited(s2_results, TOP_N_FOR_CITATIONS)
    if not top_papers:
        return {}

    client = SemanticScholarClient()
    tasks = [
        client.get_paper_citations(p.paper_id, limit=CITATION_LIMIT)
        for p in top_papers
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    citation_map: dict[str, list[PaperResult]] = {}
    for paper, res in zip(top_papers, results):
        if isinstance(res, Exception):
            logger.warning("Citation fetch failed for %s: %s", paper.paper_id, res)
            citation_map[paper.paper_id] = []
        else:
            citation_map[paper.paper_id] = res
    return citation_map


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_all_context(plan: SearchPlan) -> RawRetrievedData:
    """Execute the *SearchPlan* and return aggregated raw data.

    All external calls are concurrent; individual failures are logged and
    replaced with empty results so the pipeline always continues.
    """
    s2_results, paper_results, web_results = await asyncio.gather(
        _search_s2(plan.paper_keywords),
        _search_papers(plan.paper_keywords),
        _search_web(plan.web_queries),
    )

    citation_map = await _fetch_citations(s2_results)

    total_papers = sum(len(sr.papers) for sr in (*s2_results, *paper_results))
    total_web = sum(len(wr.results) for wr in web_results)
    logger.info(
        "Retriever  papers=%d  web_snippets=%d  citation_chains=%d",
        total_papers,
        total_web,
        len(citation_map),
    )

    return RawRetrievedData(
        s2_results=s2_results,
        paper_results=paper_results,
        web_results=web_results,
        citation_map=citation_map,
    )
