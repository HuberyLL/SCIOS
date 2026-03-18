"""PubMed paper source — NCBI E-utilities."""

from __future__ import annotations

import logging
from typing import Any
from xml.etree import ElementTree as ET

from .._http import managed_client
from .._schemas import PaperResult
from ._base import BasePaperFetcher, get_source_limiter

logger = logging.getLogger(__name__)


class PubMedFetcher(BasePaperFetcher):
    """Fetch papers from NCBI PubMed E-utilities."""

    source_name = "pubmed"
    _SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    _FETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    def __init__(self) -> None:
        self._limiter = get_source_limiter(self.source_name)

    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        await self._limiter.acquire("request")
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

                await self._limiter.acquire("request")
                fetch_resp = await client.get(
                    self._FETCH_URL,
                    params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml"},
                )
                fetch_resp.raise_for_status()
        except Exception as exc:
            logger.warning("PubMed search failed: %s", exc)
            return []

        return self._parse_articles(fetch_resp.text)

    async def fetch_full_text(self, paper: PaperResult) -> str:
        return paper.abstract

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


def _xml_text(root: Any, xpath: str) -> str:
    el = root.find(xpath)
    return (el.text or "").strip() if el is not None else ""
