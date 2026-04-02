"""Pydantic data contracts for the Dynamic Research Landscape (动态研究全景图).

This module is the **single source of truth** for all structured output
produced by the DRL pipeline and its incremental-monitoring subsystem.
Front-end TypeScript interfaces in ``frontend/types/index.ts`` mirror these
models and must be kept in sync.

Sub-models are intentionally graph-oriented (nodes + edges) so that the
front-end can feed them directly into React Flow / ECharts / D3 without
any shape transformation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .paper import PaperResult

# ---------------------------------------------------------------------------
# 1. TechTree — 技术路线演进树
# ---------------------------------------------------------------------------


class TechTreeNode(BaseModel):
    """A node in the technology-evolution tree.

    Each node represents a method, technique, or milestone paper.
    ``representative_paper_ids`` link back to entries in
    ``DynamicResearchLandscape.papers`` for full traceability.
    """

    node_id: str = Field(..., description="Unique identifier used as the rendering key by the front-end.")
    label: str = Field(..., description="Display name (method name or short paper title).")
    node_type: Literal["method", "paper", "milestone", "unverified"] = Field(
        ..., description="Semantic category of the node. 'unverified' = degraded fallback."
    )
    year: int | None = Field(default=None, description="Publication or emergence year.")
    description: str = Field(..., description="1-2 sentence summary.")
    representative_paper_ids: list[str] = Field(
        default_factory=list,
        description="PaperResult.paper_id values associated with this node.",
    )
    is_new: bool = Field(
        default=False,
        description="Set to true when added by incremental monitoring.",
    )


class TechTreeEdge(BaseModel):
    """A directed edge between two TechTreeNode entries."""

    source: str = Field(..., description="node_id of the origin node.")
    target: str = Field(..., description="node_id of the destination node.")
    relation: Literal["evolves_from", "extends", "alternative_to", "inspires"] = Field(
        ..., description="Semantic relation type."
    )
    label: str = Field(default="", description="Optional human-readable edge label.")


class TechTree(BaseModel):
    """Technology-evolution tree for a research topic."""

    nodes: list[TechTreeNode] = Field(default_factory=list)
    edges: list[TechTreeEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_graph_integrity(self) -> TechTree:
        node_ids = {n.node_id for n in self.nodes}
        if len(node_ids) < len(self.nodes):
            dupes = len(self.nodes) - len(node_ids)
            raise ValueError(f"TechTree contains {dupes} duplicate node_id(s)")
        for edge in self.edges:
            if edge.source not in node_ids:
                raise ValueError(
                    f"TechTreeEdge.source '{edge.source}' references a non-existent node"
                )
            if edge.target not in node_ids:
                raise ValueError(
                    f"TechTreeEdge.target '{edge.target}' references a non-existent node"
                )
        return self


# ---------------------------------------------------------------------------
# 2. CollaborationNetwork — 学者合作网络图谱
# ---------------------------------------------------------------------------


class ScholarNode(BaseModel):
    """A node representing a researcher in the collaboration network."""

    scholar_id: str = Field(..., description="Unique identifier for the scholar.")
    name: str
    affiliations: list[str] = Field(
        default_factory=list,
        description="Institution(s) the scholar is affiliated with.",
    )
    paper_count: int = Field(default=0, description="Number of papers in the analysed corpus.")
    citation_count: int = Field(default=0, description="Total citations within the analysed corpus.")
    top_paper_ids: list[str] = Field(
        default_factory=list,
        description="PaperResult.paper_id values for representative works.",
    )
    is_new: bool = Field(
        default=False,
        description="Set to true when surfaced by incremental monitoring.",
    )


class CollaborationEdge(BaseModel):
    """An undirected co-authorship link between two scholars."""

    source: str = Field(..., description="scholar_id of one end.")
    target: str = Field(..., description="scholar_id of the other end.")
    weight: int = Field(default=1, ge=1, description="Number of co-authored papers.")
    shared_paper_ids: list[str] = Field(
        default_factory=list,
        description="PaperResult.paper_id values for co-authored papers.",
    )


class CollaborationNetwork(BaseModel):
    """Scholar collaboration network for a research topic."""

    nodes: list[ScholarNode] = Field(default_factory=list)
    edges: list[CollaborationEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_graph_integrity(self) -> CollaborationNetwork:
        scholar_ids = {n.scholar_id for n in self.nodes}
        if len(scholar_ids) < len(self.nodes):
            dupes = len(self.nodes) - len(scholar_ids)
            raise ValueError(
                f"CollaborationNetwork contains {dupes} duplicate scholar_id(s)"
            )
        for edge in self.edges:
            if edge.source not in scholar_ids:
                raise ValueError(
                    f"CollaborationEdge.source '{edge.source}' references a non-existent scholar"
                )
            if edge.target not in scholar_ids:
                raise ValueError(
                    f"CollaborationEdge.target '{edge.target}' references a non-existent scholar"
                )
        return self


# ---------------------------------------------------------------------------
# 3. ResearchGaps — 研究空白挖掘
# ---------------------------------------------------------------------------


class ResearchGap(BaseModel):
    """A single identified research gap / open problem."""

    gap_id: str = Field(..., description="Unique identifier for this gap.")
    title: str = Field(..., description="Concise gap title.")
    description: str = Field(..., description="Detailed description of the gap.")
    evidence_paper_ids: list[str] = Field(
        default_factory=list,
        description="PaperResult.paper_id values that support this assessment.",
    )
    potential_approaches: list[str] = Field(
        default_factory=list,
        description="Possible research directions to address the gap.",
    )
    impact: Literal["high", "medium", "low"] = Field(
        default="medium",
        description="Estimated impact level if this gap were addressed.",
    )


class ResearchGaps(BaseModel):
    """Collection of identified research gaps for a topic."""

    gaps: list[ResearchGap] = Field(default_factory=list)
    summary: str = Field(default="", description="High-level overview of the gap landscape.")


# ---------------------------------------------------------------------------
# 4. Envelope — DynamicResearchLandscape (顶层输出)
# ---------------------------------------------------------------------------


class LandscapeMeta(BaseModel):
    """Metadata for a DynamicResearchLandscape snapshot."""

    topic: str
    generated_at: datetime = Field(..., description="Timestamp of generation.")
    paper_count: int = Field(default=0, description="Total papers included in the analysis.")
    version: int = Field(default=1, ge=1, description="Monotonically increasing; bumped on incremental updates.")
    quality: Literal["complete", "degraded"] = Field(
        default="complete",
        description="'degraded' when pipeline encountered issues but produced usable output.",
    )


class DynamicResearchLandscape(BaseModel):
    """Top-level envelope — the single deliverable of the DRL pipeline.

    All sub-models reference papers by ``paper_id``; the full
    ``PaperResult`` objects live in the ``papers`` list to avoid
    duplication.
    """

    meta: LandscapeMeta
    tech_tree: TechTree = Field(default_factory=TechTree)
    collaboration_network: CollaborationNetwork = Field(default_factory=CollaborationNetwork)
    research_gaps: ResearchGaps = Field(default_factory=ResearchGaps)
    papers: list[PaperResult] = Field(
        default_factory=list,
        description="All referenced papers with full metadata (single source of truth).",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="Every cited URL / DOI for traceability.",
    )

    @model_validator(mode="after")
    def _check_paper_id_references(self) -> DynamicResearchLandscape:
        paper_ids = {p.paper_id for p in self.papers}
        missing: list[str] = []

        for node in self.tech_tree.nodes:
            for pid in node.representative_paper_ids:
                if pid not in paper_ids:
                    missing.append(f"TechTreeNode('{node.node_id}').representative_paper_ids: '{pid}'")

        for scholar in self.collaboration_network.nodes:
            for pid in scholar.top_paper_ids:
                if pid not in paper_ids:
                    missing.append(f"ScholarNode('{scholar.scholar_id}').top_paper_ids: '{pid}'")

        for edge in self.collaboration_network.edges:
            for pid in edge.shared_paper_ids:
                if pid not in paper_ids:
                    missing.append(f"CollaborationEdge('{edge.source}'->'{edge.target}').shared_paper_ids: '{pid}'")

        for gap in self.research_gaps.gaps:
            for pid in gap.evidence_paper_ids:
                if pid not in paper_ids:
                    missing.append(f"ResearchGap('{gap.gap_id}').evidence_paper_ids: '{pid}'")

        if missing:
            details = "; ".join(missing[:10])
            suffix = f" (and {len(missing) - 10} more)" if len(missing) > 10 else ""
            raise ValueError(
                f"paper_id reference(s) not found in papers list: {details}{suffix}"
            )
        return self


# ---------------------------------------------------------------------------
# 5. Incremental update — LandscapeIncrement (增量监控)
# ---------------------------------------------------------------------------


class LandscapeIncrement(BaseModel):
    """Delta produced by the incremental-monitoring subsystem.

    Describes *what is new* since the last snapshot so that a merge
    function can fold it into an existing ``DynamicResearchLandscape``.
    """

    new_papers: list[PaperResult] = Field(default_factory=list)
    new_tech_nodes: list[TechTreeNode] = Field(default_factory=list)
    new_tech_edges: list[TechTreeEdge] = Field(default_factory=list)
    new_scholars: list[ScholarNode] = Field(default_factory=list)
    new_collab_edges: list[CollaborationEdge] = Field(default_factory=list)
    new_gaps: list[ResearchGap] = Field(default_factory=list)
    detected_at: datetime | None = Field(default=None, description="Timestamp of detection.")
