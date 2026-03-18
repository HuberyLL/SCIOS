"""bioRxiv / medRxiv paper sources — shared base + concrete fetchers."""

from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta

from pypdf import PdfReader

from .._http import api_retry, managed_client
from .._schemas import PaperResult
from ._base import BasePaperFetcher, get_source_limiter

logger = logging.getLogger(__name__)

_FETCH_CAP_MULTIPLIER = 5
_FETCH_CAP_MAX = 500


def _matches(paper: PaperResult, keywords: list[str]) -> bool:
    """Return True if *any* keyword appears in the paper's title or abstract."""
    text = (paper.title + " " + paper.abstract).lower()
    return any(kw in text for kw in keywords)


class _BiorxivBaseFetcher(BasePaperFetcher):
    """Shared implementation for bioRxiv and medRxiv (identical API, different path).

    The bioRxiv API only supports date-range browsing, not keyword search.
    We over-fetch from the date window and apply client-side keyword filtering
    on title + abstract to avoid polluting downstream results with irrelevant
    papers.
    """

    _SERVER: str = ""  # "biorxiv" or "medrxiv" — set by subclasses
    _WEB_HOST: str = ""  # "www.biorxiv.org" or "www.medrxiv.org"

    def __init__(self) -> None:
        self._limiter = get_source_limiter(self.source_name)

    @api_retry
    async def _fetch_page(self, url: str) -> dict:
        await self._limiter.acquire(self.source_name)
        async with managed_client() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        keywords = [w.lower() for w in query.split() if w.strip()]
        fetch_cap = min(max_results * _FETCH_CAP_MULTIPLIER, _FETCH_CAP_MAX)

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        base_url = f"https://api.biorxiv.org/details/{self._SERVER}/{start_date}/{end_date}"

        raw_papers: list[PaperResult] = []
        cursor = 0
        while len(raw_papers) < fetch_cap:
            url = f"{base_url}/{cursor}"
            try:
                data = await self._fetch_page(url)
            except Exception as exc:
                logger.warning("%s search failed at cursor %d: %s", self.source_name, cursor, exc)
                break

            collection = data.get("collection", [])
            if not collection:
                break

            for item in collection:
                try:
                    doi = item.get("doi", "")
                    version = item.get("version", "1")
                    authors_raw = item.get("authors", "")
                    authors = [a.strip() for a in authors_raw.split(";") if a.strip()] if authors_raw else []
                    pub_date = item.get("date", "")

                    raw_papers.append(PaperResult(
                        paper_id=doi or f"{self.source_name}_{cursor}",
                        title=item.get("title", ""),
                        authors=authors,
                        abstract=item.get("abstract", ""),
                        doi=doi,
                        published_date=pub_date,
                        pdf_url=f"https://{self._WEB_HOST}/content/{doi}v{version}.full.pdf" if doi else "",
                        url=f"https://{self._WEB_HOST}/content/{doi}v{version}" if doi else "",
                        source=self.source_name,
                        categories=[item.get("category", "")] if item.get("category") else [],
                    ))
                    if len(raw_papers) >= fetch_cap:
                        break
                except Exception as exc:
                    logger.warning("%s entry parse error: %s", self.source_name, exc)

            if len(collection) < 100:
                break
            cursor += 100

        if keywords:
            filtered = [p for p in raw_papers if _matches(p, keywords)]
        else:
            filtered = raw_papers

        return filtered[:max_results]

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
            logger.warning("%s PDF extraction failed for %s: %s", self.source_name, paper.paper_id, exc)
        return paper.abstract


class BioRxivFetcher(_BiorxivBaseFetcher):
    source_name = "biorxiv"
    _SERVER = "biorxiv"
    _WEB_HOST = "www.biorxiv.org"


class MedRxivFetcher(_BiorxivBaseFetcher):
    source_name = "medrxiv"
    _SERVER = "medrxiv"
    _WEB_HOST = "www.medrxiv.org"
