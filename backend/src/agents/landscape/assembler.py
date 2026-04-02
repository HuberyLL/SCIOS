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
    ResearchGaps,
    TechTree,
)
from src.models.paper import PaperResult

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
    papers: list[PaperResult],
    tech_tree: TechTree,
    collaboration_network: CollaborationNetwork,
    research_gaps: ResearchGaps,
    quality: str = "complete",
    base_version: int = 0,
) -> DynamicResearchLandscape:
    """Combine all pipeline outputs into the final ``DynamicResearchLandscape``.

    Key responsibility: **reference sanitisation** — any ``paper_id``
    produced by the LLM that does not appear in the actual papers list is
    silently removed so ``DynamicResearchLandscape.model_validator`` passes.
    """
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

    tt = copy.deepcopy(tech_tree)
    rg = copy.deepcopy(research_gaps)
    collab = copy.deepcopy(collaboration_network)

    for node in tt.nodes:
        node.representative_paper_ids = _sanitise_ids(
            node.representative_paper_ids,
            valid_ids,
            f"TechTreeNode('{node.node_id}').representative_paper_ids",
        )

    for gap in rg.gaps:
        gap.evidence_paper_ids = _sanitise_ids(
            gap.evidence_paper_ids,
            valid_ids,
            f"ResearchGap('{gap.gap_id}').evidence_paper_ids",
        )

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
        version=base_version + 1,
        quality=quality,  # type: ignore[arg-type]
    )

    landscape = DynamicResearchLandscape(
        meta=meta,
        tech_tree=tt,
        collaboration_network=collab,
        research_gaps=rg,
        papers=papers,
        sources=sources,
    )

    logger.info(
        "Assembled DynamicResearchLandscape  papers=%d  sources=%d  "
        "tech_nodes=%d  scholars=%d  gaps=%d",
        len(papers), len(sources),
        len(tt.nodes), len(collab.nodes),
        len(rg.gaps),
    )
    return landscape
