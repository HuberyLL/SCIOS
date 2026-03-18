"""PMC (PubMed Central) paper source — NCBI E-utilities (db=pmc)."""

from __future__ import annotations

import logging
from typing import Any
from xml.etree import ElementTree as ET

from .._http import api_retry, managed_client
from .._schemas import PaperResult
from ._base import BasePaperFetcher, get_source_limiter

logger = logging.getLogger(__name__)


class PMCFetcher(BasePaperFetcher):
    source_name = "pmc"
    _SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    _SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

    def __init__(self) -> None:
        self._limiter = get_source_limiter(self.source_name)

    @api_retry
    async def _search_ids(self, query: str, max_results: int) -> list[str]:
        await self._limiter.acquire("request")
        async with managed_client() as client:
            resp = await client.get(
                self._SEARCH_URL,
                params={
                    "db": "pmc", "term": query, "retmax": max_results,
                    "retmode": "xml", "tool": "scios", "email": "scios@example.org",
                },
            )
            resp.raise_for_status()
            return [el.text for el in ET.fromstring(resp.text).findall(".//Id") if el.text]

    @api_retry
    async def _fetch_summaries(self, ids: list[str]) -> str:
        await self._limiter.acquire("request")
        async with managed_client() as client:
            resp = await client.get(
                self._SUMMARY_URL,
                params={
                    "db": "pmc", "id": ",".join(ids), "retmode": "xml",
                    "tool": "scios", "email": "scios@example.org",
                },
            )
            resp.raise_for_status()
            return resp.text

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        try:
            ids = await self._search_ids(query, max_results)
            if not ids:
                return []
            xml_text = await self._fetch_summaries(ids)
        except Exception as exc:
            logger.warning("PMC search failed: %s", exc)
            return []

        return self._parse_docsums(xml_text, max_results)

    async def fetch_full_text(self, paper: PaperResult) -> str:
        return paper.abstract

    @staticmethod
    def _parse_docsums(xml_text: str, max_results: int) -> list[PaperResult]:
        root = ET.fromstring(xml_text)
        papers: list[PaperResult] = []
        for docsum in root.findall(".//DocSum"):
            try:
                paper = _parse_single_docsum(docsum)
                if paper:
                    papers.append(paper)
                    if len(papers) >= max_results:
                        break
            except Exception as exc:
                logger.warning("PMC docsum parse error: %s", exc)
        return papers


def _item_text(docsum: Any, name: str) -> str:
    item = docsum.find(f"./Item[@Name='{name}']")
    if item is None:
        return ""
    return "".join(item.itertext()).strip()


def _parse_single_docsum(docsum: Any) -> PaperResult | None:
    doc_id = "".join((docsum.findtext("Id") or "").split())
    if not doc_id:
        return None
    title = _item_text(docsum, "Title")
    if not title:
        return None

    authors: list[str] = []
    author_list = docsum.find("./Item[@Name='AuthorList']")
    if author_list is not None:
        for sub in author_list.findall("./Item"):
            val = "".join(sub.itertext()).strip()
            if val:
                authors.append(val)

    pmcid = f"PMC{doc_id}" if not doc_id.upper().startswith("PMC") else doc_id

    doi = _item_text(docsum, "DOI")
    pub_date = _item_text(docsum, "PubDate")
    journal = _item_text(docsum, "FullJournalName") or _item_text(docsum, "Source")

    return PaperResult(
        paper_id=pmcid,
        title=title,
        authors=authors,
        abstract="",
        doi=doi,
        published_date=pub_date,
        pdf_url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/",
        url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/",
        source="pmc",
        categories=[journal] if journal else [],
    )
