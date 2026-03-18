"""Crossref paper source — works API with polite-pool support."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .._http import api_retry, managed_client
from .._schemas import PaperResult
from ._base import BasePaperFetcher, get_source_limiter

logger = logging.getLogger(__name__)

_USER_AGENT = "SCIOS/1.0 (mailto:scios-research@example.org)"


class CrossrefFetcher(BasePaperFetcher):
    source_name = "crossref"
    _BASE_URL = "https://api.crossref.org"

    def __init__(self, mailto: str = "") -> None:
        self._limiter = get_source_limiter(self.source_name)
        self._mailto = mailto or "scios-research@example.org"

    @api_retry
    async def _do_search(self, query: str, max_results: int) -> dict:
        await self._limiter.acquire("request")
        params: dict[str, Any] = {
            "query": query,
            "rows": min(max_results, 100),
            "sort": "relevance",
            "order": "desc",
            "mailto": self._mailto,
        }
        async with managed_client(headers={"User-Agent": _USER_AGENT}) as client:
            resp = await client.get(f"{self._BASE_URL}/works", params=params)
            resp.raise_for_status()
            return resp.json()

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        try:
            data = await self._do_search(query, max_results)
        except Exception as exc:
            logger.warning("Crossref search failed: %s", exc)
            return []

        papers: list[PaperResult] = []
        for item in data.get("message", {}).get("items", []):
            try:
                paper = self._parse_item(item)
                if paper:
                    papers.append(paper)
            except Exception as exc:
                logger.warning("Crossref parse error: %s", exc)
        return papers[:max_results]

    async def fetch_full_text(self, paper: PaperResult) -> str:
        return paper.abstract

    # -- parsing helpers --

    @staticmethod
    def _parse_item(item: dict[str, Any]) -> PaperResult | None:
        doi = item.get("DOI", "")
        titles = item.get("title", [])
        title = titles[0] if isinstance(titles, list) and titles else str(titles or "")
        if not title:
            return None

        authors: list[str] = []
        for au in item.get("author", []):
            if isinstance(au, dict):
                given = au.get("given", "")
                family = au.get("family", "")
                name = f"{given} {family}".strip()
                if name:
                    authors.append(name)

        abstract = item.get("abstract", "")
        pub_date = _extract_date(item, "published") or _extract_date(item, "issued") or _extract_date(item, "created")

        url = item.get("URL", f"https://doi.org/{doi}" if doi else "")
        pdf_url = _extract_pdf_url(item)

        citations = item.get("is-referenced-by-count")
        if not isinstance(citations, int):
            citations = 0

        container = item.get("container-title", [])
        categories = []
        if isinstance(container, list) and container:
            categories = [container[0]]
        item_type = item.get("type", "")
        if item_type:
            categories.append(item_type)

        return PaperResult(
            paper_id=doi or title[:60],
            title=title,
            authors=authors,
            abstract=abstract,
            doi=doi,
            published_date=pub_date or "",
            pdf_url=pdf_url,
            url=url,
            source="crossref",
            categories=categories,
            citation_count=citations,
        )


def _extract_date(item: dict, field: str) -> str | None:
    date_info = item.get(field, {})
    if not date_info:
        return None
    parts = (date_info.get("date-parts") or [[]])[0]
    if not parts:
        return None
    try:
        year = parts[0] if len(parts) > 0 and parts[0] is not None else 1970
        month = parts[1] if len(parts) > 1 and parts[1] is not None else 1
        day = parts[2] if len(parts) > 2 and parts[2] is not None else 1
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except (TypeError, ValueError, IndexError):
        return None


def _extract_pdf_url(item: dict) -> str:
    resource = item.get("resource", {})
    if resource:
        primary = resource.get("primary", {})
        if primary and (primary.get("URL", "")).endswith(".pdf"):
            return primary["URL"]
    for link in item.get("link", []):
        if isinstance(link, dict) and "pdf" in link.get("content-type", "").lower():
            return link.get("URL", "")
    return ""
