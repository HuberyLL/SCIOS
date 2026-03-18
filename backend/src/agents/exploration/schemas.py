"""Pydantic data contracts for every stage of the Exploration pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..tools._schemas import PaperResult, SearchResult, WebSearchResult


# ---------------------------------------------------------------------------
# Stage 1  –  Planner output
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
        description="Research sub-directions to guide the Synthesizer.",
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


# ---------------------------------------------------------------------------
# Stage 1.5  –  Router output
# ---------------------------------------------------------------------------

class RoutedSources(BaseModel):
    """Validated source list produced by the Router between Planner and Retriever."""

    primary: list[str] = Field(
        default_factory=list,
        description="Sources to query in Stage A.",
    )
    secondary: list[str] = Field(
        default_factory=list,
        description="Extra sources queried in Stage B when Stage A yields too few papers.",
    )
    reason: str = Field(
        default="",
        description="Human-readable explanation of the routing decision.",
    )


# ---------------------------------------------------------------------------
# Stage 2  –  Retriever output (pure data, no LLM involved)
# ---------------------------------------------------------------------------

class RawRetrievedData(BaseModel):
    """Aggregated raw data returned by the Retriever stage."""

    s2_results: list[SearchResult] = Field(default_factory=list)
    paper_results: list[SearchResult] = Field(default_factory=list)
    web_results: list[WebSearchResult] = Field(default_factory=list)
    citation_map: dict[str, list[PaperResult]] = Field(
        default_factory=dict,
        description="paper_id → list of citing papers (top-N high-citation papers only).",
    )


# ---------------------------------------------------------------------------
# Stage 3  –  Synthesizer output  (final product)
# ---------------------------------------------------------------------------

class CoreConcept(BaseModel):
    term: str
    explanation: str


class ScholarProfile(BaseModel):
    name: str
    affiliation: str
    representative_works: list[str]
    contribution_summary: str


class RecommendedPaper(BaseModel):
    title: str
    authors: list[str]
    year: int
    venue: str = ""
    citation_count: int = 0
    summary: str
    url: str


class TrendsAndChallenges(BaseModel):
    recent_progress: str
    emerging_trends: list[str]
    open_challenges: list[str]
    future_directions: str


class ExplorationReport(BaseModel):
    """Final structured report — the single deliverable of the Exploration pipeline.

    Maps directly to the graduation-project requirements:
    Topic, CoreConcepts, KeyScholars, MustReadPapers, TrendsAndChallenges.
    """

    topic: str
    core_concepts: list[CoreConcept]
    key_scholars: list[ScholarProfile]
    must_read_papers: list[RecommendedPaper]
    trends_and_challenges: TrendsAndChallenges
    sources: list[str] = Field(
        default_factory=list,
        description="All cited URLs / DOIs for traceability.",
    )
