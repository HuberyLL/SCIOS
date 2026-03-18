"""CORE paper source — global open-access research aggregator (v3 API)."""

from __future__ import annotations

import logging
from typing import Any

from .._http import api_retry, managed_client
from .._schemas import PaperResult
from ._base import BasePaperFetcher, get_source_limiter

logger = logging.getLogger(__name__)


class CoreFetcher(BasePaperFetcher):
    source_name = "core"
    _BASE_URL = "https://api.core.ac.uk/v3"

    def __init__(self, api_key: str = "") -> None:
        self._limiter = get_source_limiter(self.source_name)
        self._api_key = api_key

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Accept": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    @api_retry
    async def _do_search(self, query: str, max_results: int) -> dict:
        await self._limiter.acquire("request")
        params: dict[str, Any] = {"q": query, "limit": min(max_results, 100), "offset": 0}
        async with managed_client(headers=self._headers()) as client:
            resp = await client.get(f"{self._BASE_URL}/search/works", params=params)
            resp.raise_for_status()
            return resp.json()

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        try:
            data = await self._do_search(query, max_results)
        except Exception as exc:
            logger.warning("CORE search failed: %s", exc)
            return []

        papers: list[PaperResult] = []
        for item in data.get("results", []):
            if len(papers) >= max_results:
                break
            try:
                paper = _parse_item(item)
                if paper:
                    papers.append(paper)
            except Exception as exc:
                logger.warning("CORE parse error: %s", exc)
        return papers

    async def fetch_full_text(self, paper: PaperResult) -> str:
        return paper.abstract


def _parse_item(item: dict[str, Any]) -> PaperResult | None:
    core_id = str(item.get("id", ""))
    if not core_id:
        return None
    title = (item.get("title") or "").strip()
    if not title:
        return None

    authors: list[str] = []
    for au in item.get("authors", []):
        if isinstance(au, dict):
            name = au.get("name", "")
            if name:
                authors.append(name)
        elif isinstance(au, str):
            authors.append(au)

    abstract = item.get("abstract", "") or ""
    doi = item.get("doi", "") or ""
    pub_date = item.get("publishedDate", "") or ""
    if "T" in pub_date:
        pub_date = pub_date.split("T")[0]

    url = item.get("url", "")
    if not url and doi:
        url = f"https://doi.org/{doi}"

    pdf_url = ""
    dl = item.get("downloadUrl", "")
    if isinstance(dl, str) and dl.lower().endswith(".pdf"):
        pdf_url = dl

    categories: list[str] = []
    for subj in item.get("subjects", []):
        if isinstance(subj, dict):
            name = subj.get("name", "")
            if name:
                categories.append(name)
        elif isinstance(subj, str):
            categories.append(subj)

    return PaperResult(
        paper_id=core_id,
        title=title,
        authors=authors,
        abstract=abstract,
        doi=doi,
        published_date=pub_date,
        pdf_url=pdf_url,
        url=url,
        source="core",
        categories=categories[:5],
        citation_count=item.get("citationCount", 0) or 0,
    )
