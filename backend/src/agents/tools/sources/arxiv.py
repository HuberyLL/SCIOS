"""arXiv paper source — Atom feed API."""

from __future__ import annotations

import io
import logging
from datetime import datetime

import feedparser
from pypdf import PdfReader

from .._http import managed_client
from .._schemas import PaperResult
from ._base import BasePaperFetcher, get_source_limiter

logger = logging.getLogger(__name__)


class ArxivFetcher(BasePaperFetcher):
    """Fetch papers from the arXiv Atom feed API."""

    source_name = "arxiv"
    _API_URL = "https://export.arxiv.org/api/query"

    def __init__(self) -> None:
        self._limiter = get_source_limiter(self.source_name)

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        await self._limiter.acquire("request")
        params = {
            "search_query": query,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        try:
            async with managed_client() as client:
                resp = await client.get(self._API_URL, params=params)
                resp.raise_for_status()
                raw = resp.text
        except Exception as exc:
            logger.error("arXiv search failed: %s", exc)
            return []

        feed = feedparser.parse(raw)
        papers: list[PaperResult] = []
        for entry in feed.entries:
            try:
                authors = [a.name for a in getattr(entry, "authors", [])]
                pdf_url = next(
                    (lnk.href for lnk in entry.links if getattr(lnk, "type", "") == "application/pdf"),
                    "",
                )
                published = _parse_iso(entry.get("published", ""))
                papers.append(PaperResult(
                    paper_id=entry.id.split("/")[-1],
                    title=entry.title.strip().replace("\n", " "),
                    authors=authors,
                    abstract=(entry.summary or "").strip(),
                    doi=entry.get("doi", ""),
                    published_date=published,
                    pdf_url=pdf_url,
                    url=entry.id,
                    source=self.source_name,
                    categories=[t.term for t in getattr(entry, "tags", [])],
                ))
            except Exception as exc:
                logger.warning("arXiv entry parse error: %s", exc)
        return papers

    async def fetch_full_text(self, paper: PaperResult) -> str:
        if not paper.pdf_url:
            return paper.abstract
        try:
            async with managed_client(timeout=60.0) as client:
                resp = await client.get(paper.pdf_url)
                resp.raise_for_status()
                reader = PdfReader(io.BytesIO(resp.content))
                pages = [page.extract_text() or "" for page in reader.pages]
                text = "\n".join(pages).strip()
                if text:
                    return text
        except Exception as exc:
            logger.warning("arXiv PDF extraction failed for %s: %s", paper.paper_id, exc)
        return paper.abstract


def _parse_iso(date_str: str) -> str:
    if not date_str:
        return ""
    try:
        return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d")
    except ValueError:
        return date_str
