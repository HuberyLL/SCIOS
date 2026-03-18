"""Multi-source paper fetcher with graceful degradation.

Supports arXiv and PubMed.  Each source implements ``BasePaperFetcher``;
the ``PaperSearcher`` facade fans out queries and merges results.
"""

from __future__ import annotations

import asyncio
import io
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Sequence
from xml.etree import ElementTree as ET

import feedparser
import httpx
from pypdf import PdfReader

from ._http import managed_client
from ._schemas import PaperResult, SearchResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class BasePaperFetcher(ABC):
    """Contract that every paper source must satisfy."""

    source_name: str = ""

    @abstractmethod
    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        ...

    @abstractmethod
    async def fetch_full_text(self, paper: PaperResult) -> str:
        """Return extracted full text.  On failure, return the abstract."""
        ...


# ---------------------------------------------------------------------------
# arXiv
# ---------------------------------------------------------------------------

class ArxivFetcher(BasePaperFetcher):
    """Fetch papers from the arXiv Atom feed API."""

    source_name = "arxiv"
    _API_URL = "http://export.arxiv.org/api/query"

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
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
        """Download PDF into memory and extract text; fall back to abstract."""
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
            logger.warning("arXiv PDF extraction failed for %s, using abstract: %s", paper.paper_id, exc)

        return paper.abstract


# ---------------------------------------------------------------------------
# PubMed
# ---------------------------------------------------------------------------

class PubMedFetcher(BasePaperFetcher):
    """Fetch papers from NCBI PubMed E-utilities."""

    source_name = "pubmed"
    _SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    _FETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        try:
            async with managed_client() as client:
                search_resp = await client.get(
                    self._SEARCH_URL,
                    params={"db": "pubmed", "term": query, "retmax": max_results, "retmode": "xml"},
                )
                search_resp.raise_for_status()
                ids = [el.text for el in ET.fromstring(search_resp.text).findall(".//Id") if el.text]
                if not ids:
                    return []

                fetch_resp = await client.get(
                    self._FETCH_URL,
                    params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml"},
                )
                fetch_resp.raise_for_status()
        except Exception as exc:
            logger.error("PubMed search failed: %s", exc)
            return []

        return self._parse_articles(fetch_resp.text)

    async def fetch_full_text(self, paper: PaperResult) -> str:
        """PubMed doesn't offer free PDF access; return the abstract."""
        return paper.abstract

    # -- helpers --

    @staticmethod
    def _parse_articles(xml_text: str) -> list[PaperResult]:
        root = ET.fromstring(xml_text)
        papers: list[PaperResult] = []
        for article in root.findall(".//PubmedArticle"):
            try:
                pmid = _xml_text(article, ".//PMID")
                title = _xml_text(article, ".//ArticleTitle")
                abstract = _xml_text(article, ".//AbstractText")
                pub_year = _xml_text(article, ".//PubDate/Year")
                doi_el = article.find('.//ELocationID[@EIdType="doi"]')
                doi = doi_el.text if doi_el is not None and doi_el.text else ""

                authors: list[str] = []
                for au in article.findall(".//Author"):
                    last = _xml_text(au, "LastName")
                    initials = _xml_text(au, "Initials")
                    if last:
                        authors.append(f"{last} {initials}".strip())

                papers.append(PaperResult(
                    paper_id=pmid,
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    doi=doi,
                    published_date=pub_year,
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                    source="pubmed",
                ))
            except Exception as exc:
                logger.warning("PubMed article parse error: %s", exc)
        return papers


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

class PaperSearcher:
    """Fan-out search across multiple sources, merge and deduplicate."""

    _FETCHERS: dict[str, BasePaperFetcher] = {
        "arxiv": ArxivFetcher(),
        "pubmed": PubMedFetcher(),
    }

    async def search(
        self,
        query: str,
        *,
        sources: Sequence[str] | None = None,
        max_results: int = 10,
    ) -> SearchResult:
        """Search selected (or all) sources concurrently.

        Failures in individual sources are swallowed — partial results are
        better than no results.
        """
        chosen = sources or list(self._FETCHERS.keys())
        tasks = [
            self._safe_search(name, query, max_results)
            for name in chosen
            if name in self._FETCHERS
        ]
        nested = await asyncio.gather(*tasks)
        papers = _deduplicate(p for batch in nested for p in batch)
        return SearchResult(query=query, total=len(papers), papers=papers)

    async def fetch_full_text(self, paper: PaperResult) -> str:
        """Route to the correct fetcher and return full text (or abstract)."""
        fetcher = self._FETCHERS.get(paper.source)
        if fetcher is None:
            logger.warning("No fetcher for source '%s'; returning abstract", paper.source)
            return paper.abstract
        try:
            return await fetcher.fetch_full_text(paper)
        except Exception as exc:
            logger.error("fetch_full_text failed for %s: %s", paper.paper_id, exc)
            return paper.abstract

    # -- internal --

    async def _safe_search(self, name: str, query: str, max_results: int) -> list[PaperResult]:
        try:
            return await self._FETCHERS[name].search(query, max_results=max_results)
        except Exception as exc:
            logger.error("Source '%s' search failed: %s", name, exc)
            return []


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _xml_text(root: Any, xpath: str) -> str:
    el = root.find(xpath)
    return (el.text or "").strip() if el is not None else ""


def _parse_iso(date_str: str) -> str:
    """Best-effort ISO-date extraction; return raw string on failure."""
    if not date_str:
        return ""
    try:
        return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d")
    except ValueError:
        return date_str


def _deduplicate(papers: Any) -> list[PaperResult]:
    """Remove duplicates by DOI (preferred) or title lower-case."""
    seen_doi: set[str] = set()
    seen_title: set[str] = set()
    unique: list[PaperResult] = []
    for p in papers:
        if p.doi:
            if p.doi in seen_doi:
                continue
            seen_doi.add(p.doi)
        key = p.title.lower().strip()
        if key in seen_title:
            continue
        seen_title.add(key)
        unique.append(p)
    return unique
