"""Shared Pydantic models for academic paper and web-search results.

These are the canonical definitions — the single source of truth.
The legacy path ``src.agents.tools._schemas`` re-exports from here
for backward compatibility.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Paper-related schemas
# ---------------------------------------------------------------------------

class PaperResult(BaseModel):
    """Unified representation of a single academic paper across all sources."""

    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    author_ids: list[str] = Field(
        default_factory=list,
        description="S2 authorId for each author (parallel to 'authors'). "
        "Empty string if unknown.",
    )
    abstract: str = ""
    doi: str = ""
    published_date: str = ""
    pdf_url: str = ""
    url: str = ""
    source: str = ""
    categories: list[str] = Field(default_factory=list)
    citation_count: int = 0
    influential_citation_count: int = 0
    reference_count: int = 0
    venue: str = ""
    venue_type: str = ""
    fields_of_study: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    """Wrapper for a batch of paper search results."""

    query: str
    total: int = 0
    papers: list[PaperResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Web-search schemas
# ---------------------------------------------------------------------------

class WebSearchItem(BaseModel):
    """A single web-search hit returned by Tavily."""

    title: str
    url: str
    content: str
    score: float = 0.0


class WebSearchResult(BaseModel):
    """Wrapper for a batch of web-search results."""

    query: str
    results: list[WebSearchItem] = Field(default_factory=list)
