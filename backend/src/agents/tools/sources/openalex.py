"""OpenAlex paper source — works search API with polite-pool support."""

from __future__ import annotations

import logging
from typing import Any

from .._http import api_retry, managed_client
from .._schemas import PaperResult
from ._base import BasePaperFetcher, get_source_limiter

logger = logging.getLogger(__name__)

_USER_AGENT = "SCIOS/1.0 (mailto:scios-research@example.org)"


class OpenAlexFetcher(BasePaperFetcher):
    source_name = "openalex"
    _BASE_URL = "https://api.openalex.org/works"

    def __init__(self, mailto: str = "") -> None:
        self._limiter = get_source_limiter(self.source_name)
        self._mailto = mailto or "scios-research@example.org"

    @api_retry
    async def _do_search(self, query: str, max_results: int) -> dict:
        await self._limiter.acquire("request")
        params: dict[str, Any] = {
            "search": query,
            "per_page": min(max_results, 200),
            "mailto": self._mailto,
        }
        async with managed_client(headers={"User-Agent": _USER_AGENT}) as client:
            resp = await client.get(self._BASE_URL, params=params)
            resp.raise_for_status()
            return resp.json()

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        try:
            data = await self._do_search(query, max_results)
        except Exception as exc:
            logger.warning("OpenAlex search failed: %s", exc)
            return []

        papers: list[PaperResult] = []
        for item in data.get("results", []):
            if len(papers) >= max_results:
                break
            try:
                paper = self._parse_item(item)
                if paper:
                    papers.append(paper)
            except Exception as exc:
                logger.warning("OpenAlex parse error: %s", exc)
        return papers

    async def fetch_full_text(self, paper: PaperResult) -> str:
        return paper.abstract

    # -- parsing helpers --

    @staticmethod
    def _parse_item(item: dict[str, Any]) -> PaperResult | None:
        paper_id = item.get("id", "").replace("https://openalex.org/", "")
        title = item.get("title")
        if not title:
            return None

        authors = [
            au.get("author", {}).get("display_name", "")
            for au in item.get("authorships", [])
            if au.get("author", {}).get("display_name")
        ]

        abstract = _reconstruct_abstract(item.get("abstract_inverted_index"))

        doi = item.get("doi", "") or ""
        if doi:
            doi = doi.replace("https://doi.org/", "")

        url = ""
        pdf_url = ""
        primary_location = item.get("primary_location")
        if primary_location:
            url = primary_location.get("landing_page_url", "")
            pdf_url = primary_location.get("pdf_url", "") or ""
        if not url:
            url = item.get("id", "")

        oa = item.get("open_access", {})
        if not pdf_url and oa.get("is_oa"):
            pdf_url = oa.get("oa_url", "") or ""

        pub_date = item.get("publication_date", "") or ""

        concepts = [
            c.get("display_name")
            for c in item.get("concepts", [])
            if c.get("display_name")
        ][:5]

        citations = item.get("cited_by_count", 0) or 0

        return PaperResult(
            paper_id=paper_id,
            title=title,
            authors=authors,
            abstract=abstract,
            doi=doi,
            published_date=pub_date,
            pdf_url=pdf_url,
            url=url,
            source="openalex",
            categories=concepts,
            citation_count=citations,
        )


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """Rebuild plain text from OpenAlex inverted-index representation."""
    if not inverted_index:
        return ""
    try:
        word_positions: list[tuple[int, str]] = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort(key=lambda x: x[0])
        return " ".join(w for _, w in word_positions)
    except Exception:
        return ""
