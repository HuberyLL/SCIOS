"""Intermediate data models for the DRL Landscape pipeline.

These schemas are internal to the pipeline and NOT exposed to the API layer.
The final output uses the canonical models from ``src.models.landscape``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.models.paper import PaperResult


# ---------------------------------------------------------------------------
# Scope Agent outputs
# ---------------------------------------------------------------------------

class SeedPaper(BaseModel):
    """A foundational paper that the Scope Agent identifies via LLM world knowledge."""

    title: str = Field(..., description="Exact or near-exact paper title for S2 lookup.")
    expected_authors: list[str] = Field(
        default_factory=list,
        description="Key author names to help disambiguate search results.",
    )
    expected_year: int | None = Field(
        default=None,
        description="Expected publication year.",
    )
    reason: str = Field(
        ...,
        description="Why this paper is foundational to the field.",
    )


class SubField(BaseModel):
    """A distinct research sub-direction within the user's topic."""

    name: str = Field(..., description="Short, descriptive sub-field name.")
    description: str = Field(..., description="Brief description of this sub-field.")
    keywords: list[str] = Field(
        ..., min_length=1,
        description="Academic keyword phrases for targeted S2 search.",
    )


class SearchStrategy(BaseModel):
    """A single search phase within the retrieval plan."""

    phase: Literal["foundational", "evolution", "frontier"] = Field(
        ..., description="Which stage of field evolution this targets.",
    )
    queries: list[str] = Field(
        ..., min_length=1,
        description="Search queries for this phase.",
    )
    year_range: str | None = Field(
        default=None,
        description="S2-compatible year filter, e.g. '2017-2020'.",
    )
    min_citation_count: int | None = Field(
        default=None,
        description="Minimum citation count filter.",
    )


class ScopeDefinition(BaseModel):
    """Complete output of the Scope Agent — defines *what* to retrieve."""

    topic: str = Field(..., description="The user's original topic.")
    topic_description: str = Field(
        default="",
        description="Expert-level description of the field.",
    )
    estimated_complexity: Literal["narrow", "medium", "broad"] = Field(
        default="medium",
        description=(
            "How broad the field is. Downstream agents use this to set "
            "adaptive budget envelopes (concurrency, API call limits)."
        ),
    )
    seed_papers: list[SeedPaper] = Field(
        ..., min_length=1,
        description="Foundational / seminal papers. Scale to topic breadth.",
    )
    sub_fields: list[SubField] = Field(
        ..., min_length=1,
        description="Major sub-directions of the field. Scale to topic breadth.",
    )
    deprioritized_sub_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Sub-field names deliberately omitted to keep scope manageable "
            "for exceptionally broad topics. Empty for narrow/medium topics."
        ),
    )
    time_range_start: int = Field(..., description="Start year of the field, e.g. 2017.")
    time_range_end: int = Field(..., description="End year (inclusive), e.g. 2026.")
    search_strategies: list[SearchStrategy] = Field(
        ..., min_length=1,
        description="Phased retrieval strategies (foundational / evolution / frontier).",
    )
    source_hints: list[str] = Field(
        default_factory=list,
        description="Preferred data source IDs, e.g. ['arxiv', 'dblp'].",
    )
    domain_tags: list[str] = Field(
        default_factory=list,
        description="Domain labels, e.g. ['computer_science'].",
    )


# ---------------------------------------------------------------------------
# Retrieval Agent outputs
# ---------------------------------------------------------------------------

class CorpusStats(BaseModel):
    """Summary statistics for the retrieved paper corpus."""

    total_papers: int = Field(default=0)
    seed_papers_found: int = Field(default=0)
    seed_papers_expected: int = Field(default=0)
    year_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="Year (as string key) -> paper count.",
    )
    sub_field_coverage: dict[str, int] = Field(
        default_factory=dict,
        description="Sub-field name -> paper count.",
    )
    quality_flags: list[str] = Field(
        default_factory=list,
        description=(
            "Machine-readable quality signals set by agents during execution. "
            "E.g. 'low_seed_coverage', 'small_corpus', 'supplement_failed'."
        ),
    )


class PaperCorpus(BaseModel):
    """The full paper corpus built by the Retrieval Agent."""

    papers: list[PaperResult] = Field(default_factory=list)
    seed_paper_map: dict[str, str] = Field(
        default_factory=dict,
        description="seed_title -> paper_id for each successfully anchored seed.",
    )
    citation_graph: dict[str, list[str]] = Field(
        default_factory=dict,
        description="paper_id -> [paper_ids it cites] (directed).",
    )
    reference_graph: dict[str, list[str]] = Field(
        default_factory=dict,
        description="paper_id -> [paper_ids that cite it] (reverse direction).",
    )
    sub_field_mapping: dict[str, list[str]] = Field(
        default_factory=dict,
        description="sub_field name -> [paper_ids assigned to it].",
    )
    author_paper_count: dict[str, int] = Field(
        default_factory=dict,
        description="author_id -> paper count in corpus (for Network Agent).",
    )
    stats: CorpusStats = Field(default_factory=CorpusStats)

    @property
    def seed_paper_ids(self) -> list[str]:
        """Backward-compatible accessor: list of anchored seed paper_ids."""
        return list(self.seed_paper_map.values())


# ---------------------------------------------------------------------------
# Critic Agent outputs
# ---------------------------------------------------------------------------

class QualityIssue(BaseModel):
    """A single quality concern identified by the Critic Agent."""

    category: str = Field(
        ...,
        description="Issue category: seed_coverage | subfield_coverage | "
        "time_continuity | network_size | data_consistency",
    )
    severity: Literal["critical", "warning", "info"] = Field(...)
    description: str = Field(...)


class QualityReport(BaseModel):
    """Critic Agent output — determines whether the pipeline can proceed."""

    passed: bool = Field(..., description="True if quality is acceptable.")
    issues: list[QualityIssue] = Field(default_factory=list)
    retry_targets: list[str] = Field(
        default_factory=list,
        description="Agent names to re-run if not passed, e.g. ['retrieval', 'taxonomy'].",
    )
    scores: dict[str, float] = Field(
        default_factory=dict,
        description="Dimension -> 0-1 score, e.g. {'seed_coverage': 0.8}.",
    )


# ---------------------------------------------------------------------------
# S2 Author profile (used by Network Agent)
# ---------------------------------------------------------------------------

class AuthorProfile(BaseModel):
    """Author details fetched from the S2 Author API."""

    author_id: str
    name: str
    affiliations: list[str] = Field(default_factory=list)
    paper_count: int = Field(default=0)
    citation_count: int = Field(default=0)
    h_index: int = Field(default=0)
