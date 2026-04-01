"""Unit tests for the DRL Landscape pipeline components.

Covers:
- graph_builder: co-authorship pairing, dedup merging, noise filtering
- assembler: reference sanitisation, normal assembly, model_validator pass
- analyzer: mock call_llm → LandscapeAnalysis
- retriever: mock S2 client → EnrichedRetrievedData structure
- pipeline: end-to-end with all external calls mocked
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.landscape import (
    CollaborationNetwork,
    ComparisonMatrix,
    DynamicResearchLandscape,
    MethodologyDetail,
    PaperComparison,
    ResearchGap,
    ResearchGaps,
    ScholarNode,
    TechTree,
    TechTreeEdge,
    TechTreeNode,
)
from src.models.paper import PaperResult, SearchResult, WebSearchResult

from src.agents.landscape.schemas import (
    EnrichedPaper,
    EnrichedRetrievedData,
    LandscapeAnalysis,
    S2AuthorDetail,
)
from src.agents.landscape.graph_builder import build_collaboration_network
from src.agents.landscape.assembler import assemble_landscape
from src.agents.landscape.analyzer import _format_evidence


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _paper(pid: str, title: str = "Paper", citations: int = 0, authors: list[str] | None = None) -> PaperResult:
    return PaperResult(
        paper_id=pid,
        title=title or f"Paper {pid}",
        authors=authors or ["Author A"],
        citation_count=citations,
        source="semantic_scholar",
    )


def _author(aid: str, name: str, affiliations: list[str] | None = None) -> S2AuthorDetail:
    return S2AuthorDetail(author_id=aid, name=name, affiliations=affiliations or [])


def _enriched(paper: PaperResult, authors: list[S2AuthorDetail] | None = None) -> EnrichedPaper:
    return EnrichedPaper(paper=paper, author_details=authors or [])


def _minimal_analysis(paper_ids: list[str] | None = None) -> LandscapeAnalysis:
    """Build a minimal valid LandscapeAnalysis referencing given paper_ids."""
    pids = paper_ids or []
    nodes = [
        TechTreeNode(
            node_id="method_a",
            label="Method A",
            node_type="method",
            description="A method.",
            representative_paper_ids=pids[:1],
        ),
    ]
    edges: list[TechTreeEdge] = []
    comparisons = []
    for pid in pids[:2]:
        comparisons.append(
            PaperComparison(
                paper_id=pid,
                title=f"Paper {pid}",
                methodology=MethodologyDetail(approach="Approach"),
            )
        )
    gaps = [
        ResearchGap(
            gap_id="gap_1",
            title="A gap",
            description="An open problem.",
            evidence_paper_ids=pids[:1],
        ),
    ]
    return LandscapeAnalysis(
        tech_tree=TechTree(nodes=nodes, edges=edges),
        comparison_matrix=ComparisonMatrix(papers=comparisons),
        research_gaps=ResearchGaps(gaps=gaps, summary="Summary"),
    )


# ===================================================================
# graph_builder tests
# ===================================================================

class TestGraphBuilder:
    """Tests for build_collaboration_network."""

    def test_empty_input(self):
        net = build_collaboration_network([])
        assert net.nodes == []
        assert net.edges == []

    def test_single_paper_two_authors(self):
        """Two co-authors on one paper, but each has paper_count=1 → filtered."""
        p = _paper("p1")
        ep = _enriched(p, [_author("a1", "Alice"), _author("a2", "Bob")])
        net = build_collaboration_network([ep])
        assert len(net.nodes) == 0
        assert len(net.edges) == 0

    def test_two_papers_same_pair(self):
        """Two papers with the same two authors → both retained, edge weight=2."""
        p1 = _paper("p1", citations=10)
        p2 = _paper("p2", citations=5)
        authors = [_author("a1", "Alice"), _author("a2", "Bob")]
        eps = [_enriched(p1, authors), _enriched(p2, authors)]
        net = build_collaboration_network(eps)

        assert len(net.nodes) == 2
        assert {n.scholar_id for n in net.nodes} == {"a1", "a2"}
        assert len(net.edges) == 1
        assert net.edges[0].weight == 2
        assert set(net.edges[0].shared_paper_ids) == {"p1", "p2"}

    def test_author_fields_accumulated(self):
        """paper_count, citation_count, affiliations accumulate across papers."""
        p1 = _paper("p1", citations=100)
        p2 = _paper("p2", citations=50)
        a1 = _author("a1", "Alice", ["MIT"])
        a1b = _author("a1", "Alice", ["Stanford"])
        a2 = _author("a2", "Bob", ["MIT"])

        eps = [
            _enriched(p1, [a1, a2]),
            _enriched(p2, [a1b, a2]),
        ]
        net = build_collaboration_network(eps)

        alice = next(n for n in net.nodes if n.scholar_id == "a1")
        assert alice.paper_count == 2
        assert alice.citation_count == 150
        assert set(alice.affiliations) == {"MIT", "Stanford"}

    def test_authors_without_id_ignored(self):
        """Authors with empty author_id don't create nodes or edges."""
        p1 = _paper("p1")
        p2 = _paper("p2")
        a_no_id = S2AuthorDetail(author_id="", name="Ghost")
        a_real = _author("a1", "Alice")

        eps = [_enriched(p1, [a_no_id, a_real]), _enriched(p2, [a_real])]
        net = build_collaboration_network(eps)
        # Alice appears in 2 papers → retained; Ghost has no id → excluded
        assert len(net.nodes) == 1
        assert net.nodes[0].scholar_id == "a1"
        assert len(net.edges) == 0

    def test_three_authors_pairwise_edges(self):
        """3 co-authors on 2 papers produce 3 edges."""
        p1 = _paper("p1")
        p2 = _paper("p2")
        authors = [_author("a1", "Alice"), _author("a2", "Bob"), _author("a3", "Carol")]
        eps = [_enriched(p1, authors), _enriched(p2, authors)]
        net = build_collaboration_network(eps)

        assert len(net.nodes) == 3
        assert len(net.edges) == 3
        for edge in net.edges:
            assert edge.weight == 2

    def test_top_paper_ids_capped(self):
        """top_paper_ids should be capped at 5."""
        papers = [_paper(f"p{i}", citations=i) for i in range(7)]
        a1 = _author("a1", "Alice")
        a2 = _author("a2", "Bob")
        eps = [_enriched(p, [a1, a2]) for p in papers]
        net = build_collaboration_network(eps)

        alice = next(n for n in net.nodes if n.scholar_id == "a1")
        assert len(alice.top_paper_ids) <= 5
        assert alice.top_paper_ids[0] == "p6"


# ===================================================================
# assembler tests
# ===================================================================

class TestAssembler:
    """Tests for assemble_landscape."""

    def test_basic_assembly(self):
        """Happy path: all references valid, assembler produces valid landscape."""
        p1 = _paper("p1", "Paper 1", 10)
        p2 = _paper("p2", "Paper 2", 5)
        eps = [_enriched(p1), _enriched(p2)]
        data = EnrichedRetrievedData(enriched_papers=eps)
        analysis = _minimal_analysis(["p1", "p2"])
        collab = CollaborationNetwork()

        landscape = assemble_landscape(
            topic="Test",
            analysis=analysis,
            collaboration_network=collab,
            enriched_data=data,
        )
        assert isinstance(landscape, DynamicResearchLandscape)
        assert landscape.meta.topic == "Test"
        assert landscape.meta.paper_count == 2
        assert len(landscape.papers) == 2

    def test_sanitises_invalid_paper_ids_in_tech_tree(self):
        """Invalid paper_id in TechTree nodes is removed by sanitisation."""
        p1 = _paper("p1")
        eps = [_enriched(p1)]
        data = EnrichedRetrievedData(enriched_papers=eps)
        analysis = _minimal_analysis(["p1", "INVALID_ID"])
        collab = CollaborationNetwork()

        landscape = assemble_landscape(
            topic="Test",
            analysis=analysis,
            collaboration_network=collab,
            enriched_data=data,
        )
        node = landscape.tech_tree.nodes[0]
        assert "INVALID_ID" not in node.representative_paper_ids

    def test_sanitises_invalid_paper_ids_in_gaps(self):
        """Invalid paper_id in ResearchGap is removed."""
        p1 = _paper("p1")
        eps = [_enriched(p1)]
        data = EnrichedRetrievedData(enriched_papers=eps)

        analysis = LandscapeAnalysis(
            tech_tree=TechTree(),
            comparison_matrix=ComparisonMatrix(),
            research_gaps=ResearchGaps(
                gaps=[
                    ResearchGap(
                        gap_id="g1",
                        title="Gap",
                        description="Desc",
                        evidence_paper_ids=["p1", "FAKE"],
                    )
                ]
            ),
        )
        collab = CollaborationNetwork()
        landscape = assemble_landscape(
            topic="Test",
            analysis=analysis,
            collaboration_network=collab,
            enriched_data=data,
        )
        assert landscape.research_gaps.gaps[0].evidence_paper_ids == ["p1"]

    def test_sanitises_invalid_comparison(self):
        """PaperComparison with invalid paper_id is removed entirely."""
        p1 = _paper("p1")
        eps = [_enriched(p1)]
        data = EnrichedRetrievedData(enriched_papers=eps)

        analysis = LandscapeAnalysis(
            tech_tree=TechTree(),
            comparison_matrix=ComparisonMatrix(
                papers=[
                    PaperComparison(
                        paper_id="p1",
                        title="Valid",
                        methodology=MethodologyDetail(approach="A"),
                    ),
                    PaperComparison(
                        paper_id="MISSING",
                        title="Invalid",
                        methodology=MethodologyDetail(approach="B"),
                    ),
                ]
            ),
            research_gaps=ResearchGaps(),
        )
        collab = CollaborationNetwork()
        landscape = assemble_landscape(
            topic="Test",
            analysis=analysis,
            collaboration_network=collab,
            enriched_data=data,
        )
        assert len(landscape.comparison_matrix.papers) == 1
        assert landscape.comparison_matrix.papers[0].paper_id == "p1"

    def test_sanitises_collab_network_paper_ids(self):
        """Invalid paper_ids in CollaborationNetwork are cleaned."""
        p1 = _paper("p1")
        eps = [_enriched(p1)]
        data = EnrichedRetrievedData(enriched_papers=eps)
        analysis = LandscapeAnalysis(
            tech_tree=TechTree(),
            comparison_matrix=ComparisonMatrix(),
            research_gaps=ResearchGaps(),
        )
        collab = CollaborationNetwork(
            nodes=[
                ScholarNode(
                    scholar_id="s1",
                    name="Scholar",
                    top_paper_ids=["p1", "GHOST"],
                )
            ],
            edges=[],
        )
        landscape = assemble_landscape(
            topic="Test",
            analysis=analysis,
            collaboration_network=collab,
            enriched_data=data,
        )
        assert landscape.collaboration_network.nodes[0].top_paper_ids == ["p1"]

    def test_sources_collected(self):
        """URLs and DOIs from papers + web results appear in sources."""
        from src.models.paper import WebSearchItem

        p = PaperResult(
            paper_id="p1", title="T", url="https://example.com", doi="10.1234/test",
        )
        eps = [_enriched(p)]
        wr = WebSearchResult(
            query="q",
            results=[WebSearchItem(
                url="https://web.example.com", content="text", title="T", score=0.9,
            )],
        )
        data = EnrichedRetrievedData(enriched_papers=eps, web_results=[wr])
        analysis = LandscapeAnalysis(
            tech_tree=TechTree(),
            comparison_matrix=ComparisonMatrix(),
            research_gaps=ResearchGaps(),
        )
        landscape = assemble_landscape(
            topic="Test",
            analysis=analysis,
            collaboration_network=CollaborationNetwork(),
            enriched_data=data,
        )
        assert "https://example.com" in landscape.sources
        assert "10.1234/test" in landscape.sources
        assert "https://web.example.com" in landscape.sources

    def test_does_not_mutate_original_analysis(self):
        """Assembler deep-copies; original analysis is unchanged."""
        p1 = _paper("p1")
        eps = [_enriched(p1)]
        data = EnrichedRetrievedData(enriched_papers=eps)
        analysis = _minimal_analysis(["p1", "BAD"])
        original_ids = list(analysis.tech_tree.nodes[0].representative_paper_ids)

        assemble_landscape(
            topic="Test",
            analysis=analysis,
            collaboration_network=CollaborationNetwork(),
            enriched_data=data,
        )
        assert analysis.tech_tree.nodes[0].representative_paper_ids == original_ids


# ===================================================================
# analyzer tests
# ===================================================================

class TestAnalyzer:
    """Tests for the analyzer module."""

    def test_format_evidence_includes_paper_ids(self):
        """Formatted evidence must contain paper_id for LLM referencing."""
        p = _paper("abc123", "Test Paper", 42)
        data = EnrichedRetrievedData(enriched_papers=[_enriched(p)])
        text = _format_evidence(data)
        assert "paper_id=abc123" in text
        assert "Test Paper" in text

    def test_format_evidence_citation_and_reference_maps(self):
        """Citation and reference maps appear in formatted evidence."""
        p = _paper("p1", "Main Paper", 100)
        cited_by = _paper("c1", "Citing Paper")
        ref = _paper("r1", "Referenced Paper")
        data = EnrichedRetrievedData(
            enriched_papers=[_enriched(p)],
            citation_map={"p1": [cited_by]},
            reference_map={"p1": [ref]},
        )
        text = _format_evidence(data)
        assert "p1 cited by:" in text
        assert "Citing Paper" in text
        assert "p1 references:" in text
        assert "Referenced Paper" in text

    def test_format_evidence_empty(self):
        """Empty data returns the no-evidence sentinel."""
        data = EnrichedRetrievedData()
        text = _format_evidence(data)
        assert "No evidence" in text

    def test_format_evidence_truncates_papers(self):
        """Papers beyond max_papers are omitted."""
        papers = [_enriched(_paper(f"p{i}")) for i in range(50)]
        data = EnrichedRetrievedData(enriched_papers=papers)
        text = _format_evidence(data, max_papers=5)
        assert "omitted" in text

    @pytest.mark.asyncio
    async def test_analyze_landscape_calls_llm(self):
        """analyze_landscape should call call_llm with LandscapeAnalysis format."""
        mock_result = _minimal_analysis(["p1"])
        data = EnrichedRetrievedData(
            enriched_papers=[_enriched(_paper("p1"))],
        )
        with patch(
            "src.agents.landscape.analyzer.call_llm",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_llm:
            from src.agents.landscape.analyzer import analyze_landscape
            result = await analyze_landscape("Test topic", data)

            mock_llm.assert_awaited_once()
            assert isinstance(result, LandscapeAnalysis)
            assert len(result.tech_tree.nodes) == 1


# ===================================================================
# retriever tests
# ===================================================================

class TestRetriever:
    """Tests for the enriched retriever (mocked external calls)."""

    @pytest.mark.asyncio
    async def test_fetch_enriched_context_structure(self):
        """Verify that fetch_enriched_context returns EnrichedRetrievedData."""
        mock_search_result = SearchResult(
            query="test",
            total=1,
            papers=[_paper("p1", "Paper 1", 100)],
        )
        mock_web_result = WebSearchResult(query="test")

        with (
            patch(
                "src.agents.landscape.retriever._search_s2",
                new_callable=AsyncMock,
                return_value=[mock_search_result],
            ),
            patch(
                "src.agents.landscape.retriever._search_web",
                new_callable=AsyncMock,
                return_value=[mock_web_result],
            ),
            patch(
                "src.agents.landscape.retriever._enrich_authors",
                new_callable=AsyncMock,
                return_value={"p1": [_author("a1", "Alice")]},
            ),
            patch(
                "src.agents.landscape.retriever._fetch_references",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "src.agents.landscape.retriever._fetch_citations",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            from src.agents.landscape.retriever import fetch_enriched_context
            from src.agents.exploration.schemas import SearchPlan

            plan = SearchPlan(
                paper_keywords=["test"],
                web_queries=["test query"],
                focus_areas=["area"],
            )

            result = await fetch_enriched_context(plan)

            assert isinstance(result, EnrichedRetrievedData)
            assert len(result.enriched_papers) >= 1
            ep = next(
                (ep for ep in result.enriched_papers if ep.paper.paper_id == "p1"),
                None,
            )
            assert ep is not None
            assert len(ep.author_details) == 1
            assert ep.author_details[0].name == "Alice"


# ===================================================================
# pipeline integration test
# ===================================================================

class TestPipeline:
    """End-to-end pipeline test with all externals mocked."""

    @pytest.mark.asyncio
    async def test_run_landscape_pipeline(self):
        """Pipeline produces a valid DynamicResearchLandscape."""
        from src.agents.exploration.schemas import SearchPlan

        mock_plan = SearchPlan(
            paper_keywords=["transformers"],
            web_queries=["transformer trends"],
            focus_areas=["NLP"],
            source_hints=["arxiv"],
            domain_tags=["computer_science"],
            confidence=0.9,
        )
        p1 = _paper("p1", "Attention Is All You Need", 50000)
        p2 = _paper("p2", "BERT", 30000)
        mock_enriched = EnrichedRetrievedData(
            enriched_papers=[
                _enriched(p1, [_author("a1", "Vaswani"), _author("a2", "Shazeer")]),
                _enriched(p2, [_author("a1", "Vaswani"), _author("a3", "Devlin")]),
            ],
        )
        mock_analysis = _minimal_analysis(["p1", "p2"])
        mock_collab = CollaborationNetwork()

        with (
            patch(
                "src.agents.landscape.pipeline.generate_search_plan",
                new_callable=AsyncMock,
                return_value=mock_plan,
            ),
            patch(
                "src.agents.landscape.pipeline.fetch_enriched_context",
                new_callable=AsyncMock,
                return_value=mock_enriched,
            ),
            patch(
                "src.agents.landscape.pipeline.analyze_landscape",
                new_callable=AsyncMock,
                return_value=mock_analysis,
            ),
            patch(
                "src.agents.landscape.pipeline.build_collaboration_network",
                return_value=mock_collab,
            ),
        ):
            from src.agents.landscape.pipeline import run_landscape_pipeline

            progress_msgs: list[str] = []

            async def track_progress(msg: str) -> None:
                progress_msgs.append(msg)

            landscape = await run_landscape_pipeline(
                "Vision Transformers",
                on_progress=track_progress,
            )

            assert isinstance(landscape, DynamicResearchLandscape)
            assert landscape.meta.topic == "Vision Transformers"
            assert len(landscape.papers) == 2
            assert len(progress_msgs) == 4

    @pytest.mark.asyncio
    async def test_pipeline_with_graph_builder_integration(self):
        """Pipeline uses real graph_builder (not mocked) to build collab network."""
        from src.agents.exploration.schemas import SearchPlan

        mock_plan = SearchPlan(
            paper_keywords=["test"],
            web_queries=["test"],
            focus_areas=["test"],
        )
        p1 = _paper("p1", "Paper 1", 10)
        p2 = _paper("p2", "Paper 2", 5)
        a1 = _author("a1", "Alice")
        a2 = _author("a2", "Bob")
        mock_enriched = EnrichedRetrievedData(
            enriched_papers=[
                _enriched(p1, [a1, a2]),
                _enriched(p2, [a1, a2]),
            ],
        )
        mock_analysis = _minimal_analysis(["p1", "p2"])

        with (
            patch(
                "src.agents.landscape.pipeline.generate_search_plan",
                new_callable=AsyncMock,
                return_value=mock_plan,
            ),
            patch(
                "src.agents.landscape.pipeline.fetch_enriched_context",
                new_callable=AsyncMock,
                return_value=mock_enriched,
            ),
            patch(
                "src.agents.landscape.pipeline.analyze_landscape",
                new_callable=AsyncMock,
                return_value=mock_analysis,
            ),
        ):
            from src.agents.landscape.pipeline import run_landscape_pipeline

            landscape = await run_landscape_pipeline("Test Topic")

            assert isinstance(landscape, DynamicResearchLandscape)
            assert len(landscape.collaboration_network.nodes) == 2
            assert len(landscape.collaboration_network.edges) == 1


# ===================================================================
# s2_client enhancements tests
# ===================================================================

class TestS2ClientEnhancements:
    """Tests for the new S2 client methods."""

    def test_extract_author_details(self):
        """_extract_author_details extracts structured author info."""
        from src.agents.landscape.retriever import S2AuthorDetail
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
        """Empty/missing authors field returns empty list."""
        from src.agents.tools.s2_client import _extract_author_details

        assert _extract_author_details({}) == []
        assert _extract_author_details({"authors": None}) == []
        assert _extract_author_details({"authors": []}) == []

    def test_enriched_fields_contains_author_sub_fields(self):
        """ENRICHED_FIELDS should include author sub-fields."""
        from src.agents.tools.s2_client import ENRICHED_FIELDS, DEFAULT_FIELDS

        assert "authors.authorId" in ENRICHED_FIELDS
        assert "authors.affiliations" in ENRICHED_FIELDS
        for f in DEFAULT_FIELDS:
            assert f in ENRICHED_FIELDS

    @pytest.mark.asyncio
    async def test_open_access_pdf_false_does_not_filter(self):
        """open_access_pdf=False should NOT add the openAccessPdf filter param."""
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
        """open_access_pdf=True should add the openAccessPdf filter param."""
        from src.agents.tools.s2_client import SemanticScholarClient

        captured_params: dict = {}

        async def mock_get(self_inner, endpoint, params=None):
            captured_params.update(params or {})
            return {"data": [], "total": 0}

        with patch.object(SemanticScholarClient, "_get", mock_get):
            client = SemanticScholarClient(api_key="fake")
            await client.search_papers("test", open_access_pdf=True)

        assert "openAccessPdf" in captured_params
