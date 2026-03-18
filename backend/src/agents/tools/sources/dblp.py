"""dblp paper source — computer science bibliography (XML API)."""

from __future__ import annotations

import logging
from xml.etree import ElementTree as ET

from .._http import api_retry, managed_client
from .._schemas import PaperResult
from ._base import BasePaperFetcher, get_source_limiter

logger = logging.getLogger(__name__)


class DblpFetcher(BasePaperFetcher):
    source_name = "dblp"
    _API_URL = "https://dblp.org/search/publ/api"

    def __init__(self) -> None:
        self._limiter = get_source_limiter(self.source_name)

    @api_retry
    async def _do_search(self, query: str, max_results: int) -> bytes:
        await self._limiter.acquire("request")
        params = {"q": query, "format": "xml", "h": min(max_results, 100)}
        async with managed_client() as client:
            resp = await client.get(self._API_URL, params=params)
            resp.raise_for_status()
            return resp.content

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        try:
            raw = await self._do_search(query, max_results)
        except Exception as exc:
            logger.warning("dblp search failed: %s", exc)
            return []

        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            logger.warning("dblp XML parse error: %s", exc)
            return []

        papers: list[PaperResult] = []
        for hit in root.findall(".//hit"):
            if len(papers) >= max_results:
                break
            try:
                paper = _parse_hit(hit)
                if paper:
                    papers.append(paper)
            except Exception as exc:
                logger.warning("dblp hit parse error: %s", exc)
        return papers

    async def fetch_full_text(self, paper: PaperResult) -> str:
        return paper.abstract


def _elem_text(parent: ET.Element, tag: str) -> str:
    el = parent.find(tag)
    return (el.text or "").strip() if el is not None else ""


def _parse_hit(hit: ET.Element) -> PaperResult | None:
    info = hit.find("info")
    if info is None:
        return None

    title = _elem_text(info, "title")
    if not title:
        return None

    authors = [
        (a.text or "").strip()
        for a in info.findall("authors/author")
        if a.text
    ]

    venue = _elem_text(info, "venue")
    year = _elem_text(info, "year")
    dblp_url = _elem_text(info, "url")

    doi = ""
    for ee in info.findall("ee"):
        ee_text = (ee.text or "").strip()
        if "doi.org" in ee_text:
            doi = ee_text.split("doi.org/")[-1]
            break
        if ee_text.startswith("10."):
            doi = ee_text
            break
    if not doi:
        doi = _elem_text(info, "doi")

    paper_id = dblp_url.split("/")[-1] if dblp_url and "/" in dblp_url else f"dblp_{hash(title) & 0xffffffff:08x}"

    return PaperResult(
        paper_id=paper_id,
        title=title,
        authors=authors,
        abstract="",
        doi=doi,
        published_date=year,
        pdf_url="",
        url=dblp_url or f"https://dblp.org/search?q={title}",
        source="dblp",
        categories=[venue] if venue else [],
    )
