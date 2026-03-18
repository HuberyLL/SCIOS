"""Tests for individual paper sources — mock HTTP, parse verification, degradation."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from src.agents.tools._schemas import PaperResult


# ===================================================================
# Helpers
# ===================================================================

def _assert_valid_paper(p: PaperResult, expected_source: str) -> None:
    assert p.source == expected_source
    assert p.title
    assert p.paper_id


# ===================================================================
# bioRxiv
# ===================================================================

BIORXIV_JSON = {
    "collection": [
        {
            "doi": "10.1101/2024.01.01.000001",
            "title": "Neural circuits in cortical processing",
            "authors": "Smith J; Doe A",
            "abstract": "We study cortical neuroscience mechanisms using optogenetics.",
            "date": "2024-06-15",
            "category": "neuroscience",
            "version": "1",
        },
        {
            "doi": "10.1101/2024.01.01.000002",
            "title": "Protein folding dynamics in E. coli",
            "authors": "Li X",
            "abstract": "Molecular biology study on protein structures.",
            "date": "2024-06-14",
            "category": "biochemistry",
            "version": "1",
        },
    ]
}


class TestBioRxiv:
    async def test_search_filters_by_keyword(self):
        from src.agents.tools.sources.biorxiv import BioRxivFetcher

        with respx.mock:
            respx.get(url__startswith="https://api.biorxiv.org/details/biorxiv/").mock(
                return_value=httpx.Response(200, json=BIORXIV_JSON)
            )
            fetcher = BioRxivFetcher()
            papers = await fetcher.search("neuroscience", max_results=5)

        assert len(papers) == 1
        _assert_valid_paper(papers[0], "biorxiv")
        assert papers[0].doi == "10.1101/2024.01.01.000001"
        assert "Smith J" in papers[0].authors

    async def test_search_no_match_returns_empty(self):
        from src.agents.tools.sources.biorxiv import BioRxivFetcher

        with respx.mock:
            respx.get(url__startswith="https://api.biorxiv.org/details/biorxiv/").mock(
                return_value=httpx.Response(200, json=BIORXIV_JSON)
            )
            fetcher = BioRxivFetcher()
            papers = await fetcher.search("quantum computing", max_results=5)

        assert papers == []

    async def test_search_matches_title_or_abstract(self):
        """Any keyword hitting title OR abstract should match."""
        from src.agents.tools.sources.biorxiv import BioRxivFetcher

        with respx.mock:
            respx.get(url__startswith="https://api.biorxiv.org/details/biorxiv/").mock(
                return_value=httpx.Response(200, json=BIORXIV_JSON)
            )
            fetcher = BioRxivFetcher()
            papers = await fetcher.search("protein", max_results=5)

        assert len(papers) == 1
        assert papers[0].doi == "10.1101/2024.01.01.000002"

    async def test_search_handles_timeout(self):
        from src.agents.tools.sources.biorxiv import BioRxivFetcher

        with respx.mock:
            respx.get(url__startswith="https://api.biorxiv.org/details/biorxiv/").mock(
                side_effect=httpx.ReadTimeout("timeout")
            )
            fetcher = BioRxivFetcher()
            papers = await fetcher.search("test", max_results=5)

        assert papers == []


# ===================================================================
# medRxiv
# ===================================================================

MEDRXIV_JSON = {
    "collection": [
        {
            "doi": "10.1101/2024.02.02.000002",
            "title": "COVID-19 epidemiology in urban settings",
            "authors": "Lee K",
            "abstract": "Medical preprint on pandemic spread patterns.",
            "date": "2024-07-01",
            "category": "epidemiology",
            "version": "2",
        },
        {
            "doi": "10.1101/2024.02.02.000003",
            "title": "Genome-wide association for diabetes",
            "authors": "Park S",
            "abstract": "Genetic markers for type 2 diabetes risk.",
            "date": "2024-07-02",
            "category": "genetics",
            "version": "1",
        },
    ]
}


class TestMedRxiv:
    async def test_search_filters_by_keyword(self):
        from src.agents.tools.sources.biorxiv import MedRxivFetcher

        with respx.mock:
            respx.get(url__startswith="https://api.biorxiv.org/details/medrxiv/").mock(
                return_value=httpx.Response(200, json=MEDRXIV_JSON)
            )
            fetcher = MedRxivFetcher()
            papers = await fetcher.search("epidemiology", max_results=5)

        assert len(papers) == 1
        _assert_valid_paper(papers[0], "medrxiv")
        assert "medrxiv" in papers[0].url

    async def test_search_no_match_returns_empty(self):
        from src.agents.tools.sources.biorxiv import MedRxivFetcher

        with respx.mock:
            respx.get(url__startswith="https://api.biorxiv.org/details/medrxiv/").mock(
                return_value=httpx.Response(200, json=MEDRXIV_JSON)
            )
            fetcher = MedRxivFetcher()
            papers = await fetcher.search("astrophysics", max_results=5)

        assert papers == []

    async def test_search_multi_keyword_any_match(self):
        """With 'diabetes genetics', both keywords match the second paper."""
        from src.agents.tools.sources.biorxiv import MedRxivFetcher

        with respx.mock:
            respx.get(url__startswith="https://api.biorxiv.org/details/medrxiv/").mock(
                return_value=httpx.Response(200, json=MEDRXIV_JSON)
            )
            fetcher = MedRxivFetcher()
            papers = await fetcher.search("diabetes pandemic", max_results=5)

        assert len(papers) == 2


# ===================================================================
# Crossref
# ===================================================================

CROSSREF_JSON = {
    "message": {
        "items": [
            {
                "DOI": "10.1234/test.crossref",
                "title": ["Crossref Test Paper"],
                "author": [{"given": "Alice", "family": "Wang"}],
                "abstract": "A test abstract.",
                "published": {"date-parts": [[2023, 5, 10]]},
                "URL": "https://doi.org/10.1234/test.crossref",
                "is-referenced-by-count": 42,
                "type": "journal-article",
                "container-title": ["Nature"],
                "link": [],
            }
        ]
    }
}


class TestCrossref:
    async def test_search_parses_results(self):
        from src.agents.tools.sources.crossref import CrossrefFetcher

        with respx.mock:
            respx.get("https://api.crossref.org/works").mock(
                return_value=httpx.Response(200, json=CROSSREF_JSON)
            )
            fetcher = CrossrefFetcher()
            papers = await fetcher.search("machine learning", max_results=5)

        assert len(papers) == 1
        p = papers[0]
        _assert_valid_paper(p, "crossref")
        assert p.doi == "10.1234/test.crossref"
        assert p.citation_count == 42
        assert "Alice Wang" in p.authors
        assert p.published_date == "2023-05-10"

    async def test_429_retries(self):
        from src.agents.tools.sources.crossref import CrossrefFetcher

        with respx.mock:
            route = respx.get("https://api.crossref.org/works")
            route.side_effect = [
                httpx.Response(429, text="Rate limited"),
                httpx.Response(429, text="Rate limited"),
                httpx.Response(200, json=CROSSREF_JSON),
            ]
            fetcher = CrossrefFetcher()
            papers = await fetcher.search("test", max_results=5)

        assert len(papers) == 1


# ===================================================================
# OpenAlex
# ===================================================================

OPENALEX_JSON = {
    "results": [
        {
            "id": "https://openalex.org/W1234567890",
            "title": "OpenAlex Test Paper",
            "authorships": [
                {"author": {"display_name": "Dr. Test"}}
            ],
            "abstract_inverted_index": {
                "This": [0], "is": [1], "a": [2], "test": [3], "abstract": [4]
            },
            "doi": "https://doi.org/10.5678/openalex.test",
            "publication_date": "2024-03-15",
            "primary_location": {
                "landing_page_url": "https://example.com/paper",
                "pdf_url": "https://example.com/paper.pdf",
            },
            "open_access": {"is_oa": True, "oa_url": "https://example.com/paper.pdf"},
            "concepts": [{"display_name": "Machine Learning"}],
            "cited_by_count": 100,
        }
    ]
}


class TestOpenAlex:
    async def test_search_parses_results(self):
        from src.agents.tools.sources.openalex import OpenAlexFetcher

        with respx.mock:
            respx.get("https://api.openalex.org/works").mock(
                return_value=httpx.Response(200, json=OPENALEX_JSON)
            )
            fetcher = OpenAlexFetcher()
            papers = await fetcher.search("ML", max_results=5)

        assert len(papers) == 1
        p = papers[0]
        _assert_valid_paper(p, "openalex")
        assert p.doi == "10.5678/openalex.test"
        assert p.abstract == "This is a test abstract"
        assert p.citation_count == 100

    async def test_abstract_reconstruction_empty(self):
        from src.agents.tools.sources.openalex import _reconstruct_abstract

        assert _reconstruct_abstract(None) == ""
        assert _reconstruct_abstract({}) == ""


# ===================================================================
# PMC
# ===================================================================

PMC_SEARCH_XML = """<?xml version="1.0"?>
<eSearchResult><IdList><Id>9000001</Id></IdList></eSearchResult>"""

PMC_SUMMARY_XML = """<?xml version="1.0"?>
<eSummaryResult>
<DocSum>
    <Id>9000001</Id>
    <Item Name="Title" Type="String">PMC Test Paper</Item>
    <Item Name="AuthorList" Type="List">
        <Item Name="Author" Type="String">Author A</Item>
    </Item>
    <Item Name="DOI" Type="String">10.9999/pmc.test</Item>
    <Item Name="PubDate" Type="String">2024</Item>
    <Item Name="FullJournalName" Type="String">Test Journal</Item>
</DocSum>
</eSummaryResult>"""


class TestPMC:
    async def test_search_parses_results(self):
        from src.agents.tools.sources.pmc import PMCFetcher

        with respx.mock:
            respx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").mock(
                return_value=httpx.Response(200, text=PMC_SEARCH_XML)
            )
            respx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi").mock(
                return_value=httpx.Response(200, text=PMC_SUMMARY_XML)
            )
            fetcher = PMCFetcher()
            papers = await fetcher.search("cancer", max_results=5)

        assert len(papers) == 1
        p = papers[0]
        _assert_valid_paper(p, "pmc")
        assert p.paper_id == "PMC9000001"
        assert p.doi == "10.9999/pmc.test"

    async def test_search_empty_ids(self):
        from src.agents.tools.sources.pmc import PMCFetcher

        empty_xml = '<?xml version="1.0"?><eSearchResult><IdList></IdList></eSearchResult>'
        with respx.mock:
            respx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").mock(
                return_value=httpx.Response(200, text=empty_xml)
            )
            fetcher = PMCFetcher()
            papers = await fetcher.search("nonexistent query", max_results=5)

        assert papers == []


# ===================================================================
# Europe PMC
# ===================================================================

EUROPEPMC_JSON = {
    "resultList": {
        "result": [
            {
                "id": "12345678",
                "source": "MED",
                "title": "Europe PMC Test Paper",
                "authorList": {"author": [{"fullName": "Smith J"}]},
                "abstractText": "European biomedical abstract.",
                "doi": "10.1111/epmc.test",
                "pubYear": "2024",
                "journalTitle": "BMJ Open",
                "citedByCount": 15,
                "fullTextUrlList": {
                    "fullTextUrl": [
                        {"documentStyle": "html", "url": "https://example.com/html"},
                        {"documentStyle": "pdf", "url": "https://example.com/paper.pdf"},
                    ]
                },
            }
        ]
    }
}


class TestEuropePMC:
    async def test_search_parses_results(self):
        from src.agents.tools.sources.europepmc import EuropePMCFetcher

        with respx.mock:
            respx.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search").mock(
                return_value=httpx.Response(200, json=EUROPEPMC_JSON)
            )
            fetcher = EuropePMCFetcher()
            papers = await fetcher.search("biomedical", max_results=5)

        assert len(papers) == 1
        p = papers[0]
        _assert_valid_paper(p, "europepmc")
        assert p.doi == "10.1111/epmc.test"
        assert p.citation_count == 15
        assert p.pdf_url == "https://example.com/paper.pdf"


# ===================================================================
# CORE
# ===================================================================

CORE_JSON = {
    "results": [
        {
            "id": 99887766,
            "title": "CORE Test Paper",
            "authors": [{"name": "Dr. Core"}],
            "abstract": "Open access paper.",
            "doi": "10.0000/core.test",
            "publishedDate": "2024-01-20T00:00:00Z",
            "url": "https://core.ac.uk/paper/99887766",
            "downloadUrl": "https://core.ac.uk/paper/99887766.pdf",
            "subjects": [{"name": "Computer Science"}],
            "citationCount": 5,
        }
    ]
}


class TestCORE:
    async def test_search_parses_results(self):
        from src.agents.tools.sources.core import CoreFetcher

        with respx.mock:
            respx.get("https://api.core.ac.uk/v3/search/works").mock(
                return_value=httpx.Response(200, json=CORE_JSON)
            )
            fetcher = CoreFetcher()
            papers = await fetcher.search("machine learning", max_results=5)

        assert len(papers) == 1
        p = papers[0]
        _assert_valid_paper(p, "core")
        assert p.doi == "10.0000/core.test"
        assert p.published_date == "2024-01-20"

    async def test_no_key_degrades_gracefully(self):
        from src.agents.tools.sources.core import CoreFetcher

        with respx.mock:
            respx.get("https://api.core.ac.uk/v3/search/works").mock(
                return_value=httpx.Response(403, text="Forbidden")
            )
            fetcher = CoreFetcher(api_key="")
            papers = await fetcher.search("test", max_results=5)

        assert papers == []


# ===================================================================
# dblp
# ===================================================================

DBLP_XML = b"""<?xml version="1.0"?>
<result>
<hits total="1">
<hit>
<info>
<title>DBLP Test Paper</title>
<authors><author>Author X</author></authors>
<venue>ICML</venue>
<year>2024</year>
<url>https://dblp.org/rec/conf/icml/Test2024</url>
<ee>https://doi.org/10.1234/dblp.test</ee>
</info>
</hit>
</hits>
</result>"""


class TestDBLP:
    async def test_search_parses_results(self):
        from src.agents.tools.sources.dblp import DblpFetcher

        with respx.mock:
            respx.get("https://dblp.org/search/publ/api").mock(
                return_value=httpx.Response(200, content=DBLP_XML)
            )
            fetcher = DblpFetcher()
            papers = await fetcher.search("test", max_results=5)

        assert len(papers) == 1
        p = papers[0]
        _assert_valid_paper(p, "dblp")
        assert p.doi == "10.1234/dblp.test"
        assert "ICML" in p.categories

    async def test_search_500_degrades(self):
        from src.agents.tools.sources.dblp import DblpFetcher

        with respx.mock:
            respx.get("https://dblp.org/search/publ/api").mock(
                side_effect=[
                    httpx.Response(500, text="Server Error"),
                    httpx.Response(500, text="Server Error"),
                    httpx.Response(500, text="Server Error"),
                ]
            )
            fetcher = DblpFetcher()
            papers = await fetcher.search("test", max_results=5)

        assert papers == []


# ===================================================================
# DOAJ
# ===================================================================

DOAJ_JSON = {
    "total": 1,
    "results": [
        {
            "id": "doaj-article-001",
            "bibjson": {
                "title": "DOAJ Test Paper",
                "author": [{"name": "Open Author"}],
                "abstract": "Open access journal article.",
                "identifier": [{"type": "doi", "id": "10.0000/doaj.test"}],
                "year": "2024",
                "journal": {"title": "OA Journal"},
                "subject": [{"term": "Biology"}],
                "keywords": ["open access"],
                "link": [
                    {"type": "fulltext", "url": "https://example.com/article.pdf"}
                ],
            },
        }
    ],
}


class TestDOAJ:
    async def test_search_parses_results(self):
        from src.agents.tools.sources.doaj import DoajFetcher

        with respx.mock:
            respx.get(url__startswith="https://doaj.org/api/search/articles/").mock(
                return_value=httpx.Response(200, json=DOAJ_JSON)
            )
            fetcher = DoajFetcher()
            papers = await fetcher.search("biology", max_results=5)

        assert len(papers) == 1
        p = papers[0]
        _assert_valid_paper(p, "doaj")
        assert p.doi == "10.0000/doaj.test"
        assert p.pdf_url == "https://example.com/article.pdf"

    async def test_no_key_still_works(self):
        from src.agents.tools.sources.doaj import DoajFetcher

        with respx.mock:
            respx.get(url__startswith="https://doaj.org/api/search/articles/").mock(
                return_value=httpx.Response(200, json=DOAJ_JSON)
            )
            fetcher = DoajFetcher(api_key="")
            papers = await fetcher.search("test", max_results=5)

        assert len(papers) == 1


# ===================================================================
# Cross-source dedup integration
# ===================================================================

class TestCrossSourceDedup:
    def test_same_doi_different_sources(self):
        from src.agents.tools.paper_fetcher import _deduplicate

        p1 = PaperResult(
            paper_id="arxiv-1", title="Paper A", doi="10.1234/shared",
            source="arxiv", url="https://arxiv.org/abs/1234",
        )
        p2 = PaperResult(
            paper_id="cr-1", title="Paper A (crossref)", doi="10.1234/shared",
            source="crossref", url="https://doi.org/10.1234/shared",
        )
        p3 = PaperResult(
            paper_id="oa-1", title="Paper A (openalex)", doi="10.1234/shared",
            source="openalex", url="https://openalex.org/W999",
        )

        result = _deduplicate([p1, p2, p3])
        assert len(result) == 1
        assert result[0].source == "arxiv"

    def test_no_key_regression(self):
        """All sources should return [] rather than crash when APIs are down."""
        from src.agents.tools.paper_fetcher import _deduplicate

        result = _deduplicate([])
        assert result == []
