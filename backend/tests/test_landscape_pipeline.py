"""Unit tests for the DRL Landscape pipeline components.

Covers:
- assembler: reference sanitisation, normal assembly, model_validator pass
- S2 client enhancements (enriched fields, open access filter, author details)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.models.landscape import (
    CollaborationNetwork,
    DynamicResearchLandscape,
    ResearchGap,
    ResearchGaps,
    ScholarNode,
    TechTree,
    TechTreeEdge,
    TechTreeNode,
)
from src.models.paper import PaperResult, WebSearchItem, WebSearchResult

from src.agents.landscape.assembler import assemble_landscape


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _paper(
    pid: str,
    title: str = "Paper",
    citations: int = 0,
    authors: list[str] | None = None,
    url: str = "",
    doi: str = "",
) -> PaperResult:
    return PaperResult(
        paper_id=pid,
        title=title or f"Paper {pid}",
        authors=authors or ["Author A"],
        citation_count=citations,
        source="semantic_scholar",
        url=url,
        doi=doi,
    )


def _minimal_tech_tree(paper_ids: list[str] | None = None) -> TechTree:
    pids = paper_ids or []
    return TechTree(
        nodes=[
            TechTreeNode(
                node_id="method_a",
                label="Method A",
                node_type="method",
                description="A method.",
                representative_paper_ids=pids[:1],
            ),
        ],
        edges=[],
    )


def _minimal_gaps(paper_ids: list[str] | None = None) -> ResearchGaps:
    pids = paper_ids or []
    return ResearchGaps(
        gaps=[
            ResearchGap(
                gap_id="gap_1",
                title="A gap",
                description="An open problem.",
                evidence_paper_ids=pids[:1],
            ),
        ],
        summary="Summary",
    )


# ===================================================================
# assembler tests
# ===================================================================

class TestAssembler:
    """Tests for assemble_landscape."""

    def test_basic_assembly(self):
        """Happy path: all references valid, assembler produces valid landscape."""
        p1 = _paper("p1", "Paper 1", 10)
        p2 = _paper("p2", "Paper 2", 5)

        landscape = assemble_landscape(
            topic="Test",
            papers=[p1, p2],
            tech_tree=_minimal_tech_tree(["p1", "p2"]),
            collaboration_network=CollaborationNetwork(),
            research_gaps=_minimal_gaps(["p1"]),
        )
        assert isinstance(landscape, DynamicResearchLandscape)
        assert landscape.meta.topic == "Test"
        assert landscape.meta.paper_count == 2
        assert len(landscape.papers) == 2

    def test_sanitises_invalid_paper_ids_in_tech_tree(self):
        """Invalid paper_id in TechTree nodes is removed by sanitisation."""
        p1 = _paper("p1")

        landscape = assemble_landscape(
            topic="Test",
            papers=[p1],
            tech_tree=_minimal_tech_tree(["p1", "INVALID_ID"]),
            collaboration_network=CollaborationNetwork(),
            research_gaps=_minimal_gaps(["p1"]),
        )
        node = landscape.tech_tree.nodes[0]
        assert "INVALID_ID" not in node.representative_paper_ids

    def test_sanitises_invalid_paper_ids_in_gaps(self):
        """Invalid paper_id in ResearchGap is removed."""
        p1 = _paper("p1")

        landscape = assemble_landscape(
            topic="Test",
            papers=[p1],
            tech_tree=TechTree(),
            collaboration_network=CollaborationNetwork(),
            research_gaps=ResearchGaps(
                gaps=[
                    ResearchGap(
                        gap_id="g1",
                        title="Gap",
                        description="Desc",
                        evidence_paper_ids=["p1", "FAKE"],
                    )
                ],
            ),
        )
        assert landscape.research_gaps.gaps[0].evidence_paper_ids == ["p1"]

    def test_sanitises_collab_network_paper_ids(self):
        """Invalid paper_ids in CollaborationNetwork are cleaned."""
        p1 = _paper("p1")

        landscape = assemble_landscape(
            topic="Test",
            papers=[p1],
            tech_tree=TechTree(),
            collaboration_network=CollaborationNetwork(
                nodes=[
                    ScholarNode(
                        scholar_id="s1",
                        name="Scholar",
                        top_paper_ids=["p1", "GHOST"],
                    )
                ],
                edges=[],
            ),
            research_gaps=ResearchGaps(),
        )
        assert landscape.collaboration_network.nodes[0].top_paper_ids == ["p1"]

    def test_sources_collected(self):
        """URLs and DOIs from papers appear in sources."""
        p = _paper("p1", url="https://example.com", doi="10.1234/test")

        landscape = assemble_landscape(
            topic="Test",
            papers=[p],
            tech_tree=TechTree(),
            collaboration_network=CollaborationNetwork(),
            research_gaps=ResearchGaps(),
        )
        assert "https://example.com" in landscape.sources
        assert "10.1234/test" in landscape.sources

    def test_does_not_mutate_original(self):
        """Assembler deep-copies; original objects are unchanged."""
        p1 = _paper("p1")
        tt = _minimal_tech_tree(["p1", "BAD"])
        original_ids = list(tt.nodes[0].representative_paper_ids)

        assemble_landscape(
            topic="Test",
            papers=[p1],
            tech_tree=tt,
            collaboration_network=CollaborationNetwork(),
            research_gaps=_minimal_gaps(["p1"]),
        )
        assert tt.nodes[0].representative_paper_ids == original_ids


# ===================================================================
# s2_client enhancements tests
# ===================================================================

class TestS2ClientEnhancements:
    """Tests for S2 client methods."""

    def test_extract_author_details(self):
        from src.agents.tools.s2_client import _extract_author_details

        raw = {
            "authors": [
                {
                    "authorId": "123",
                    "name": "Alice",
                    "affiliations": ["MIT", "Stanford"],
                },
                {
                    "authorId": "456",
                    "name": "Bob",
                    "affiliations": [],
                },
                {
                    "name": "Ghost",
                },
            ],
        }
        details = _extract_author_details(raw)
        assert len(details) == 3
        assert details[0]["author_id"] == "123"
        assert details[0]["name"] == "Alice"
        assert details[0]["affiliations"] == ["MIT", "Stanford"]
        assert details[1]["author_id"] == "456"
        assert details[2]["author_id"] == ""

    def test_extract_author_details_empty(self):
        from src.agents.tools.s2_client import _extract_author_details

        assert _extract_author_details({}) == []
        assert _extract_author_details({"authors": None}) == []
        assert _extract_author_details({"authors": []}) == []

    def test_enriched_fields_contains_author_sub_fields(self):
        from src.agents.tools.s2_client import ENRICHED_FIELDS, DEFAULT_FIELDS

        assert "authors.authorId" in ENRICHED_FIELDS
        assert "authors.affiliations" in ENRICHED_FIELDS
        for f in DEFAULT_FIELDS:
            assert f in ENRICHED_FIELDS

    @pytest.mark.asyncio
    async def test_open_access_pdf_false_does_not_filter(self):
        from src.agents.tools.s2_client import SemanticScholarClient

        captured_params: dict = {}

        async def mock_get(self_inner, endpoint, params=None):
            captured_params.update(params or {})
            return {"data": [], "total": 0}

        with patch.object(SemanticScholarClient, "_get", mock_get):
            client = SemanticScholarClient(api_key="fake")
            await client.search_papers("test", open_access_pdf=False)

        assert "openAccessPdf" not in captured_params

    @pytest.mark.asyncio
    async def test_open_access_pdf_true_adds_filter(self):
        from src.agents.tools.s2_client import SemanticScholarClient

        captured_params: dict = {}

        async def mock_get(self_inner, endpoint, params=None):
            captured_params.update(params or {})
            return {"data": [], "total": 0}

        with patch.object(SemanticScholarClient, "_get", mock_get):
            client = SemanticScholarClient(api_key="fake")
            await client.search_papers("test", open_access_pdf=True)

        assert "openAccessPdf" in captured_params
