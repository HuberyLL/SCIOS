"""Unit tests for Dynamic Research Landscape Pydantic schemas.

Validates serialisation round-trips, default values, constraint enforcement,
runtime model_validator integrity checks, and the relationship between
the top-level envelope and its sub-models.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.models.paper import PaperResult
from src.models.landscape import (
    CollaborationEdge,
    CollaborationNetwork,
    DynamicResearchLandscape,
    LandscapeIncrement,
    LandscapeMeta,
    ResearchGap,
    ResearchGaps,
    ScholarNode,
    TechTree,
    TechTreeEdge,
    TechTreeNode,
)

# ---------------------------------------------------------------------------
# Reusable fixtures
# ---------------------------------------------------------------------------

_TS = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _paper(id_: str = "p1", title: str = "Test Paper") -> PaperResult:
    return PaperResult(
        paper_id=id_,
        title=title,
        authors=["Alice", "Bob"],
        abstract="Abstract text.",
        doi=f"10.1234/{id_}",
        published_date="2024-06-01",
        url=f"https://example.com/{id_}",
        source="semantic_scholar",
        citation_count=42,
    )


def _tech_node(**overrides) -> TechTreeNode:
    defaults = dict(
        node_id="method_transformer",
        label="Transformer",
        node_type="method",
        year=2017,
        description="Self-attention-based architecture.",
        representative_paper_ids=["p1"],
    )
    defaults.update(overrides)
    return TechTreeNode(**defaults)


def _tech_edge(**overrides) -> TechTreeEdge:
    defaults = dict(
        source="method_transformer",
        target="method_transformer",
        relation="evolves_from",
    )
    defaults.update(overrides)
    return TechTreeEdge(**defaults)


def _scholar(**overrides) -> ScholarNode:
    defaults = dict(
        scholar_id="scholar_vaswani",
        name="Ashish Vaswani",
        affiliations=["Google Brain"],
        paper_count=5,
        citation_count=90000,
        top_paper_ids=["p1"],
    )
    defaults.update(overrides)
    return ScholarNode(**defaults)


def _collab_edge(**overrides) -> CollaborationEdge:
    defaults = dict(
        source="scholar_vaswani",
        target="scholar_vaswani",
        weight=3,
        shared_paper_ids=["p1"],
    )
    defaults.update(overrides)
    return CollaborationEdge(**defaults)


def _gap(**overrides) -> ResearchGap:
    defaults = dict(
        gap_id="gap_1",
        title="Lack of low-resource benchmarks",
        description="Most methods are only evaluated on high-resource language pairs.",
        evidence_paper_ids=["p1"],
        potential_approaches=["Create multilingual benchmark suite"],
        impact="high",
    )
    defaults.update(overrides)
    return ResearchGap(**defaults)


def _full_landscape() -> DynamicResearchLandscape:
    return DynamicResearchLandscape(
        meta=LandscapeMeta(
            topic="Transformer in NLP",
            generated_at=_TS,
            paper_count=1,
            version=1,
        ),
        tech_tree=TechTree(
            nodes=[_tech_node()],
            edges=[_tech_edge()],
        ),
        collaboration_network=CollaborationNetwork(
            nodes=[_scholar()],
            edges=[_collab_edge()],
        ),
        research_gaps=ResearchGaps(gaps=[_gap()], summary="Several gaps identified."),
        papers=[_paper()],
        sources=["https://example.com/p1"],
    )


# ===================================================================
# TechTree
# ===================================================================


class TestTechTreeNode:
    def test_valid_construction(self):
        node = _tech_node()
        assert node.node_id == "method_transformer"
        assert node.is_new is False

    def test_is_new_flag(self):
        node = _tech_node(is_new=True)
        assert node.is_new is True

    def test_invalid_node_type_rejected(self):
        with pytest.raises(ValidationError):
            _tech_node(node_type="unknown")

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            TechTreeNode(label="X", node_type="method", description="Y")


class TestTechTreeEdge:
    def test_valid_construction(self):
        edge = _tech_edge()
        assert edge.relation == "evolves_from"
        assert edge.label == ""

    def test_invalid_relation_rejected(self):
        with pytest.raises(ValidationError):
            _tech_edge(relation="copies")


class TestTechTree:
    def test_defaults_to_empty(self):
        tree = TechTree()
        assert tree.nodes == []
        assert tree.edges == []

    def test_json_round_trip(self):
        tree = TechTree(nodes=[_tech_node()], edges=[_tech_edge()])
        restored = TechTree.model_validate_json(tree.model_dump_json())
        assert restored.nodes[0].node_id == "method_transformer"
        assert restored.edges[0].relation == "evolves_from"

    def test_duplicate_node_id_rejected(self):
        with pytest.raises(ValidationError, match="duplicate node_id"):
            TechTree(
                nodes=[
                    _tech_node(node_id="dup"),
                    _tech_node(node_id="dup", label="Another"),
                ],
            )

    def test_edge_source_not_in_nodes_rejected(self):
        with pytest.raises(ValidationError, match="non-existent node"):
            TechTree(
                nodes=[_tech_node(node_id="a")],
                edges=[TechTreeEdge(source="missing", target="a", relation="extends")],
            )

    def test_edge_target_not_in_nodes_rejected(self):
        with pytest.raises(ValidationError, match="non-existent node"):
            TechTree(
                nodes=[_tech_node(node_id="a")],
                edges=[TechTreeEdge(source="a", target="missing", relation="extends")],
            )


# ===================================================================
# CollaborationNetwork
# ===================================================================


class TestScholarNode:
    def test_valid_construction(self):
        s = _scholar()
        assert s.name == "Ashish Vaswani"
        assert s.affiliations == ["Google Brain"]

    def test_defaults(self):
        s = ScholarNode(scholar_id="s1", name="Test")
        assert s.paper_count == 0
        assert s.citation_count == 0
        assert s.top_paper_ids == []
        assert s.is_new is False


class TestCollaborationEdge:
    def test_weight_min_constraint(self):
        with pytest.raises(ValidationError):
            _collab_edge(weight=0)

    def test_valid_weight(self):
        edge = _collab_edge(weight=10)
        assert edge.weight == 10


class TestCollaborationNetwork:
    def test_defaults_to_empty(self):
        net = CollaborationNetwork()
        assert net.nodes == []
        assert net.edges == []

    def test_json_round_trip(self):
        net = CollaborationNetwork(nodes=[_scholar()], edges=[_collab_edge()])
        restored = CollaborationNetwork.model_validate_json(net.model_dump_json())
        assert restored.nodes[0].scholar_id == "scholar_vaswani"
        assert restored.edges[0].weight == 3

    def test_duplicate_scholar_id_rejected(self):
        with pytest.raises(ValidationError, match="duplicate scholar_id"):
            CollaborationNetwork(
                nodes=[
                    _scholar(scholar_id="dup"),
                    _scholar(scholar_id="dup", name="Another"),
                ],
            )

    def test_edge_source_not_in_nodes_rejected(self):
        with pytest.raises(ValidationError, match="non-existent scholar"):
            CollaborationNetwork(
                nodes=[_scholar(scholar_id="a")],
                edges=[CollaborationEdge(source="missing", target="a")],
            )

    def test_edge_target_not_in_nodes_rejected(self):
        with pytest.raises(ValidationError, match="non-existent scholar"):
            CollaborationNetwork(
                nodes=[_scholar(scholar_id="a")],
                edges=[CollaborationEdge(source="a", target="missing")],
            )


# ===================================================================
# ResearchGaps
# ===================================================================


class TestResearchGap:
    def test_valid_construction(self):
        gap = _gap()
        assert gap.impact == "high"
        assert len(gap.potential_approaches) == 1

    def test_invalid_impact_rejected(self):
        with pytest.raises(ValidationError):
            _gap(impact="critical")

    def test_defaults(self):
        gap = ResearchGap(gap_id="g", title="T", description="D")
        assert gap.evidence_paper_ids == []
        assert gap.potential_approaches == []
        assert gap.impact == "medium"


class TestResearchGaps:
    def test_defaults_to_empty(self):
        rg = ResearchGaps()
        assert rg.gaps == []
        assert rg.summary == ""


# ===================================================================
# DynamicResearchLandscape (Envelope)
# ===================================================================


class TestLandscapeMeta:
    def test_version_must_be_positive(self):
        with pytest.raises(ValidationError):
            LandscapeMeta(topic="X", generated_at=_TS, version=0)

    def test_defaults(self):
        m = LandscapeMeta(topic="X", generated_at=_TS)
        assert m.paper_count == 0
        assert m.version == 1

    def test_generated_at_is_datetime(self):
        m = LandscapeMeta(topic="X", generated_at="2024-06-01T12:00:00Z")
        assert isinstance(m.generated_at, datetime)

    def test_generated_at_rejects_bad_format(self):
        with pytest.raises(ValidationError):
            LandscapeMeta(topic="X", generated_at="not-a-date")


class TestDynamicResearchLandscape:
    def test_minimal_construction(self):
        landscape = DynamicResearchLandscape(
            meta=LandscapeMeta(topic="Test", generated_at=_TS),
        )
        assert landscape.tech_tree.nodes == []
        assert landscape.collaboration_network.edges == []
        assert landscape.research_gaps.gaps == []
        assert landscape.papers == []
        assert landscape.sources == []

    def test_full_construction(self):
        landscape = _full_landscape()
        assert landscape.meta.topic == "Transformer in NLP"
        assert len(landscape.tech_tree.nodes) == 1
        assert len(landscape.collaboration_network.nodes) == 1
        assert len(landscape.research_gaps.gaps) == 1
        assert len(landscape.papers) == 1

    def test_json_round_trip(self):
        original = _full_landscape()
        json_str = original.model_dump_json()
        restored = DynamicResearchLandscape.model_validate_json(json_str)

        assert restored.meta.topic == original.meta.topic
        assert restored.meta.version == original.meta.version
        assert isinstance(restored.meta.generated_at, datetime)
        assert restored.tech_tree.nodes[0].node_id == "method_transformer"
        assert restored.collaboration_network.nodes[0].name == "Ashish Vaswani"
        assert restored.research_gaps.gaps[0].impact == "high"
        assert restored.papers[0].paper_id == "p1"
        assert restored.sources == ["https://example.com/p1"]

    def test_dict_round_trip(self):
        original = _full_landscape()
        data = original.model_dump()
        restored = DynamicResearchLandscape.model_validate(data)
        assert restored == original

    def test_paper_id_validator_catches_missing_ref_in_tech_tree(self):
        with pytest.raises(ValidationError, match="paper_id reference"):
            DynamicResearchLandscape(
                meta=LandscapeMeta(topic="T", generated_at=_TS),
                tech_tree=TechTree(
                    nodes=[_tech_node(representative_paper_ids=["ghost"])],
                ),
                papers=[],
            )

    def test_paper_id_validator_catches_missing_ref_in_scholars(self):
        with pytest.raises(ValidationError, match="paper_id reference"):
            DynamicResearchLandscape(
                meta=LandscapeMeta(topic="T", generated_at=_TS),
                collaboration_network=CollaborationNetwork(
                    nodes=[_scholar(top_paper_ids=["ghost"])],
                ),
                papers=[],
            )

    def test_paper_id_validator_catches_missing_ref_in_gaps(self):
        with pytest.raises(ValidationError, match="paper_id reference"):
            DynamicResearchLandscape(
                meta=LandscapeMeta(topic="T", generated_at=_TS),
                research_gaps=ResearchGaps(
                    gaps=[_gap(evidence_paper_ids=["ghost"])],
                ),
                papers=[],
            )

    def test_paper_id_validator_catches_missing_ref_in_collab_edges(self):
        s1 = _scholar(scholar_id="s1")
        s2 = _scholar(scholar_id="s2", name="Bob")
        with pytest.raises(ValidationError, match="paper_id reference"):
            DynamicResearchLandscape(
                meta=LandscapeMeta(topic="T", generated_at=_TS),
                collaboration_network=CollaborationNetwork(
                    nodes=[s1, s2],
                    edges=[CollaborationEdge(source="s1", target="s2", shared_paper_ids=["ghost"])],
                ),
                papers=[],
            )

    def test_paper_ids_consistent(self):
        """Valid landscape passes validation — all paper_ids exist."""
        landscape = _full_landscape()
        paper_ids = {p.paper_id for p in landscape.papers}

        for node in landscape.tech_tree.nodes:
            for pid in node.representative_paper_ids:
                assert pid in paper_ids

        for scholar in landscape.collaboration_network.nodes:
            for pid in scholar.top_paper_ids:
                assert pid in paper_ids

        for gap in landscape.research_gaps.gaps:
            for pid in gap.evidence_paper_ids:
                assert pid in paper_ids


# ===================================================================
# LandscapeIncrement
# ===================================================================


class TestLandscapeIncrement:
    def test_defaults_to_empty(self):
        inc = LandscapeIncrement()
        assert inc.new_papers == []
        assert inc.new_tech_nodes == []
        assert inc.new_tech_edges == []
        assert inc.new_scholars == []
        assert inc.new_collab_edges == []
        assert inc.new_gaps == []
        assert inc.detected_at is None

    def test_populated_increment(self):
        ts = datetime(2024, 7, 1, 8, 0, 0, tzinfo=timezone.utc)
        inc = LandscapeIncrement(
            new_papers=[_paper("p2", "New Paper")],
            new_tech_nodes=[_tech_node(node_id="method_new", is_new=True)],
            new_tech_edges=[_tech_edge(source="method_new", target="method_new")],
            new_scholars=[_scholar(scholar_id="scholar_new", name="New Scholar", is_new=True)],
            new_collab_edges=[_collab_edge(source="scholar_new", target="scholar_new")],
            new_gaps=[_gap(gap_id="gap_2", title="New gap")],
            detected_at=ts,
        )
        assert len(inc.new_papers) == 1
        assert inc.new_tech_nodes[0].is_new is True
        assert inc.new_scholars[0].is_new is True
        assert inc.detected_at == ts

    def test_detected_at_accepts_iso_string(self):
        inc = LandscapeIncrement(detected_at="2024-07-01T08:00:00Z")
        assert isinstance(inc.detected_at, datetime)

    def test_detected_at_rejects_bad_format(self):
        with pytest.raises(ValidationError):
            LandscapeIncrement(detected_at="not-a-date")

    def test_json_round_trip(self):
        inc = LandscapeIncrement(
            new_papers=[_paper()],
            new_tech_nodes=[_tech_node(is_new=True)],
            detected_at=datetime(2024, 7, 1, 8, 0, 0, tzinfo=timezone.utc),
        )
        restored = LandscapeIncrement.model_validate_json(inc.model_dump_json())
        assert restored.new_papers[0].paper_id == "p1"
        assert restored.new_tech_nodes[0].is_new is True
        assert isinstance(restored.detected_at, datetime)
