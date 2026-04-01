"""Incremental monitoring scan for the DRL Landscape.

Analyses papers published since a given date, produces a
``LandscapeIncrement`` delta that the front-end can merge into an
existing ``DynamicResearchLandscape``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from src.models.landscape import (
    CollaborationEdge,
    LandscapeIncrement,
    ScholarNode,
)
from src.models.paper import PaperResult, SearchResult, WebSearchResult

from ..llm_client import call_llm
from ..tools import SemanticScholarClient, tavily_search
from ..tools.s2_client import ENRICHED_FIELDS, _extract_author_details
from .graph_builder import MIN_PAPER_COUNT
from .prompts import INCREMENTAL_SYSTEM_PROMPT, INCREMENTAL_USER_TEMPLATE
from .schemas import EnrichedPaper, IncrementalAnalysis, S2AuthorDetail

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], Awaitable[None]] | None

S2_MAX_PER_KEYWORD = 20
MAX_ABSTRACT_CHARS = 400


async def _notify(on_progress: ProgressCallback, message: str) -> None:
    if on_progress is not None:
        await on_progress(message)


# ---------------------------------------------------------------------------
# Step 1 – search S2 for recent papers (year >= since)
# ---------------------------------------------------------------------------

async def _search_recent_s2(
    keywords: list[str],
    since_year: str,
) -> list[PaperResult]:
    """Search S2 for papers published in ``since_year`` or later."""
    client = SemanticScholarClient()
    tasks = [
        client.search_papers(kw, limit=S2_MAX_PER_KEYWORD, year=f"{since_year}-")
        for kw in keywords
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    seen: set[str] = set()
    papers: list[PaperResult] = []
    for kw, r in zip(keywords, results):
        if isinstance(r, Exception):
            logger.warning("S2 incremental search failed for '%s': %s", kw, r)
            continue
        for p in r.papers:
            key = p.title.strip().lower()
            if key not in seen:
                seen.add(key)
                papers.append(p)
    return papers


# ---------------------------------------------------------------------------
# Step 2 – dedup against existing papers
# ---------------------------------------------------------------------------

def _filter_new_papers(
    candidates: list[PaperResult],
    existing_paper_ids: set[str],
) -> list[PaperResult]:
    """Remove papers already present in the existing landscape."""
    existing_titles = set()
    new: list[PaperResult] = []
    for p in candidates:
        if p.paper_id in existing_paper_ids:
            continue
        title_key = p.title.strip().lower()
        if title_key in existing_titles:
            continue
        existing_titles.add(title_key)
        new.append(p)
    return new


# ---------------------------------------------------------------------------
# Step 3 – enrich authors for new papers
# ---------------------------------------------------------------------------

async def _enrich_authors(
    papers: list[PaperResult],
) -> list[EnrichedPaper]:
    if not papers:
        return []
    client = SemanticScholarClient()
    ids = [p.paper_id for p in papers if p.paper_id]
    if not ids:
        return [EnrichedPaper(paper=p) for p in papers]

    raw_list = await client.get_papers_batch(ids, fields=ENRICHED_FIELDS)
    author_map: dict[str, list[S2AuthorDetail]] = {}
    for raw in raw_list:
        pid = raw.get("paperId", "")
        if not pid:
            continue
        details = _extract_author_details(raw)
        author_map[pid] = [S2AuthorDetail(**d) for d in details]

    return [
        EnrichedPaper(paper=p, author_details=author_map.get(p.paper_id, []))
        for p in papers
    ]


# ---------------------------------------------------------------------------
# Step 4 – build new co-authorship edges from new papers
# ---------------------------------------------------------------------------

def _build_new_collab(
    enriched_papers: list[EnrichedPaper],
) -> tuple[list[ScholarNode], list[CollaborationEdge]]:
    """Build scholar nodes and co-authorship edges from newly found papers."""
    from collections import defaultdict
    from itertools import combinations

    scholar_map: dict[str, dict] = {}
    edge_counter: dict[tuple[str, str], dict] = {}

    for ep in enriched_papers:
        paper = ep.paper
        authors_with_id = [a for a in ep.author_details if a.author_id]

        for author in authors_with_id:
            aid = author.author_id
            if aid not in scholar_map:
                scholar_map[aid] = {
                    "name": author.name,
                    "affiliations": set(author.affiliations),
                    "paper_count": 0,
                    "citation_count": 0,
                    "top_papers": [],
                }
            entry = scholar_map[aid]
            entry["paper_count"] += 1
            entry["citation_count"] += paper.citation_count
            entry["affiliations"].update(author.affiliations)
            entry["top_papers"].append((paper.paper_id, paper.citation_count))

        aid_list = [a.author_id for a in authors_with_id]
        for a_id, b_id in combinations(sorted(aid_list), 2):
            key = (a_id, b_id)
            if key not in edge_counter:
                edge_counter[key] = {"weight": 0, "shared_paper_ids": []}
            edge_counter[key]["weight"] += 1
            edge_counter[key]["shared_paper_ids"].append(paper.paper_id)

    nodes: list[ScholarNode] = []
    retained_ids: set[str] = set()
    for aid, info in scholar_map.items():
        retained_ids.add(aid)
        top_papers = sorted(info["top_papers"], key=lambda t: t[1], reverse=True)
        nodes.append(
            ScholarNode(
                scholar_id=aid,
                name=info["name"],
                affiliations=sorted(info["affiliations"]),
                paper_count=info["paper_count"],
                citation_count=info["citation_count"],
                top_paper_ids=[pid for pid, _ in top_papers[:5]],
                is_new=True,
            )
        )

    edges: list[CollaborationEdge] = []
    for (src, tgt), info in edge_counter.items():
        if src not in retained_ids or tgt not in retained_ids:
            continue
        edges.append(
            CollaborationEdge(
                source=src,
                target=tgt,
                weight=info["weight"],
                shared_paper_ids=info["shared_paper_ids"],
            )
        )

    return nodes, edges


# ---------------------------------------------------------------------------
# Step 5 – mini LLM call for incremental analysis
# ---------------------------------------------------------------------------

def _format_new_papers_context(papers: list[PaperResult]) -> str:
    lines: list[str] = []
    for i, p in enumerate(papers, 1):
        abstract = p.abstract[:MAX_ABSTRACT_CHARS].rstrip()
        if len(p.abstract) > MAX_ABSTRACT_CHARS:
            abstract += "…"
        lines.append(
            f"[P{i}] paper_id={p.paper_id}\n"
            f"     Title: {p.title}\n"
            f"     Authors: {', '.join(p.authors[:5])}\n"
            f"     Year: {p.published_date}  |  Citations: {p.citation_count}\n"
            f"     Abstract: {abstract}"
        )
    return "\n\n".join(lines) if lines else "(No new papers found.)"


async def _run_incremental_llm(
    topic: str,
    new_papers: list[PaperResult],
    existing_node_ids: list[str],
) -> IncrementalAnalysis:
    """Call the LLM to produce incremental tech nodes, comparisons, gaps."""
    context = _format_new_papers_context(new_papers)
    node_ids_str = "\n".join(existing_node_ids) if existing_node_ids else "(none)"

    messages = [
        {"role": "system", "content": INCREMENTAL_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": INCREMENTAL_USER_TEMPLATE.format(
                topic=topic,
                existing_node_ids=node_ids_str,
                new_papers_context=context,
            ),
        },
    ]
    return await call_llm(messages, response_format=IncrementalAnalysis)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_incremental_scan(
    topic: str,
    since_date: str,
    existing_paper_ids: set[str],
    existing_node_ids: list[str] | None = None,
    keywords: list[str] | None = None,
    on_progress: ProgressCallback = None,
) -> LandscapeIncrement:
    """Run an incremental monitoring scan for *topic*.

    Parameters
    ----------
    topic
        The research topic.
    since_date
        Year (e.g. "2024") to limit the S2 search window.
    existing_paper_ids
        Set of paper_ids already in the landscape for dedup.
    existing_node_ids
        Node IDs from the existing TechTree so the LLM can connect new
        nodes to them.
    keywords
        Override search keywords (if ``None``, derives from topic).
    on_progress
        Optional SSE-style progress callback.
    """
    t_total = time.perf_counter()

    # Derive keywords if not provided
    if keywords is None:
        keywords = [topic]

    # Step 1: Search for recent papers
    await _notify(on_progress, "[1/4] Searching for new papers …")
    candidates = await _search_recent_s2(keywords, since_date)
    logger.info("Incremental scan found %d candidate papers", len(candidates))

    # Step 2: Filter out already-known papers
    await _notify(on_progress, "[2/4] Deduplicating against existing landscape …")
    new_papers = _filter_new_papers(candidates, existing_paper_ids)
    logger.info("After dedup: %d new papers", len(new_papers))

    if not new_papers:
        logger.info("No new papers found — returning empty increment")
        return LandscapeIncrement(detected_at=datetime.now(timezone.utc))

    # Step 3 + 4: Enrich authors + Mini LLM (concurrent)
    await _notify(
        on_progress,
        f"[3/4] Enriching {len(new_papers)} new papers & analyzing …",
    )
    enriched_papers, analysis = await asyncio.gather(
        _enrich_authors(new_papers),
        _run_incremental_llm(topic, new_papers, existing_node_ids or []),
    )

    # Build new collaboration graph from new papers
    new_scholars, new_collab_edges = _build_new_collab(enriched_papers)

    # Mark all new tech nodes as is_new
    for node in analysis.new_tech_nodes:
        node.is_new = True

    # Step 5: Pack into LandscapeIncrement
    await _notify(on_progress, "[4/4] Packaging increment …")
    increment = LandscapeIncrement(
        new_papers=new_papers,
        new_tech_nodes=analysis.new_tech_nodes,
        new_tech_edges=analysis.new_tech_edges,
        new_scholars=new_scholars,
        new_collab_edges=new_collab_edges,
        new_comparisons=analysis.new_comparisons,
        new_gaps=analysis.new_gaps,
        detected_at=datetime.now(timezone.utc),
    )

    logger.info(
        "Incremental scan complete  total=%.1fs  new_papers=%d  "
        "new_tech_nodes=%d  new_scholars=%d  new_comparisons=%d  new_gaps=%d",
        time.perf_counter() - t_total,
        len(increment.new_papers),
        len(increment.new_tech_nodes),
        len(increment.new_scholars),
        len(increment.new_comparisons),
        len(increment.new_gaps),
    )
    return increment
