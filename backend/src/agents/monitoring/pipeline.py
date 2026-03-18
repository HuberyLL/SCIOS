"""Monitoring pipeline — lightweight 'retrieve then summarise' flow.

Usage::

    from src.agents.monitoring import run_monitoring_scan

    brief = await run_monitoring_scan("large language models", "2026-03-17")
"""

from __future__ import annotations

import asyncio
import logging

from ..llm_client import call_llm
from ..tools import SemanticScholarClient, tavily_search
from ..tools._schemas import PaperResult, WebSearchItem
from .prompts import MONITORING_SYSTEM_PROMPT, MONITORING_USER_TEMPLATE
from .schemas import DailyBrief

logger = logging.getLogger(__name__)


def _format_papers(papers: list[PaperResult]) -> str:
    if not papers:
        return "(no papers found)"
    lines: list[str] = []
    for i, p in enumerate(papers, 1):
        authors = ", ".join(p.authors[:5])
        if len(p.authors) > 5:
            authors += " et al."
        lines.append(
            f"{i}. {p.title}\n"
            f"   Authors: {authors}\n"
            f"   Year: {p.published_date}  |  Citations: {p.citation_count}\n"
            f"   URL: {p.url}\n"
            f"   Abstract: {(p.abstract or 'N/A')[:300]}"
        )
    return "\n\n".join(lines)


def _format_web(items: list[WebSearchItem]) -> str:
    if not items:
        return "(no web results)"
    lines: list[str] = []
    for i, w in enumerate(items, 1):
        lines.append(
            f"{i}. {w.title}\n"
            f"   URL: {w.url}\n"
            f"   Snippet: {w.content[:300]}"
        )
    return "\n\n".join(lines)


def _deduplicate_papers(papers: list[PaperResult]) -> list[PaperResult]:
    seen: set[str] = set()
    unique: list[PaperResult] = []
    for p in papers:
        key = p.title.strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


async def run_monitoring_scan(topic: str, since_date: str) -> DailyBrief:
    """Execute a single monitoring scan for *topic*.

    Steps
    -----
    1. Fan-out: Semantic Scholar search + Tavily web search (concurrent).
    2. Deduplicate paper results by title.
    3. Call LLM to distil evidence into a ``DailyBrief``.

    On total retrieval failure an empty brief is returned.
    """
    year_filter = f"{since_date[:4]}-"

    s2_task = _fetch_s2(topic, year_filter)
    web_task = _fetch_web(topic, since_date)

    s2_papers, web_items = await asyncio.gather(s2_task, web_task)

    papers = _deduplicate_papers(s2_papers)

    if not papers and not web_items:
        logger.warning("No evidence found for topic=%s since=%s", topic, since_date)
        return DailyBrief(topic=topic, since_date=since_date)

    paper_ctx = _format_papers(papers)
    web_ctx = _format_web(web_items)

    messages = [
        {"role": "system", "content": MONITORING_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": MONITORING_USER_TEMPLATE.format(
                topic=topic,
                since_date=since_date,
                paper_context=paper_ctx,
                web_context=web_ctx,
            ),
        },
    ]

    try:
        brief = await call_llm(messages, response_format=DailyBrief)
    except Exception:
        logger.exception("LLM call failed for monitoring topic=%s", topic)
        return DailyBrief(topic=topic, since_date=since_date)

    brief.topic = topic
    brief.since_date = since_date
    return brief


# ------------------------------------------------------------------
# Internal retrieval helpers (graceful degradation)
# ------------------------------------------------------------------


async def _fetch_s2(topic: str, year_filter: str) -> list[PaperResult]:
    try:
        client = SemanticScholarClient()
        result = await client.search_papers(topic, limit=20, year=year_filter)
        return result.papers
    except Exception:
        logger.exception("S2 retrieval failed for topic=%s", topic)
        return []


async def _fetch_web(topic: str, since_date: str) -> list[WebSearchItem]:
    try:
        result = await tavily_search(
            f"{topic} latest research news {since_date}",
            max_results=5,
        )
        return result.results
    except Exception:
        logger.exception("Tavily retrieval failed for topic=%s", topic)
        return []
