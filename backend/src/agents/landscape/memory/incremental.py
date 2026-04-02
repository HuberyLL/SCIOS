"""Layer 4: Incremental update engine.

Computes the delta between two ``DynamicResearchLandscape`` snapshots and
merges it into the existing landscape, bumping the version number.  Also
provides ``detect_new_papers`` to find papers published since the last run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.agents.tools.s2_client import SemanticScholarClient
from src.models.landscape import (
    CollaborationEdge,
    CollaborationNetwork,
    DynamicResearchLandscape,
    LandscapeIncrement,
    LandscapeMeta,
    ResearchGap,
    ResearchGaps,
    ScholarNode,
    TechTree,
    TechTreeEdge,
    TechTreeNode,
)
from src.models.paper import PaperResult

from ..schemas import ScopeDefinition

logger = logging.getLogger(__name__)


def compute_increment(
    old: DynamicResearchLandscape,
    new: DynamicResearchLandscape,
) -> LandscapeIncrement:
    """Diff *old* and *new* to produce a ``LandscapeIncrement``."""
    old_pids = {p.paper_id for p in old.papers}
    old_nids = {n.node_id for n in old.tech_tree.nodes}
    old_edge_keys = {(e.source, e.target) for e in old.tech_tree.edges}
    old_sids = {s.scholar_id for s in old.collaboration_network.nodes}
    old_collab_keys = {(e.source, e.target) for e in old.collaboration_network.edges}
    old_gids = {g.gap_id for g in old.research_gaps.gaps}

    new_papers = [p for p in new.papers if p.paper_id not in old_pids]
    new_tech_nodes = [n for n in new.tech_tree.nodes if n.node_id not in old_nids]
    new_tech_edges = [
        e for e in new.tech_tree.edges if (e.source, e.target) not in old_edge_keys
    ]
    new_scholars = [
        s for s in new.collaboration_network.nodes if s.scholar_id not in old_sids
    ]
    new_collab_edges = [
        e for e in new.collaboration_network.edges
        if (e.source, e.target) not in old_collab_keys
    ]
    new_gaps = [g for g in new.research_gaps.gaps if g.gap_id not in old_gids]

    return LandscapeIncrement(
        new_papers=new_papers,
        new_tech_nodes=new_tech_nodes,
        new_tech_edges=new_tech_edges,
        new_scholars=new_scholars,
        new_collab_edges=new_collab_edges,
        new_gaps=new_gaps,
        detected_at=datetime.now(timezone.utc),
    )


def merge_increment(
    existing: DynamicResearchLandscape,
    increment: LandscapeIncrement,
) -> DynamicResearchLandscape:
    """Fold *increment* into *existing*, returning a new landscape with bumped version."""
    if increment.is_empty:
        return existing

    for node in increment.new_tech_nodes:
        node.is_new = True
    for scholar in increment.new_scholars:
        scholar.is_new = True

    merged_papers = list(existing.papers) + list(increment.new_papers)
    merged_tech_nodes = list(existing.tech_tree.nodes) + list(increment.new_tech_nodes)
    merged_tech_edges = list(existing.tech_tree.edges) + list(increment.new_tech_edges)
    merged_scholars = list(existing.collaboration_network.nodes) + list(increment.new_scholars)
    merged_collab_edges = list(existing.collaboration_network.edges) + list(increment.new_collab_edges)
    merged_gaps = list(existing.research_gaps.gaps) + list(increment.new_gaps)

    valid_pids = {p.paper_id for p in merged_papers}
    valid_nids = {n.node_id for n in merged_tech_nodes}
    valid_sids = {s.scholar_id for s in merged_scholars}

    clean_tech_edges = [
        e for e in merged_tech_edges
        if e.source in valid_nids and e.target in valid_nids
    ]
    clean_collab_edges = [
        e for e in merged_collab_edges
        if e.source in valid_sids and e.target in valid_sids
    ]

    new_version = existing.meta.version + 1

    sources = list(existing.sources)
    seen = set(existing.sources)
    for p in increment.new_papers:
        if p.url and p.url not in seen:
            seen.add(p.url)
            sources.append(p.url)
        if p.doi and p.doi not in seen:
            seen.add(p.doi)
            sources.append(p.doi)

    meta = LandscapeMeta(
        topic=existing.meta.topic,
        generated_at=datetime.now(timezone.utc),
        paper_count=len(merged_papers),
        version=new_version,
        quality=existing.meta.quality,
    )

    return DynamicResearchLandscape(
        meta=meta,
        tech_tree=TechTree(nodes=merged_tech_nodes, edges=clean_tech_edges),
        collaboration_network=CollaborationNetwork(
            nodes=merged_scholars, edges=clean_collab_edges,
        ),
        research_gaps=ResearchGaps(gaps=merged_gaps, summary=existing.research_gaps.summary),
        papers=merged_papers,
        sources=sources,
    )


async def detect_new_papers(
    scope: ScopeDefinition,
    existing_paper_ids: set[str],
) -> list[PaperResult]:
    """Query S2 using the scope's search strategies and return only papers not in *existing_paper_ids*."""
    client = SemanticScholarClient()
    new_papers: list[PaperResult] = []
    seen: set[str] = set(existing_paper_ids)

    for strategy in scope.search_strategies:
        for query in strategy.queries:
            result = await client.search_papers(
                query,
                limit=20,
                year=strategy.year_range,
                min_citation_count=strategy.min_citation_count,
            )
            for paper in result.papers:
                if paper.paper_id and paper.paper_id not in seen:
                    seen.add(paper.paper_id)
                    new_papers.append(paper)

    logger.info("detect_new_papers: found %d new papers", len(new_papers))
    return new_papers
