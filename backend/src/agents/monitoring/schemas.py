"""Pydantic data contracts for the Monitoring pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HotPaper(BaseModel):
    """A single noteworthy paper surfaced by the monitoring scan."""

    title: str
    authors: list[str] = Field(default_factory=list)
    year: int = 0
    url: str = ""
    citation_count: int = 0
    relevance_reason: str = ""


class DailyBrief(BaseModel):
    """Structured output produced by the monitoring pipeline for one topic."""

    topic: str
    since_date: str
    new_hot_papers: list[HotPaper] = Field(default_factory=list)
    trend_summary: str = ""
    sources: list[str] = Field(default_factory=list)
