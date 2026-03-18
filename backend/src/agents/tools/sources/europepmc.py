"""Europe PMC paper source — REST search API."""

from __future__ import annotations

import logging
from typing import Any

from .._http import api_retry, managed_client
from .._schemas import PaperResult
from ._base import BasePaperFetcher, get_source_limiter

logger = logging.getLogger(__name__)


class EuropePMCFetcher(BasePaperFetcher):
    source_name = "europepmc"
    _BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"

    def __init__(self) -> None:
        self._limiter = get_source_limiter(self.source_name)

    @api_retry
    async def _do_search(self, query: str, max_results: int) -> dict:
        await self._limiter.acquire("request")
        params: dict[str, Any] = {
            "query": query,
            "pageSize": min(max_results, 100),
            "format": "json",
            "resultType": "core",
        }
        async with managed_client() as client:
            resp = await client.get(f"{self._BASE_URL}/search", params=params)
            resp.raise_for_status()
            return resp.json()

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        try:
            data = await self._do_search(query, max_results)
        except Exception as exc:
            logger.warning("Europe PMC search failed: %s", exc)
            return []

        papers: list[PaperResult] = []
        for item in data.get("resultList", {}).get("result", []):
            if len(papers) >= max_results:
                break
            try:
                paper = _parse_item(item)
                if paper:
                    papers.append(paper)
            except Exception as exc:
                logger.warning("Europe PMC parse error: %s", exc)
        return papers

    async def fetch_full_text(self, paper: PaperResult) -> str:
        return paper.abstract


def _parse_item(item: dict[str, Any]) -> PaperResult | None:
    paper_id = item.get("id", "")
    if not paper_id:
        return None

    id_type = item.get("source", "")
    if id_type == "MED":
        paper_id = f"PMID:{paper_id}"
    elif id_type == "PMC" and not paper_id.startswith("PMC"):
        paper_id = f"PMC{paper_id}"

    title = item.get("title", "").strip()
    if not title:
        return None

    authors: list[str] = []
    author_list = item.get("authorList", {}).get("author", [])
    if isinstance(author_list, list):
        for au in author_list:
            if isinstance(au, dict):
                name = au.get("fullName", "")
                if name:
                    authors.append(name)
            elif isinstance(au, str):
                authors.append(au)

    abstract = item.get("abstractText", "") or ""
    doi = item.get("doi", "") or item.get("doiId", "") or ""

    pub_year = item.get("pubYear", "")
    pub_date = str(pub_year) if pub_year else ""

    landing_url = ""
    pdf_url = ""
    url_list = item.get("fullTextUrlList", {}).get("fullTextUrl", [])
    if isinstance(url_list, list):
        for u in url_list:
            if isinstance(u, dict):
                style = u.get("documentStyle", "")
                href = u.get("url", "")
                if style == "html" and not landing_url:
                    landing_url = href
                elif style == "pdf" and not pdf_url:
                    pdf_url = href

    if not landing_url:
        if doi:
            landing_url = f"https://doi.org/{doi}"
        elif id_type == "MED":
            landing_url = f"https://pubmed.ncbi.nlm.nih.gov/{paper_id.replace('PMID:', '')}/"

    journal = item.get("journalTitle", "")
    citation_count = item.get("citedByCount", 0) or 0

    return PaperResult(
        paper_id=paper_id,
        title=title,
        authors=authors,
        abstract=abstract,
        doi=doi,
        published_date=pub_date,
        pdf_url=pdf_url,
        url=landing_url,
        source="europepmc",
        categories=[journal] if journal else [],
        citation_count=citation_count,
    )
