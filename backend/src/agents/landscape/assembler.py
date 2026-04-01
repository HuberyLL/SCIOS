"""Assembler: merge pipeline outputs into a DynamicResearchLandscape.

Pure Python — no LLM, no I/O.  Performs reference sanitisation so that
the model_validator on ``DynamicResearchLandscape`` does not reject
paper_id references fabricated or mis-typed by the LLM.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone

from src.models.landscape import (
    CollaborationNetwork,
    DynamicResearchLandscape,
    LandscapeMeta,
)
from src.models.paper import PaperResult

from .schemas import EnrichedRetrievedData, LandscapeAnalysis

logger = logging.getLogger(__name__)


def _sanitise_ids(ids: list[str], valid: set[str], context: str) -> list[str]:
    """Return only ids that exist in *valid*; log removed ones."""
    clean: list[str] = []
    for pid in ids:
        if pid in valid:
            clean.append(pid)
        else:
            logger.warning("Removed invalid paper_id '%s' from %s", pid, context)
    return clean


def assemble_landscape(
    *,
    topic: str,
    analysis: LandscapeAnalysis,
    collaboration_network: CollaborationNetwork,
    enriched_data: EnrichedRetrievedData,
) -> DynamicResearchLandscape:
    """Combine all pipeline outputs into the final ``DynamicResearchLandscape``.

    Key responsibility: **reference sanitisation** — any ``paper_id``
    produced by the LLM that does not appear in the actual papers list is
    silently removed so ``DynamicResearchLandscape.model_validator`` passes.
    """
    papers: list[PaperResult] = [ep.paper for ep in enriched_data.enriched_papers]
    valid_ids = {p.paper_id for p in papers}

    sources: list[str] = []
    seen_sources: set[str] = set()
    for p in papers:
        if p.url and p.url not in seen_sources:
            seen_sources.add(p.url)
            sources.append(p.url)
        if p.doi and p.doi not in seen_sources:
            seen_sources.add(p.doi)
            sources.append(p.doi)
    for wr in enriched_data.web_results:
        for item in wr.results:
            if item.url and item.url not in seen_sources:
                seen_sources.add(item.url)
                sources.append(item.url)

    # Deep-copy LLM outputs to avoid mutating the originals
    tech_tree = copy.deepcopy(analysis.tech_tree)
    research_gaps = copy.deepcopy(analysis.research_gaps)
    collab = copy.deepcopy(collaboration_network)

    # --- Sanitise TechTree ---
    for node in tech_tree.nodes:
        node.representative_paper_ids = _sanitise_ids(
            node.representative_paper_ids,
            valid_ids,
            f"TechTreeNode('{node.node_id}').representative_paper_ids",
        )

    # --- Sanitise ResearchGaps ---
    for gap in research_gaps.gaps:
        gap.evidence_paper_ids = _sanitise_ids(
            gap.evidence_paper_ids,
            valid_ids,
            f"ResearchGap('{gap.gap_id}').evidence_paper_ids",
        )

    # --- Sanitise CollaborationNetwork ---
    for scholar in collab.nodes:
        scholar.top_paper_ids = _sanitise_ids(
            scholar.top_paper_ids,
            valid_ids,
            f"ScholarNode('{scholar.scholar_id}').top_paper_ids",
        )
    for edge in collab.edges:
        edge.shared_paper_ids = _sanitise_ids(
            edge.shared_paper_ids,
            valid_ids,
            f"CollaborationEdge('{edge.source}'->'{edge.target}').shared_paper_ids",
        )

    meta = LandscapeMeta(
        topic=topic,
        generated_at=datetime.now(timezone.utc),
        paper_count=len(papers),
        version=1,
    )

    landscape = DynamicResearchLandscape(
        meta=meta,
        tech_tree=tech_tree,
        collaboration_network=collab,
        research_gaps=research_gaps,
        papers=papers,
        sources=sources,
    )

    logger.info(
        "Assembled DynamicResearchLandscape  papers=%d  sources=%d  "
        "tech_nodes=%d  scholars=%d  gaps=%d",
        len(papers), len(sources),
        len(tech_tree.nodes), len(collab.nodes),
        len(research_gaps.gaps),
    )
    return landscape
