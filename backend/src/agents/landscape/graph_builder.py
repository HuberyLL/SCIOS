"""Build a CollaborationNetwork from enriched paper data.

Pure Python — no LLM, no I/O.  Operates on ``EnrichedPaper`` objects
produced by the retriever stage and emits a ``CollaborationNetwork``
ready for the assembler.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from itertools import combinations

from src.models.landscape import (
    CollaborationEdge,
    CollaborationNetwork,
    ScholarNode,
)

from .schemas import EnrichedPaper, S2AuthorDetail

logger = logging.getLogger(__name__)

MIN_PAPER_COUNT = 2


def build_collaboration_network(
    enriched_papers: list[EnrichedPaper],
) -> CollaborationNetwork:
    """Construct a co-authorship network from enriched paper metadata.

    Only scholars with ``paper_count >= MIN_PAPER_COUNT`` are retained to
    filter out noise.  Edges are weighted by the number of co-authored
    papers.
    """
    scholar_map: dict[str, dict] = {}
    edge_counter: dict[tuple[str, str], dict] = {}

    for ep in enriched_papers:
        paper = ep.paper
        authors_with_id = [a for a in ep.author_details if a.author_id]

        for author in authors_with_id:
            aid = author.author_id
            if aid not in scholar_map:
                scholar_map[aid] = {
                    "name": author.name,
                    "affiliations": set(author.affiliations),
                    "paper_count": 0,
                    "citation_count": 0,
                    "top_papers": [],
                }
            entry = scholar_map[aid]
            entry["paper_count"] += 1
            entry["citation_count"] += paper.citation_count
            entry["affiliations"].update(author.affiliations)
            entry["top_papers"].append(
                (paper.paper_id, paper.citation_count),
            )

        aid_list = [a.author_id for a in authors_with_id]
        for a_id, b_id in combinations(sorted(aid_list), 2):
            key = (a_id, b_id)
            if key not in edge_counter:
                edge_counter[key] = {"weight": 0, "shared_paper_ids": []}
            edge_counter[key]["weight"] += 1
            edge_counter[key]["shared_paper_ids"].append(paper.paper_id)

    nodes: list[ScholarNode] = []
    retained_ids: set[str] = set()
    for aid, info in scholar_map.items():
        if info["paper_count"] < MIN_PAPER_COUNT:
            continue
        retained_ids.add(aid)
        top_papers = sorted(info["top_papers"], key=lambda t: t[1], reverse=True)
        nodes.append(
            ScholarNode(
                scholar_id=aid,
                name=info["name"],
                affiliations=sorted(info["affiliations"]),
                paper_count=info["paper_count"],
                citation_count=info["citation_count"],
                top_paper_ids=[pid for pid, _ in top_papers[:5]],
            )
        )

    edges: list[CollaborationEdge] = []
    for (src, tgt), info in edge_counter.items():
        if src not in retained_ids or tgt not in retained_ids:
            continue
        edges.append(
            CollaborationEdge(
                source=src,
                target=tgt,
                weight=info["weight"],
                shared_paper_ids=info["shared_paper_ids"],
            )
        )

    logger.info(
        "CollaborationNetwork  scholars=%d  edges=%d  (filtered from %d authors)",
        len(nodes),
        len(edges),
        len(scholar_map),
    )
    return CollaborationNetwork(nodes=nodes, edges=edges)
