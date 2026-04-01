"""Intermediate data models for the DRL Landscape pipeline.

These schemas are internal to the pipeline and NOT exposed to the API layer.
The final output uses the canonical models from ``src.models.landscape``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.models.landscape import (
    ResearchGaps,
    TechTree,
)
from src.models.paper import PaperResult, WebSearchResult


# ---------------------------------------------------------------------------
# Search Plan (migrated from the former exploration module)
# ---------------------------------------------------------------------------

class SearchPlan(BaseModel):
    """LLM-generated retrieval strategy produced by the Planner stage."""

    paper_keywords: list[str] = Field(
        ...,
        min_length=1,
        description="3-5 English academic keyword phrases for Semantic Scholar / arXiv.",
    )
    web_queries: list[str] = Field(
        ...,
        min_length=1,
        description="2-3 trend / review questions for web search (Tavily).",
    )
    focus_areas: list[str] = Field(
        ...,
        min_length=1,
        description="Research sub-directions to guide analysis.",
    )
    source_hints: list[str] = Field(
        default_factory=list,
        description=(
            "2-4 paper source identifiers most relevant to the topic, "
            "e.g. ['arxiv', 'pubmed', 'dblp']."
        ),
    )
    domain_tags: list[str] = Field(
        default_factory=list,
        description=(
            "1-2 domain labels classifying the topic, e.g. "
            "['biomedical', 'computer_science']."
        ),
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Planner's confidence in source_hints accuracy (0-1).",
    )


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
    research_gaps: ResearchGaps
