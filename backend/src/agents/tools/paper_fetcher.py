"""Multi-source paper search aggregator with graceful degradation.

The ``PaperSearcher`` facade fans out queries to registered sources,
merges results and deduplicates by DOI → canonical URL → normalized title+year.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Sequence
from urllib.parse import urlparse

from ._schemas import PaperResult, SearchResult
from .sources import DEFAULT_SOURCES, SOURCE_REGISTRY
from .sources._base import BasePaperFetcher, extract_year, normalize_title

logger = logging.getLogger(__name__)


class PaperSearcher:
    """Fan-out search across multiple sources, merge and deduplicate."""

    def __init__(self, fetchers: dict[str, BasePaperFetcher] | None = None) -> None:
        self._fetchers = fetchers if fetchers is not None else SOURCE_REGISTRY

    async def search(
        self,
        query: str,
        *,
        sources: Sequence[str] | None = None,
        max_results: int = 10,
    ) -> SearchResult:
        """Search selected (or default) sources concurrently.

        Failures in individual sources are swallowed -- partial results are
        better than no results.
        """
        chosen = sources or DEFAULT_SOURCES
        tasks = [
            self._safe_search(name, query, max_results)
            for name in chosen
            if name in self._fetchers
        ]
        nested = await asyncio.gather(*tasks)
        papers = _deduplicate(p for batch in nested for p in batch)
        return SearchResult(query=query, total=len(papers), papers=papers)

    async def fetch_full_text(self, paper: PaperResult) -> str:
        """Route to the correct fetcher and return full text (or abstract)."""
        fetcher = self._fetchers.get(paper.source)
        if fetcher is None:
            logger.warning("No fetcher for source '%s'; returning abstract", paper.source)
            return paper.abstract
        try:
            return await fetcher.fetch_full_text(paper)
        except Exception as exc:
            logger.error("fetch_full_text failed for %s: %s", paper.paper_id, exc)
            return paper.abstract

    async def _safe_search(self, name: str, query: str, max_results: int) -> list[PaperResult]:
        try:
            return await self._fetchers[name].search(query, max_results=max_results)
        except Exception as exc:
            logger.error("Source '%s' search failed: %s", name, exc)
            return []


# ---------------------------------------------------------------------------
# Three-level deduplication
# ---------------------------------------------------------------------------

_URL_STRIP_RE = re.compile(r"^https?://(www\.)?")


def _canonical_url(url: str) -> str:
    """Normalize URL for dedup: strip scheme, www, trailing slash."""
    if not url:
        return ""
    normed = _URL_STRIP_RE.sub("", url).rstrip("/").lower()
    return normed


def _deduplicate(papers: Any) -> list[PaperResult]:
    """Remove duplicates using a three-level strategy:

    1. DOI exact match
    2. Canonical URL match
    3. Normalized title + publication year
    """
    seen_doi: set[str] = set()
    seen_url: set[str] = set()
    seen_title_year: set[str] = set()
    unique: list[PaperResult] = []

    for p in papers:
        if p.doi:
            doi_key = p.doi.lower().strip()
            if doi_key in seen_doi:
                continue
            seen_doi.add(doi_key)

        if p.url:
            url_key = _canonical_url(p.url)
            if url_key and url_key in seen_url:
                continue
            if url_key:
                seen_url.add(url_key)

        norm_title = normalize_title(p.title)
        year = extract_year(p.published_date)
        title_year_key = f"{norm_title}|{year}" if year else norm_title
        if title_year_key in seen_title_year:
            continue
        seen_title_year.add(title_year_key)

        unique.append(p)
    return unique
