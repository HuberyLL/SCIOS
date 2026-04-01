"""Intermediate data models for the DRL Landscape pipeline.

These schemas are internal to the pipeline and NOT exposed to the API layer.
The final output uses the canonical models from ``src.models.landscape``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.models.landscape import (
    ComparisonMatrix,
    ResearchGaps,
    TechTree,
)
from src.models.paper import PaperResult, WebSearchResult


class S2AuthorDetail(BaseModel):
    """Structured author info extracted from the Semantic Scholar API."""

    author_id: str
    name: str
    affiliations: list[str] = Field(default_factory=list)


class EnrichedPaper(BaseModel):
    """A paper together with its enriched author details from S2."""

    paper: PaperResult
    author_details: list[S2AuthorDetail] = Field(default_factory=list)


class EnrichedRetrievedData(BaseModel):
    """Full output of the enriched retriever stage."""

    enriched_papers: list[EnrichedPaper] = Field(default_factory=list)
    web_results: list[WebSearchResult] = Field(default_factory=list)
    citation_map: dict[str, list[PaperResult]] = Field(default_factory=dict)
    reference_map: dict[str, list[PaperResult]] = Field(default_factory=dict)


class LandscapeAnalysis(BaseModel):
    """LLM Analyzer intermediate output (excludes CollaborationNetwork).

    CollaborationNetwork is built from data, not by the LLM.
    ``papers`` and ``sources`` are filled by the Assembler.
    """

    tech_tree: TechTree
    comparison_matrix: ComparisonMatrix
    research_gaps: ResearchGaps
