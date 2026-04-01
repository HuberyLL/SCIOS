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

ENRICHED_FIELDS = [
    *DEFAULT_FIELDS,
    "authors.authorId",
    "authors.affiliations",
]


def _extract_author_details(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract structured author info (id, name, affiliations) from an S2 paper.

    Returns a list of dicts suitable for constructing ``S2AuthorDetail`` in the
    landscape pipeline.  Works regardless of which ``fields`` were requested —
    missing sub-fields gracefully default to empty values.
    """
    details: list[dict[str, Any]] = []
    for a in raw.get("authors") or []:
        if not isinstance(a, dict) or "name" not in a:
            continue
        details.append({
            "author_id": a.get("authorId") or "",
            "name": a["name"],
            "affiliations": a.get("affiliations") or [],
        })
    return details


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
        if open_access_pdf:
            params["openAccessPdf"] = ""
        if fields_of_study:
            params["fieldsOfStudy"] = ",".join(fields_of_study)

        try:
            data = await self._get("/paper/search", params=params)
        except httpx.HTTPStatusError as exc:
            logger.warning("S2 search unavailable: %s", exc)
            return SearchResult(query=query)
        except Exception as exc:
            logger.warning("S2 search unexpected error: %s", exc)
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

    async def get_papers_batch(
        self,
        paper_ids: list[str],
        *,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch details for multiple papers via ``POST /paper/batch``.

        Returns **raw** S2 JSON dicts (not ``PaperResult``) so callers can
        extract enriched author info via ``_extract_author_details`` before
        converting to ``PaperResult``.  Papers that the API cannot resolve
        are silently omitted.
        """
        if not paper_ids:
            return []
        resolved_fields = fields or ENRICHED_FIELDS
        params = {"fields": ",".join(resolved_fields)}
        url = f"{BASE_URL}/paper/batch"
        try:
            data = await self._post(
                url,
                json_body={"ids": paper_ids},
                params=params,
            )
        except Exception as exc:
            logger.error("S2 batch lookup error: %s", exc)
            return []
        if isinstance(data, list):
            return [item for item in data if item is not None]
        return []
