"""DOAJ paper source — Directory of Open Access Journals (search API v2)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from .._http import api_retry, managed_client
from .._schemas import PaperResult
from ._base import BasePaperFetcher, get_source_limiter

logger = logging.getLogger(__name__)


class DoajFetcher(BasePaperFetcher):
    source_name = "doaj"
    _BASE_URL = "https://doaj.org/api"

    def __init__(self, api_key: str = "") -> None:
        self._limiter = get_source_limiter(self.source_name)
        self._api_key = api_key

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Accept": "application/json"}
        if self._api_key:
            h["X-API-Key"] = self._api_key
        return h

    @api_retry
    async def _do_search(self, query: str, max_results: int) -> dict:
        await self._limiter.acquire("request")
        encoded = quote(query.strip() or "*", safe="")
        url = f"{self._BASE_URL}/search/articles/{encoded}"
        params = {"page": 1, "pageSize": min(max_results, 100)}
        async with managed_client(headers=self._headers()) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        try:
            data = await self._do_search(query, max_results)
        except Exception as exc:
            logger.warning("DOAJ search failed: %s", exc)
            return []

        if "error" in data:
            logger.warning("DOAJ API error: %s", data["error"])
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
                logger.warning("DOAJ parse error: %s", exc)
        return papers

    async def fetch_full_text(self, paper: PaperResult) -> str:
        return paper.abstract


def _parse_item(item: dict[str, Any]) -> PaperResult | None:
    bibjson = item.get("bibjson", {})
    if not bibjson:
        return None

    title = bibjson.get("title", "")
    if not title:
        return None

    authors: list[str] = []
    for au in bibjson.get("author", []):
        name = au.get("name", "").strip()
        if name:
            authors.append(name)

    abstract = ""
    abs_val = bibjson.get("abstract")
    if isinstance(abs_val, str):
        abstract = abs_val
    elif isinstance(abs_val, dict):
        abstract = abs_val.get("text", "")

    doi = ""
    for ident in bibjson.get("identifier", []):
        if ident.get("type") == "doi" and ident.get("id"):
            doi = ident["id"]
            break

    year = bibjson.get("year", "")
    pub_date = str(year) if year else ""

    journal = bibjson.get("journal", {})
    journal_title = journal.get("title", "") if isinstance(journal, dict) else ""

    pdf_url = ""
    landing_url = ""
    for link in bibjson.get("link", []):
        if isinstance(link, dict):
            href = link.get("url", "")
            if link.get("type") == "fulltext" and href:
                if href.lower().endswith(".pdf"):
                    pdf_url = href
                elif not landing_url:
                    landing_url = href

    if not landing_url:
        if doi:
            landing_url = f"https://doi.org/{doi}"
        else:
            article_id = item.get("id", "")
            if article_id:
                landing_url = f"https://doaj.org/article/{article_id}"

    paper_id = item.get("id", "") or doi or f"doaj_{hash(title) & 0xffffffff:08x}"

    keywords = [kw for kw in bibjson.get("keywords", []) if isinstance(kw, str)]
    categories: list[str] = []
    for sub in bibjson.get("subject", []):
        if isinstance(sub, dict) and sub.get("term"):
            categories.append(sub["term"])
    if journal_title and journal_title not in categories:
        categories.insert(0, journal_title)

    return PaperResult(
        paper_id=paper_id,
        title=title,
        authors=authors,
        abstract=abstract,
        doi=doi,
        published_date=pub_date,
        pdf_url=pdf_url,
        url=landing_url,
        source="doaj",
        categories=categories[:5],
    )
