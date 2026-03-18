"""Source Router: validate Planner hints and produce a bounded source list.

Pure Python logic — no LLM call, no I/O.  Sits between the Planner and
Retriever stages to ensure only relevant sources are queried.
"""

from __future__ import annotations

import logging
from typing import Any

from .schemas import RoutedSources, SearchPlan

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain → source mapping
# ---------------------------------------------------------------------------

DOMAIN_SOURCE_MAP: dict[str, list[str]] = {
    "biomedical": ["pubmed", "biorxiv", "medrxiv", "europepmc"],
    "computer_science": ["arxiv", "dblp"],
    "physics": ["arxiv"],
    "chemistry": ["crossref", "europepmc"],
    "social_science": ["crossref", "openalex", "doaj"],
    "multidisciplinary": ["crossref", "openalex"],
}

FALLBACK_SOURCES: list[str] = ["crossref", "openalex"]
# Used when routing is disabled (safe-mode degradation).
# Keep this list small and broadly useful to avoid context explosion.
DEGRADED_UNIVERSAL_SOURCES: list[str] = ["crossref", "openalex", "arxiv"]
DEGRADED_MIN_SOURCES = 2
DEGRADED_MAX_SOURCES = 3


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_domain_sources(
    domain_tags: list[str],
    registry: dict[str, Any],
) -> list[str]:
    """Merge sources for all *domain_tags*, preserving insertion order and
    filtering against the live *registry*."""
    seen: set[str] = set()
    result: list[str] = []
    for tag in domain_tags:
        for src in DOMAIN_SOURCE_MAP.get(tag, []):
            if src not in seen and src in registry:
                seen.add(src)
                result.append(src)
    return result


def _compute_secondary(
    primary: list[str],
    domain_tags: list[str],
    registry: dict[str, Any],
) -> list[str]:
    """Return domain-adjacent sources that are *not* already in *primary*."""
    primary_set = set(primary)
    candidates = _resolve_domain_sources(domain_tags, registry)
    secondary = [s for s in candidates if s not in primary_set]
    if not secondary:
        secondary = [s for s in FALLBACK_SOURCES if s not in primary_set and s in registry]
    return secondary


def _bounded_degraded_sources(
    candidates: list[str],
    registry: dict[str, Any],
) -> list[str]:
    """Return a bounded degraded source list (2-3 universal sources).

    Guarantees a small allow-list for safe-mode retrieval to control token growth.
    """
    seen: set[str] = set()
    primary = [s for s in candidates if s in registry and not (s in seen or seen.add(s))]
    primary = primary[:DEGRADED_MAX_SOURCES]

    if len(primary) < DEGRADED_MIN_SOURCES:
        for src in DEGRADED_UNIVERSAL_SOURCES:
            if src in registry and src not in primary:
                primary.append(src)
            if len(primary) >= DEGRADED_MIN_SOURCES:
                break

    return primary[:DEGRADED_MAX_SOURCES]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def route_sources(
    plan: SearchPlan,
    *,
    registry: dict[str, Any],
    enabled: bool = True,
    confidence_threshold: float = 0.6,
    max_sources: int = 3,
    default_sources: list[str] | None = None,
) -> RoutedSources:
    """Decide which paper sources the Retriever should query.

    Parameters
    ----------
    plan:
        The ``SearchPlan`` produced by the Planner (contains *source_hints*,
        *domain_tags* and *confidence*).
    registry:
        Live ``SOURCE_REGISTRY`` — only keys present here are considered valid.
    enabled:
        Master switch.  When ``False`` the router returns *default_sources*
        unchanged (backward-compatible safe mode).
    confidence_threshold:
        Minimum ``plan.confidence`` required to trust ``source_hints``.
    max_sources:
        Hard cap on the number of primary sources.
    default_sources:
        Optional degraded source preference when routing is disabled.
        The router still enforces a strict 2-3 source cap in this path.
    """
    if default_sources is None:
        default_sources = list(DEGRADED_UNIVERSAL_SOURCES)

    if not enabled:
        degraded = _bounded_degraded_sources(default_sources, registry)
        return RoutedSources(
            primary=degraded,
            reason=(
                "source routing disabled; using bounded degraded universal sources "
                f"(2-3 max): {degraded}"
            ),
        )

    primary: list[str]
    reason: str

    if plan.confidence >= confidence_threshold and plan.source_hints:
        valid = [s for s in plan.source_hints if s in registry]
        domain_set = set(_resolve_domain_sources(plan.domain_tags, registry))
        valid.sort(key=lambda s: s not in domain_set)
        primary = valid[:max_sources]
        reason = (
            f"high confidence ({plan.confidence:.2f}); "
            f"accepted hints {valid} (domain-sorted, capped to {max_sources})"
        )
    else:
        primary = _resolve_domain_sources(plan.domain_tags, registry)[:max_sources]
        reason = (
            f"low confidence ({plan.confidence:.2f}) or empty hints; "
            f"resolved from domain_tags {plan.domain_tags}"
        )

    if not primary:
        primary = _resolve_domain_sources(plan.domain_tags, registry)[:max_sources]
        if primary:
            reason += "; hints invalid, resolved from domain_tags"

    if not primary:
        primary = _bounded_degraded_sources(FALLBACK_SOURCES, registry)
        if primary:
            reason += "; fell back to FALLBACK_SOURCES"

    secondary = _compute_secondary(primary, plan.domain_tags, registry)

    logger.info(
        "route_sources  primary=%s  secondary=%s  reason=%s",
        primary, secondary, reason,
    )
    return RoutedSources(primary=primary, secondary=secondary, reason=reason)
