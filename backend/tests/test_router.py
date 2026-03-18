"""Unit tests for the source Router (exploration/router.py).

All tests are pure-Python — no I/O, no LLM, no mocking of external services.
"""

from __future__ import annotations

import pytest

from src.agents.exploration.router import (
    DOMAIN_SOURCE_MAP,
    FALLBACK_SOURCES,
    route_sources,
)
from src.agents.exploration.schemas import RoutedSources, SearchPlan

FAKE_REGISTRY: dict[str, object] = {
    "arxiv": object(),
    "pubmed": object(),
    "biorxiv": object(),
    "medrxiv": object(),
    "crossref": object(),
    "openalex": object(),
    "pmc": object(),
    "europepmc": object(),
    "core": object(),
    "dblp": object(),
    "doaj": object(),
}


def _plan(
    *,
    hints: list[str] | None = None,
    domains: list[str] | None = None,
    confidence: float = 0.8,
) -> SearchPlan:
    return SearchPlan(
        paper_keywords=["test keyword"],
        web_queries=["test query"],
        focus_areas=["test area"],
        source_hints=hints or [],
        domain_tags=domains or [],
        confidence=confidence,
    )


# ===================================================================
# High-confidence path
# ===================================================================

class TestHighConfidence:

    def test_uses_hints(self):
        plan = _plan(hints=["arxiv", "dblp"], confidence=0.8)
        routed = route_sources(plan, registry=FAKE_REGISTRY)
        assert routed.primary == ["arxiv", "dblp"]

    def test_filters_invalid_hints(self):
        plan = _plan(hints=["nonexistent", "arxiv", "fake"], confidence=0.9)
        routed = route_sources(plan, registry=FAKE_REGISTRY)
        assert routed.primary == ["arxiv"]

    def test_max_sources_cap(self):
        plan = _plan(
            hints=["arxiv", "pubmed", "dblp", "crossref", "openalex", "core"],
            confidence=0.9,
        )
        routed = route_sources(plan, registry=FAKE_REGISTRY, max_sources=3)
        assert len(routed.primary) == 3
        assert routed.primary == ["arxiv", "pubmed", "dblp"]

    def test_exact_threshold_is_accepted(self):
        plan = _plan(hints=["pubmed"], confidence=0.6)
        routed = route_sources(plan, registry=FAKE_REGISTRY, confidence_threshold=0.6)
        assert routed.primary == ["pubmed"]

    def test_domain_aware_sorting(self):
        """Domain-matching sources should be prioritised over out-of-domain ones."""
        plan = _plan(
            hints=["doaj", "crossref", "pubmed", "biorxiv"],
            domains=["biomedical"],
            confidence=0.9,
        )
        routed = route_sources(plan, registry=FAKE_REGISTRY, max_sources=3)
        bio_sources = set(DOMAIN_SOURCE_MAP["biomedical"])
        assert routed.primary[0] in bio_sources
        assert routed.primary[1] in bio_sources


# ===================================================================
# Low-confidence / fallback path
# ===================================================================

class TestLowConfidence:

    def test_falls_back_to_domain(self):
        plan = _plan(hints=["arxiv"], domains=["biomedical"], confidence=0.3)
        routed = route_sources(plan, registry=FAKE_REGISTRY)
        expected = [s for s in DOMAIN_SOURCE_MAP["biomedical"] if s in FAKE_REGISTRY][:3]
        assert routed.primary == expected

    def test_multiple_domains_merged(self):
        plan = _plan(domains=["computer_science", "physics"], confidence=0.2)
        routed = route_sources(plan, registry=FAKE_REGISTRY)
        assert "arxiv" in routed.primary
        assert "dblp" in routed.primary

    def test_empty_hints_and_no_domains_uses_fallback(self):
        plan = _plan(hints=[], domains=[], confidence=0.1)
        routed = route_sources(plan, registry=FAKE_REGISTRY)
        assert routed.primary == [s for s in FALLBACK_SOURCES if s in FAKE_REGISTRY]

    def test_below_threshold_ignores_hints(self):
        plan = _plan(hints=["dblp"], domains=["biomedical"], confidence=0.5)
        routed = route_sources(plan, registry=FAKE_REGISTRY, confidence_threshold=0.6)
        assert "dblp" not in routed.primary
        assert "pubmed" in routed.primary


# ===================================================================
# Disabled routing
# ===================================================================

class TestRoutingDisabled:

    def test_returns_default_sources(self):
        plan = _plan(hints=["arxiv", "dblp"], confidence=0.9)
        defaults = ["arxiv", "pubmed", "biorxiv"]
        routed = route_sources(
            plan, registry=FAKE_REGISTRY, enabled=False, default_sources=defaults,
        )
        assert routed.primary == defaults
        assert routed.secondary == []
        assert "disabled" in routed.reason.lower()

    def test_disabled_path_caps_sources_to_three(self):
        plan = _plan(hints=["arxiv"], confidence=0.9)
        defaults = ["arxiv", "pubmed", "biorxiv", "crossref", "openalex"]
        routed = route_sources(
            plan, registry=FAKE_REGISTRY, enabled=False, default_sources=defaults,
        )
        assert 2 <= len(routed.primary) <= 3
        assert routed.primary == ["arxiv", "pubmed", "biorxiv"]


# ===================================================================
# Secondary sources
# ===================================================================

class TestSecondary:

    def test_secondary_excludes_primary(self):
        plan = _plan(hints=["pubmed"], domains=["biomedical"], confidence=0.8)
        routed = route_sources(plan, registry=FAKE_REGISTRY)
        assert "pubmed" not in routed.secondary
        for s in routed.secondary:
            assert s not in routed.primary

    def test_secondary_drawn_from_domain(self):
        plan = _plan(hints=["pubmed"], domains=["biomedical"], confidence=0.8)
        routed = route_sources(plan, registry=FAKE_REGISTRY)
        bio_sources = set(DOMAIN_SOURCE_MAP["biomedical"])
        for s in routed.secondary:
            assert s in bio_sources


# ===================================================================
# Edge cases
# ===================================================================

class TestEdgeCases:

    def test_all_hints_invalid_falls_to_domain(self):
        plan = _plan(hints=["fake1", "fake2"], domains=["computer_science"], confidence=0.9)
        routed = route_sources(plan, registry=FAKE_REGISTRY)
        cs_sources = set(DOMAIN_SOURCE_MAP["computer_science"])
        assert all(s in cs_sources for s in routed.primary)
        assert len(routed.primary) > 0

    def test_empty_registry_returns_empty_primary(self):
        plan = _plan(hints=["arxiv"], confidence=0.9)
        routed = route_sources(plan, registry={})
        assert routed.primary == []

    def test_return_type(self):
        plan = _plan(hints=["arxiv"], confidence=0.8)
        routed = route_sources(plan, registry=FAKE_REGISTRY)
        assert isinstance(routed, RoutedSources)
        assert isinstance(routed.primary, list)
        assert isinstance(routed.secondary, list)
        assert isinstance(routed.reason, str)
