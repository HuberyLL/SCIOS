"""Taxonomy Agent — data-driven tech tree with Map-Reduce LLM labelling.

Architecture aligned with STORM/GPT-Researcher Map-Reduce patterns:
  1. Build clusters from PaperCorpus (sub-field + co-citation)
  2. Small cluster: label directly via one LLM call
  3. Large cluster: Map (summarize in batches) -> Reduce (synthesize node)
  4. Infer edges in batches from citation direction + LLM classification
  5. Self-check: verify all sub-fields are covered
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from src.models.landscape import TechTree, TechTreeEdge, TechTreeNode
from src.models.paper import PaperResult

from ...llm_client import call_llm
from ..prompts.taxonomy_prompts import (
    CLUSTER_LABEL_SYSTEM,
    CLUSTER_LABEL_USER,
    CLUSTER_REDUCE_SYSTEM,
    CLUSTER_REDUCE_USER,
    CLUSTER_SUMMARIZE_SYSTEM,
    CLUSTER_SUMMARIZE_USER,
    EDGE_INFERENCE_SYSTEM,
    EDGE_INFERENCE_USER,
    TAXONOMY_SELF_CHECK_SYSTEM,
    TAXONOMY_SELF_CHECK_USER,
)
from ..schemas import PaperCorpus, ScopeDefinition
from .base import BaseAgent, ProgressCallback

logger = logging.getLogger(__name__)

# Per-unit batch sizes for LLM calls (how many items per single LLM call)
BATCH_SIZE = 30             # papers per LLM call (map phase)
MAX_ABSTRACT_CHARS = 500    # abstract truncation per paper
EDGE_BATCH_SIZE = 40        # edge pairs per LLM call
LARGE_CLUSTER_THRESHOLD = 80


# ---------------------------------------------------------------------------
# LLM response schemas (internal)
# ---------------------------------------------------------------------------

class _NodeLabel(BaseModel):
    node_id: str
    label: str
    node_type: Literal["method", "paper", "milestone", "unverified"]
    year: int | None = None
    description: str
    representative_paper_ids: list[str] = Field(default_factory=list)


class _BatchSummary(BaseModel):
    themes: list[str] = Field(default_factory=list)
    key_methods: list[str] = Field(default_factory=list)
    key_paper_ids: list[str] = Field(default_factory=list)
    year_range: str = ""
    summary: str = ""


class _EdgeClassification(BaseModel):
    source: str
    target: str
    relation: Literal["evolves_from", "extends", "alternative_to", "inspires"]
    label: str = ""


class _EdgeBatch(BaseModel):
    edges: list[_EdgeClassification] = Field(default_factory=list)


class _MissingNode(BaseModel):
    node_id: str
    label: str
    description: str
    node_type: Literal["method", "paper", "milestone", "unverified"] = "method"
    year: int | None = None


class _SelfCheckResult(BaseModel):
    missing_nodes: list[_MissingNode] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal clustering helpers
# ---------------------------------------------------------------------------

@dataclass
class _Cluster:
    """A group of papers sharing a sub-field or co-citation community."""
    name: str
    paper_ids: list[str] = field(default_factory=list)


def _build_clusters(
    corpus: PaperCorpus,
    scope: ScopeDefinition,
) -> list[_Cluster]:
    """Build clusters primarily from sub_field_mapping, with a catch-all
    cluster for unassigned high-citation papers.

    Large clusters (> LARGE_CLUSTER_THRESHOLD papers) are automatically
    split by time era so that each chunk produces a distinct TechTreeNode.
    """
    assigned: set[str] = set()
    clusters: list[_Cluster] = []
    pid_set = _pid_set(corpus)
    lookup = _paper_lookup(corpus)

    for sf_name, pids in corpus.sub_field_mapping.items():
        valid = [pid for pid in pids if pid in pid_set]
        if valid:
            clusters.extend(_maybe_split_cluster(sf_name, valid, lookup))
            assigned.update(valid)

    if corpus.papers:
        cite_counts = sorted(
            (p.citation_count for p in corpus.papers), reverse=True,
        )
        citation_threshold = max(
            cite_counts[len(cite_counts) // 10] if len(cite_counts) > 10 else 0,
            10,
        )
    else:
        citation_threshold = 10

    unassigned_high_cite = [
        p for p in corpus.papers
        if p.paper_id not in assigned and p.citation_count >= citation_threshold
    ]
    if unassigned_high_cite:
        unassigned_high_cite.sort(key=lambda p: p.citation_count, reverse=True)
        foundation_ids = [p.paper_id for p in unassigned_high_cite]
        clusters.extend(
            _maybe_split_cluster("core_foundations", foundation_ids, lookup),
        )

    for seed_id in corpus.seed_paper_ids:
        if seed_id not in assigned:
            for c in clusters:
                if c.name.startswith("core_foundations"):
                    if seed_id not in c.paper_ids:
                        c.paper_ids.insert(0, seed_id)
                    break
            else:
                clusters.append(_Cluster(
                    name="core_foundations",
                    paper_ids=[seed_id],
                ))
            assigned.add(seed_id)

    return [c for c in clusters if c.paper_ids]


def _maybe_split_cluster(
    name: str,
    pids: list[str],
    lookup: dict[str, PaperResult],
) -> list[_Cluster]:
    """Split a cluster by time era if it exceeds LARGE_CLUSTER_THRESHOLD."""
    if len(pids) <= LARGE_CLUSTER_THRESHOLD:
        return [_Cluster(name=name, paper_ids=pids)]

    by_era: dict[str, list[str]] = defaultdict(list)
    for pid in pids:
        p = lookup.get(pid)
        if p:
            year_str = (p.published_date or "")[:4]
            if year_str.isdigit():
                y = int(year_str)
                if y < 2018:
                    by_era["early"].append(pid)
                elif y < 2022:
                    by_era["mid"].append(pid)
                else:
                    by_era["recent"].append(pid)
            else:
                by_era["recent"].append(pid)
        else:
            by_era["recent"].append(pid)

    result: list[_Cluster] = []
    for era, era_pids in by_era.items():
        if era_pids:
            result.append(_Cluster(name=f"{name}_{era}", paper_ids=era_pids))
    return result if result else [_Cluster(name=name, paper_ids=pids)]


def _pid_set(corpus: PaperCorpus) -> set[str]:
    return {p.paper_id for p in corpus.papers}


def _paper_lookup(corpus: PaperCorpus) -> dict[str, PaperResult]:
    return {p.paper_id: p for p in corpus.papers}


def _format_paper(p: PaperResult) -> str:
    """Format a single paper for LLM prompt."""
    abstract = (p.abstract or "")[:MAX_ABSTRACT_CHARS]
    if len(p.abstract or "") > MAX_ABSTRACT_CHARS:
        abstract += "…"
    return (
        f"  paper_id={p.paper_id}  "
        f"Title: {p.title}  "
        f"Year: {p.published_date}  "
        f"Citations: {p.citation_count}\n"
        f"    Abstract: {abstract}"
    )


# ---------------------------------------------------------------------------
# Taxonomy Agent
# ---------------------------------------------------------------------------

class TaxonomyInput(BaseModel):
    corpus: PaperCorpus
    scope: ScopeDefinition


class TaxonomyAgent(BaseAgent[TaxonomyInput, TechTree]):
    """Stage 3: build a data-driven TechTree with Map-Reduce LLM labelling."""

    def __init__(self) -> None:
        super().__init__(name="TaxonomyAgent")

    async def _execute(
        self,
        input_data: TaxonomyInput,
        *,
        on_progress: ProgressCallback = None,
    ) -> TechTree:
        corpus = input_data.corpus
        scope = input_data.scope
        lookup = _paper_lookup(corpus)

        # Step 1 & 2: cluster papers
        await self._notify(on_progress, "clustering papers by sub-field …")
        clusters = _build_clusters(corpus, scope)
        self._logger.info("Built %d clusters", len(clusters))

        # Step 3: LLM label each cluster (Map-Reduce for large clusters)
        await self._notify(on_progress, "labelling %d clusters …" % len(clusters))
        nodes: list[TechTreeNode] = []
        cluster_node_map: dict[str, str] = {}

        for idx, cluster in enumerate(clusters):
            node = await self._label_cluster(idx, cluster, lookup, corpus)
            if node:
                nodes.append(node)
                cluster_node_map[cluster.name] = node.node_id
            else:
                degraded = self._degraded_node(idx, cluster, lookup)
                nodes.append(degraded)
                cluster_node_map[cluster.name] = degraded.node_id
                self._logger.warning(
                    "Cluster '%s' labelling failed — created degraded node '%s'",
                    cluster.name, degraded.node_id,
                )

        if not any(n.node_type != "unverified" for n in nodes):
            self._logger.warning("All nodes are degraded; adding sub-field fallback nodes")
            fallback_nodes = self._subfield_fallback_nodes(scope, corpus)
            nodes.extend(fallback_nodes)

        # Step 4: Infer edges (batched)
        await self._notify(on_progress, "inferring relationships between nodes …")
        edges = await self._infer_edges(nodes, clusters, corpus, cluster_node_map)

        # Step 5: Self-check for missing sub-fields
        await self._notify(on_progress, "checking sub-field coverage …")
        extra_nodes = await self._self_check(scope, nodes, corpus)
        nodes.extend(extra_nodes)

        # Deduplicate
        seen_ids: set[str] = set()
        unique_nodes: list[TechTreeNode] = []
        for n in nodes:
            if n.node_id not in seen_ids:
                seen_ids.add(n.node_id)
                unique_nodes.append(n)

        node_ids = {n.node_id for n in unique_nodes}
        valid_edges = [
            e for e in edges
            if e.source in node_ids and e.target in node_ids
        ]

        tree = TechTree(nodes=unique_nodes, edges=valid_edges)
        self._logger.info(
            "TechTree: %d nodes, %d edges", len(tree.nodes), len(tree.edges),
        )
        return tree

    # ------------------------------------------------------------------
    # Step 3: Label a cluster — direct or Map-Reduce
    # ------------------------------------------------------------------

    async def _label_cluster(
        self,
        idx: int,
        cluster: _Cluster,
        lookup: dict[str, PaperResult],
        corpus: PaperCorpus,
    ) -> TechTreeNode | None:
        papers = [lookup[pid] for pid in cluster.paper_ids if pid in lookup]
        papers.sort(key=lambda p: p.citation_count, reverse=True)

        if len(papers) <= BATCH_SIZE:
            return await self._label_direct(idx, cluster.name, papers, corpus)

        # Map-Reduce for large clusters
        self._logger.info(
            "Cluster '%s' has %d papers, using Map-Reduce",
            cluster.name, len(papers),
        )
        return await self._label_map_reduce(idx, cluster.name, papers, corpus)

    async def _label_direct(
        self,
        idx: int,
        cluster_name: str,
        papers: list[PaperResult],
        corpus: PaperCorpus,
    ) -> TechTreeNode | None:
        """Label a small cluster with a single LLM call."""
        papers_text = "\n".join(_format_paper(p) for p in papers) or "(no papers)"

        try:
            label = await call_llm(
                [
                    {"role": "system", "content": CLUSTER_LABEL_SYSTEM},
                    {"role": "user", "content": CLUSTER_LABEL_USER.format(
                        cluster_idx=idx + 1,
                        cluster_hint=cluster_name,
                        papers_text=papers_text,
                    )},
                ],
                response_format=_NodeLabel,
            )
        except Exception:
            self._logger.warning("Cluster labelling failed for '%s'", cluster_name)
            return None

        valid_pids = _pid_set(corpus)
        rep_ids = [pid for pid in label.representative_paper_ids if pid in valid_pids]

        return TechTreeNode(
            node_id=label.node_id,
            label=label.label,
            node_type=label.node_type,
            year=label.year,
            description=label.description,
            representative_paper_ids=rep_ids,
        )

    async def _label_map_reduce(
        self,
        idx: int,
        cluster_name: str,
        papers: list[PaperResult],
        corpus: PaperCorpus,
    ) -> TechTreeNode | None:
        """Map-Reduce: summarize batches in parallel, then synthesize."""
        batches = [
            papers[i : i + BATCH_SIZE]
            for i in range(0, len(papers), BATCH_SIZE)
        ]
        total_batches = len(batches)

        # Map phase: summarize each batch in parallel
        async def _summarize(batch_idx: int, batch: list[PaperResult]):
            papers_text = "\n".join(_format_paper(p) for p in batch)
            try:
                return await call_llm(
                    [
                        {"role": "system", "content": CLUSTER_SUMMARIZE_SYSTEM},
                        {"role": "user", "content": CLUSTER_SUMMARIZE_USER.format(
                            cluster_hint=cluster_name,
                            batch_idx=batch_idx + 1,
                            batch_total=total_batches,
                            papers_text=papers_text,
                        )},
                    ],
                    response_format=_BatchSummary,
                )
            except Exception:
                self._logger.warning(
                    "Batch %d/%d summarization failed for '%s'",
                    batch_idx + 1, total_batches, cluster_name,
                )
                return None

        summaries = await asyncio.gather(
            *[_summarize(i, b) for i, b in enumerate(batches)],
        )
        valid_summaries = [s for s in summaries if s is not None]

        if not valid_summaries:
            self._logger.warning("All batch summaries failed for '%s', falling back to direct", cluster_name)
            return await self._label_direct(idx, cluster_name, papers[:BATCH_SIZE], corpus)

        # Reduce phase: synthesize summaries into a single node
        summaries_text = "\n\n".join(
            f"--- Batch {i+1} ---\n"
            f"Themes: {', '.join(s.themes)}\n"
            f"Methods: {', '.join(s.key_methods)}\n"
            f"Key papers: {', '.join(s.key_paper_ids)}\n"
            f"Years: {s.year_range}\n"
            f"Summary: {s.summary}"
            for i, s in enumerate(valid_summaries)
        )

        try:
            label = await call_llm(
                [
                    {"role": "system", "content": CLUSTER_REDUCE_SYSTEM},
                    {"role": "user", "content": CLUSTER_REDUCE_USER.format(
                        cluster_hint=cluster_name,
                        batch_count=len(valid_summaries),
                        total_papers=len(papers),
                        summaries_text=summaries_text,
                    )},
                ],
                response_format=_NodeLabel,
            )
        except Exception:
            self._logger.warning("Reduce phase failed for '%s'", cluster_name)
            return None

        valid_pids = _pid_set(corpus)
        rep_ids = [pid for pid in label.representative_paper_ids if pid in valid_pids]

        return TechTreeNode(
            node_id=label.node_id,
            label=label.label,
            node_type=label.node_type,
            year=label.year,
            description=label.description,
            representative_paper_ids=rep_ids,
        )

    # ------------------------------------------------------------------
    # Step 4: Infer edges — batched
    # ------------------------------------------------------------------

    async def _infer_edges(
        self,
        nodes: list[TechTreeNode],
        clusters: list[_Cluster],
        corpus: PaperCorpus,
        cluster_node_map: dict[str, str],
    ) -> list[TechTreeEdge]:
        """Find citation links between clusters and classify in batches."""
        node_id_set = {n.node_id for n in nodes}

        pid_to_cluster: dict[str, str] = {}
        for cluster in clusters:
            nid = cluster_node_map.get(cluster.name)
            if not nid:
                continue
            for pid in cluster.paper_ids:
                pid_to_cluster[pid] = nid

        cross_cluster_links: dict[tuple[str, str], int] = defaultdict(int)
        for src_pid, cited_pids in corpus.citation_graph.items():
            src_node = pid_to_cluster.get(src_pid)
            if not src_node:
                continue
            for tgt_pid in cited_pids:
                tgt_node = pid_to_cluster.get(tgt_pid)
                if tgt_node and tgt_node != src_node:
                    cross_cluster_links[(src_node, tgt_node)] += 1

        if not cross_cluster_links:
            self._logger.info("No cross-cluster citation links found, inferring time-based edges")
            return self._time_based_edges(nodes)

        sorted_links = sorted(cross_cluster_links.items(), key=lambda x: x[1], reverse=True)

        nodes_text = "\n".join(
            f"- {n.node_id}: {n.label} ({n.year}) — {n.description}"
            for n in nodes if n.node_id in node_id_set
        )

        # Process edges in batches
        all_edges: list[TechTreeEdge] = []
        for batch_start in range(0, len(sorted_links), EDGE_BATCH_SIZE):
            batch_links = sorted_links[batch_start : batch_start + EDGE_BATCH_SIZE]
            pairs_text = "\n".join(
                f"- {src} --({count} citations)--> {tgt}"
                for (src, tgt), count in batch_links
            )

            try:
                result = await call_llm(
                    [
                        {"role": "system", "content": EDGE_INFERENCE_SYSTEM},
                        {"role": "user", "content": EDGE_INFERENCE_USER.format(
                            nodes_text=nodes_text,
                            pairs_text=pairs_text,
                        )},
                    ],
                    response_format=_EdgeBatch,
                )
                for ec in result.edges:
                    if ec.source in node_id_set and ec.target in node_id_set:
                        all_edges.append(TechTreeEdge(
                            source=ec.source,
                            target=ec.target,
                            relation=ec.relation,
                            label=ec.label,
                        ))
            except Exception:
                self._logger.warning(
                    "Edge inference batch %d failed",
                    batch_start // EDGE_BATCH_SIZE + 1,
                )

        if not all_edges:
            self._logger.info("All edge inference failed, using time-based fallback")
            return self._time_based_edges(nodes)

        return all_edges

    @staticmethod
    def _time_based_edges(nodes: list[TechTreeNode]) -> list[TechTreeEdge]:
        """Fallback: connect nodes chronologically (marked as temporal_fallback)."""
        sorted_nodes = sorted(nodes, key=lambda n: n.year or 9999)
        edges: list[TechTreeEdge] = []
        for i in range(1, len(sorted_nodes)):
            edges.append(TechTreeEdge(
                source=sorted_nodes[i - 1].node_id,
                target=sorted_nodes[i].node_id,
                relation="inspires",
                label="temporal_fallback",
            ))
        return edges

    # ------------------------------------------------------------------
    # Degraded / fallback node builders
    # ------------------------------------------------------------------

    @staticmethod
    def _degraded_node(
        idx: int,
        cluster: _Cluster,
        lookup: dict[str, PaperResult],
    ) -> TechTreeNode:
        """Build a degraded node from cluster metadata when LLM labelling fails."""
        top_papers = sorted(
            (lookup[pid] for pid in cluster.paper_ids if pid in lookup),
            key=lambda p: p.citation_count,
            reverse=True,
        )[:3]
        label = cluster.name.replace("_", " ").title()
        desc = ", ".join(p.title for p in top_papers) if top_papers else "LLM labelling failed"
        rep_ids = [p.paper_id for p in top_papers]
        year = None
        if top_papers:
            years = []
            for p in top_papers:
                y_str = (p.published_date or "")[:4]
                if y_str.isdigit():
                    years.append(int(y_str))
            if years:
                year = min(years)

        return TechTreeNode(
            node_id=f"degraded_{idx}_{cluster.name[:30]}",
            label=label,
            node_type="unverified",
            year=year,
            description=desc,
            representative_paper_ids=rep_ids,
        )

    @staticmethod
    def _subfield_fallback_nodes(
        scope: ScopeDefinition,
        corpus: PaperCorpus,
    ) -> list[TechTreeNode]:
        """Create one node per scope sub-field as a last-resort fallback."""
        nodes: list[TechTreeNode] = []
        for i, sf in enumerate(scope.sub_fields):
            rep_ids = corpus.sub_field_mapping.get(sf.name, [])[:5]
            nodes.append(TechTreeNode(
                node_id=f"fallback_sf_{i}_{sf.name[:20].replace(' ', '_')}",
                label=sf.name,
                node_type="unverified",
                year=None,
                description=sf.description,
                representative_paper_ids=rep_ids,
            ))
        return nodes

    # ------------------------------------------------------------------
    # Step 5: Self-check
    # ------------------------------------------------------------------

    async def _self_check(
        self,
        scope: ScopeDefinition,
        nodes: list[TechTreeNode],
        corpus: PaperCorpus,
    ) -> list[TechTreeNode]:
        """Ask LLM if any sub-fields are missing from the tree."""
        sub_fields_text = "\n".join(
            f"- {sf.name}: {sf.description}" for sf in scope.sub_fields
        )
        nodes_text = "\n".join(
            f"- {n.node_id}: {n.label} — {n.description}" for n in nodes
        )

        try:
            result = await call_llm(
                [
                    {"role": "system", "content": TAXONOMY_SELF_CHECK_SYSTEM},
                    {"role": "user", "content": TAXONOMY_SELF_CHECK_USER.format(
                        topic=scope.topic,
                        sub_fields_text=sub_fields_text,
                        nodes_text=nodes_text,
                    )},
                ],
                response_format=_SelfCheckResult,
            )
        except Exception:
            self._logger.warning("Taxonomy self-check LLM call failed")
            return []

        extra: list[TechTreeNode] = []
        for mn in result.missing_nodes:
            extra.append(TechTreeNode(
                node_id=mn.node_id,
                label=mn.label,
                node_type=mn.node_type,
                year=mn.year,
                description=mn.description,
                representative_paper_ids=[],
            ))

        if extra:
            self._logger.info("Self-check added %d missing nodes", len(extra))
        return extra
