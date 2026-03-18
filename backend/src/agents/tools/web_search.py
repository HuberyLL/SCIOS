"""Lightweight async web search powered by the Tavily Python SDK."""

from __future__ import annotations

import logging
from typing import Sequence

from tavily import AsyncTavilyClient

from src.core.config import get_settings

from ._schemas import WebSearchItem, WebSearchResult

logger = logging.getLogger(__name__)


async def tavily_search(
    query: str,
    *,
    max_results: int = 5,
    search_depth: str = "basic",
    include_domains: Sequence[str] | None = None,
    exclude_domains: Sequence[str] | None = None,
) -> WebSearchResult:
    """Run a web search via Tavily and return structured results.

    On any failure (missing key, network error, etc.) an empty
    ``WebSearchResult`` is returned so the caller never crashes.
    """
    api_key = get_settings().tavily_api_key
    if not api_key:
        logger.error("TAVILY_API_KEY not set; returning empty results")
        return WebSearchResult(query=query)

    try:
        client = AsyncTavilyClient(api_key=api_key)
        response = await client.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_domains=list(include_domains) if include_domains else None,
            exclude_domains=list(exclude_domains) if exclude_domains else None,
        )
    except Exception as exc:
        logger.error("Tavily search failed: %s", exc)
        return WebSearchResult(query=query)

    items = [
        WebSearchItem(
            title=r.get("title", ""),
            url=r.get("url", ""),
            content=r.get("content", ""),
            score=r.get("score", 0.0),
        )
        for r in (response.get("results") or [])
    ]
    return WebSearchResult(query=query, results=items)
