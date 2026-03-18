"""Async client for the Semantic Scholar Academic Graph API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.core.config import get_settings

from ._http import RateLimiter, api_retry, managed_client
from ._schemas import PaperResult, SearchResult

logger = logging.getLogger(__name__)

BASE_URL = "https://api.semanticscholar.org/graph/v1"
RECO_URL = "https://api.semanticscholar.org/recommendations/v1"

_RATE_RULES: dict[str, tuple[int, float]] = {
    "/paper/search": (1, 1.0),
    "/paper/batch": (1, 1.0),
    "/recommendations": (1, 1.0),
    "*": (10, 1.0),
}

DEFAULT_FIELDS = [
    "paperId", "title", "abstract", "year",
    "citationCount", "authors", "url",
    "externalIds", "openAccessPdf",
]


def _paper_from_api(raw: dict[str, Any]) -> PaperResult:
    """Convert a Semantic Scholar API JSON object into a *PaperResult*."""
    authors_raw = raw.get("authors") or []
    author_names = [a["name"] for a in authors_raw if isinstance(a, dict) and "name" in a]

    external_ids = raw.get("externalIds") or {}
    doi = external_ids.get("DOI", "")

    open_pdf = raw.get("openAccessPdf") or {}
    pdf_url = open_pdf.get("url", "") if isinstance(open_pdf, dict) else ""

    return PaperResult(
        paper_id=raw.get("paperId", ""),
        title=raw.get("title", ""),
        authors=author_names,
        abstract=raw.get("abstract") or "",
        doi=doi,
        published_date=raw.get("publicationDate") or str(raw.get("year", "")),
        pdf_url=pdf_url,
        url=raw.get("url", ""),
        source="semantic_scholar",
        categories=[],
        citation_count=raw.get("citationCount", 0) or 0,
    )


class SemanticScholarClient:
    """Thin async wrapper around the Semantic Scholar REST API.

    Features:
    - Per-endpoint rate limiting (search/batch 1 req/s, others 10 req/s).
    - Automatic retry with exponential back-off on 429 / 5xx / timeouts
      via the shared ``api_retry`` decorator.
    - Optional API key authentication; falls back to unauthenticated access.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or get_settings().semantic_scholar_api_key
        self._limiter = RateLimiter(rules=_RATE_RULES)

    def _headers(self) -> dict[str, str]:
        if self._api_key:
            return {"x-api-key": self._api_key}
        logger.debug("No SEMANTIC_SCHOLAR_API_KEY; using unauthenticated access")
        return {}

    # ------------------------------------------------------------------
    # Internal request helpers
    # ------------------------------------------------------------------

    @api_retry
    async def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict:
        await self._limiter.acquire(endpoint)
        async with managed_client(headers=self._headers()) as client:
            url = f"{BASE_URL}{endpoint}"
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    @api_retry
    async def _post(self, url: str, json_body: dict[str, Any], params: dict[str, Any] | None = None) -> dict:
        endpoint = url.replace(BASE_URL, "").replace(RECO_URL, "")
        await self._limiter.acquire(endpoint)
        async with managed_client(headers=self._headers()) as client:
            resp = await client.post(url, json=json_body, params=params)
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search_papers(
        self,
        query: str,
        *,
        limit: int = 10,
        offset: int = 0,
        fields: list[str] | None = None,
        year: str | None = None,
        min_citation_count: int | None = None,
        publication_types: list[str] | None = None,
        open_access_pdf: bool | None = None,
        fields_of_study: list[str] | None = None,
    ) -> SearchResult:
        """Relevance-ranked paper search."""
        params: dict[str, Any] = {
            "query": query,
            "limit": min(limit, 100),
            "offset": offset,
            "fields": ",".join(fields or DEFAULT_FIELDS),
        }
        if year is not None:
            params["year"] = year
        if min_citation_count is not None:
            params["minCitationCount"] = min_citation_count
        if publication_types:
            params["publicationTypes"] = ",".join(publication_types)
        if open_access_pdf is not None:
            params["openAccessPdf"] = ""
        if fields_of_study:
            params["fieldsOfStudy"] = ",".join(fields_of_study)

        try:
            data = await self._get("/paper/search", params=params)
        except httpx.HTTPStatusError as exc:
            logger.error("S2 search failed: %s", exc)
            return SearchResult(query=query)
        except Exception as exc:
            logger.error("S2 search unexpected error: %s", exc)
            return SearchResult(query=query)

        papers = [_paper_from_api(p) for p in (data.get("data") or [])]
        return SearchResult(
            query=query,
            total=data.get("total", len(papers)),
            papers=papers,
        )

    async def get_paper(
        self,
        paper_id: str,
        *,
        fields: list[str] | None = None,
    ) -> PaperResult | None:
        """Fetch details for a single paper by Semantic Scholar ID, DOI, etc."""
        params = {"fields": ",".join(fields or DEFAULT_FIELDS)}
        try:
            data = await self._get(f"/paper/{paper_id}", params=params)
        except httpx.HTTPStatusError:
            logger.warning("S2 paper detail not found: %s", paper_id)
            return None
        except Exception as exc:
            logger.error("S2 get_paper error: %s", exc)
            return None
        return _paper_from_api(data)

    async def get_paper_citations(
        self,
        paper_id: str,
        *,
        fields: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PaperResult]:
        """Return papers that cite *paper_id*."""
        cite_fields = fields or ["title", "abstract", "year", "authors", "citationCount", "url"]
        params: dict[str, Any] = {
            "fields": ",".join(cite_fields),
            "limit": min(limit, 1000),
            "offset": offset,
        }
        try:
            data = await self._get(f"/paper/{paper_id}/citations", params=params)
        except Exception as exc:
            logger.error("S2 citations error: %s", exc)
            return []
        return [
            _paper_from_api(item["citingPaper"])
            for item in (data.get("data") or [])
            if "citingPaper" in item
        ]

    async def get_paper_references(
        self,
        paper_id: str,
        *,
        fields: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PaperResult]:
        """Return papers referenced by *paper_id*."""
        ref_fields = fields or ["title", "abstract", "year", "authors", "citationCount", "url"]
        params: dict[str, Any] = {
            "fields": ",".join(ref_fields),
            "limit": min(limit, 1000),
            "offset": offset,
        }
        try:
            data = await self._get(f"/paper/{paper_id}/references", params=params)
        except Exception as exc:
            logger.error("S2 references error: %s", exc)
            return []
        return [
            _paper_from_api(item["citedPaper"])
            for item in (data.get("data") or [])
            if "citedPaper" in item
        ]

    async def get_recommendations(
        self,
        paper_id: str,
        *,
        limit: int = 10,
        fields: list[str] | None = None,
        pool: str = "recent",
    ) -> list[PaperResult]:
        """Single-paper recommendation (``/recommendations/v1/papers/forpaper``)."""
        params: dict[str, Any] = {
            "fields": ",".join(fields or DEFAULT_FIELDS),
            "limit": min(limit, 500),
            "from": pool,
        }
        url = f"{RECO_URL}/papers/forpaper/{paper_id}"
        try:
            data = await self._post(url, json_body={}, params=params)
        except Exception as exc:
            logger.error("S2 recommendations error: %s", exc)
            return []
        return [_paper_from_api(p) for p in (data.get("recommendedPapers") or [])]
