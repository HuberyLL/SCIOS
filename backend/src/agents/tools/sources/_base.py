"""Abstract base class and shared rate-limiting infrastructure for all paper sources."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

from .._http import RateLimiter
from .._schemas import PaperResult

# Per-source rate limits: (max_requests_per_period, period_seconds)
# PubMed and PMC share NCBI E-utilities (3 req/s without API key), so they
# map to a single "ncbi" limiter to avoid exceeding the combined quota.
SOURCE_RATE_RULES: dict[str, tuple[int, float]] = {
    "ncbi":      (2, 1.0),
    "arxiv":     (3, 1.0),
    "biorxiv":   (5, 1.0),
    "medrxiv":   (5, 1.0),
    "crossref":  (10, 1.0),
    "openalex":  (10, 1.0),
    "europepmc": (5, 1.0),
    "core":      (5, 1.0),
    "dblp":      (3, 1.0),
    "doaj":      (3, 1.0),
}

_NCBI_SOURCES: frozenset[str] = frozenset({"pubmed", "pmc"})

_limiters: dict[str, RateLimiter] = {}


def get_source_limiter(source_name: str) -> RateLimiter:
    """Return a singleton ``RateLimiter`` for *source_name*.

    NCBI sources (pubmed, pmc) share a single limiter instance so that
    the combined request rate to ``eutils.ncbi.nlm.nih.gov`` stays within
    the NCBI rate policy.
    """
    key = "ncbi" if source_name in _NCBI_SOURCES else source_name
    if key not in _limiters:
        rate = SOURCE_RATE_RULES.get(key, (10, 1.0))
        _limiters[key] = RateLimiter(rules={"*": rate})
    return _limiters[key]


class BasePaperFetcher(ABC):
    """Contract that every paper source must satisfy."""

    source_name: str = ""

    @abstractmethod
    async def search(self, query: str, *, max_results: int = 10) -> list[PaperResult]:
        ...

    @abstractmethod
    async def fetch_full_text(self, paper: PaperResult) -> str:
        """Return extracted full text.  On failure, return the abstract."""
        ...


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

_NORM_RE = re.compile(r"[^a-z0-9 ]")


def normalize_title(title: str) -> str:
    """Lower-case, strip punctuation/extra whitespace for dedup matching."""
    return _NORM_RE.sub("", title.lower()).strip()


def extract_year(date_str: str) -> str:
    """Best-effort year extraction from a date string."""
    if not date_str:
        return ""
    m = re.search(r"\d{4}", date_str)
    return m.group(0) if m else ""
