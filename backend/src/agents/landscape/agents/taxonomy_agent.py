"""Taxonomy Agent — data-driven tech tree with hierarchical time-window
clustering, Map-Reduce LLM labelling, and global topology inference.

Pipeline:
  1. Build clusters from PaperCorpus (sub-field x time-window splits)
  2. Small cluster: label directly via one LLM call
  3. Large cluster: Map (summarize in batches) -> Reduce (synthesize node)
  4. Infer edges from citation graph (batched LLM classification)
  5. Global edge inference: LLM fills in missing relationships (batched)
  6. Self-check: verify all sub-fields are covered
  7. Post-processing: calibrate importance/depth, deduplicate edges
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from src.models.landscape import TechTree, TechTreeEdge, TechTreeNode
from src.models.paper import PaperResult

from src.core.config import get_settings

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
    GLOBAL_EDGE_INFERENCE_SYSTEM,
    GLOBAL_EDGE_INFERENCE_USER,
    TAXONOMY_SELF_CHECK_SYSTEM,
    TAXONOMY_SELF_CHECK_USER,
)
from ..schemas import PaperCorpus, ScopeDefinition
from .base import BaseAgent, ProgressCallback

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
MAX_ABSTRACT_CHARS = 400
EDGE_BATCH_SIZE = 40
GLOBAL_EDGE_BATCH_SIZE = 60
SPLIT_WINDOW_YEARS = 4
MIN_PAPERS_PER_WINDOW = 3

NODE_TYPE = Literal[
    "foundation", "breakthrough", "incremental",
    "application", "survey", "unverified",
]


# ---------------------------------------------------------------------------
# LLM response schemas (internal)
# ---------------------------------------------------------------------------

class _NodeLabel(BaseModel):
    node_id: str
    label: str
    node_type: Literal[
        "foundation", "breakthrough", "incremental",
        "application", "survey", "unverified",
    ]
    year: int | None = None
    description: str
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    depth: int = Field(default=0, ge=0)
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
    node_type: Literal[
        "foundation", "breakthrough", "incremental",
        "application", "survey", "unverified",
    ] = "incremental"
    year: int | None = None
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    depth: int = Field(default=0, ge=0)


class _SelfCheckResult(BaseModel):
    missing_nodes: list[_MissingNode] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal clustering helpers
# ---------------------------------------------------------------------------

@dataclass
class _Cluster:
    """A group of papers sharing a sub-field and time window."""
    name: str
    sub_field: str
    paper_ids: list[str] = field(default_factory=list)


def _cluster_slug(cluster_name: str) -> str:
    """Short deterministic suffix from cluster name to make node_ids unique."""
    return hashlib.sha1(cluster_name.encode()).hexdigest()[:6]


def _build_clusters(
    corpus: PaperCorpus,
    scope: ScopeDefinition,
) -> list[_Cluster]:
    """Build fine-grained clusters by splitting each sub-field into
    time windows of ~SPLIT_WINDOW_YEARS years.  This yields 3-5 clusters
    per sub-field instead of the previous 1:1 mapping.
    """
    assigned: set[str] = set()
    clusters: list[_Cluster] = []
    pid_set = _pid_set(corpus)
    lookup = _paper_lookup(corpus)

    time_start = scope.time_range_start
    time_end = scope.time_range_end

    for sf_name, pids in corpus.sub_field_mapping.items():
        valid = [pid for pid in pids if pid in pid_set]
        if not valid:
            continue
        sf_clusters = _split_by_time_window(
            sf_name, sf_name, valid, lookup, time_start, time_end,
        )
        clusters.extend(sf_clusters)
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
            _split_by_time_window(
                "core_foundations", "core_foundations",
                foundation_ids, lookup, time_start, time_end,
            ),
        )
        assigned.update(foundation_ids)

    for seed_id in corpus.seed_paper_ids:
        if seed_id not in assigned:
            for c in clusters:
                if c.sub_field == "core_foundations":
                    if seed_id not in c.paper_ids:
                        c.paper_ids.insert(0, seed_id)
                    break
            else:
                clusters.append(_Cluster(
                    name="core_foundations",
                    sub_field="core_foundations",
                    paper_ids=[seed_id],
                ))
            assigned.add(seed_id)

    return [c for c in clusters if c.paper_ids]


def _split_by_time_window(
    base_name: str,
    sub_field: str,
    pids: list[str],
    lookup: dict[str, PaperResult],
    time_start: int,
    time_end: int,
) -> list[_Cluster]:
    """Split papers into time-window clusters. Small windows are merged
    into their nearest neighbour to avoid tiny clusters."""
    span = max(time_end - time_start, 1)
    n_windows = max(span // SPLIT_WINDOW_YEARS, 1)
    window_size = max(span / n_windows, 1)

    buckets: dict[int, list[str]] = defaultdict(list)
    for pid in pids:
        p = lookup.get(pid)
        year_str = ((p.published_date or "")[:4]) if p else ""
        if year_str.isdigit():
            y = int(year_str)
            window_idx = min(int((y - time_start) / window_size), n_windows - 1)
            window_idx = max(window_idx, 0)
        else:
            window_idx = n_windows - 1
        buckets[window_idx].append(pid)

    sorted_idxs = sorted(buckets.keys())
    merged: list[tuple[int, list[str]]] = []
    for idx in sorted_idxs:
        if merged and len(merged[-1][1]) < MIN_PAPERS_PER_WINDOW:
            merged[-1] = (merged[-1][0], merged[-1][1] + buckets[idx])
        else:
            merged.append((idx, list(buckets[idx])))

    if len(merged) > 1 and len(merged[-1][1]) < MIN_PAPERS_PER_WINDOW:
        last = merged.pop()
        merged[-1] = (merged[-1][0], merged[-1][1] + last[1])

    if len(merged) <= 1:
        return [_Cluster(name=base_name, sub_field=sub_field, paper_ids=pids)]

    result: list[_Cluster] = []
    for win_idx, win_pids in merged:
        year_lo = int(time_start + win_idx * window_size)
        year_hi = min(int(year_lo + window_size - 1), time_end)
        tag = f"{year_lo}-{year_hi}"
        result.append(_Cluster(
            name=f"{base_name}_{tag}",
            sub_field=sub_field,
            paper_ids=win_pids,
        ))
    return result


def _pid_set(corpus: PaperCorpus) -> set[str]:
    return {p.paper_id for p in corpus.papers}


def _paper_lookup(corpus: PaperCorpus) -> dict[str, PaperResult]:
    return {p.paper_id: p for p in corpus.papers}


def _format_paper(p: PaperResult) -> str:
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
# Post-processing helpers
# ---------------------------------------------------------------------------

def _calibrate_importance(
    nodes: list[TechTreeNode],
    lookup: dict[str, PaperResult],
) -> None:
    """Blend LLM importance with citation data and normalise to [0.2, 1.0]."""
    citation_sums: list[float] = []
    for n in nodes:
        total = 0
        for pid in n.representative_paper_ids:
            p = lookup.get(pid)
            if p:
                total += p.citation_count
        citation_sums.append(float(total))

    max_cite = max(citation_sums) if citation_sums else 1.0
    if max_cite == 0:
        max_cite = 1.0

    raw_scores: list[float] = []
    for n, cite_sum in zip(nodes, citation_sums):
        cite_imp = math.log1p(cite_sum) / math.log1p(max_cite) if n.representative_paper_ids else n.importance
        blended = 0.4 * n.importance + 0.6 * cite_imp if n.representative_paper_ids else n.importance
        raw_scores.append(blended)

    lo = min(raw_scores) if raw_scores else 0.0
    hi = max(raw_scores) if raw_scores else 1.0
    span = hi - lo if hi > lo else 1.0

    for n, raw in zip(nodes, raw_scores):
        normalised = (raw - lo) / span
        n.importance = round(0.2 + normalised * 0.8, 3)


def _calibrate_depth(
    nodes: list[TechTreeNode],
    edges: list[TechTreeEdge],
) -> list[TechTreeEdge]:
    """Compute depth via topological sort.  Cycles are detected with DFS
    and the back-edges that close them are removed from *edges* so that
    the returned list is a DAG.  Node depths are set in-place."""
    node_ids = {n.node_id for n in nodes}
    adj: dict[str, list[tuple[str, int]]] = defaultdict(list)
    edge_list: list[TechTreeEdge] = []

    for e in edges:
        if e.source in node_ids and e.target in node_ids:
            idx = len(edge_list)
            adj[e.source].append((e.target, idx))
            edge_list.append(e)

    # Iterative DFS cycle detection — mark back-edge indices for removal
    WHITE, GRAY, BLACK = 0, 1, 2
    colour: dict[str, int] = {nid: WHITE for nid in node_ids}
    back_edge_indices: set[int] = set()

    for start in node_ids:
        if colour[start] != WHITE:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        colour[start] = GRAY
        while stack:
            u, ei = stack[-1]
            neighbors = adj[u]
            if ei < len(neighbors):
                stack[-1] = (u, ei + 1)
                v, idx = neighbors[ei]
                if colour.get(v, WHITE) == GRAY:
                    back_edge_indices.add(idx)
                elif colour.get(v, WHITE) == WHITE:
                    colour[v] = GRAY
                    stack.append((v, 0))
            else:
                colour[u] = BLACK
                stack.pop()

    if back_edge_indices:
        logger.warning(
            "Removed %d back-edge(s) to break cycles in tech tree",
            len(back_edge_indices),
        )

    dag_edges = [e for i, e in enumerate(edge_list) if i not in back_edge_indices]

    # Kahn topo-sort on the clean DAG
    dag_adj: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {nid: 0 for nid in node_ids}
    for e in dag_edges:
        dag_adj[e.source].append(e.target)
        in_degree[e.target] = in_degree.get(e.target, 0) + 1

    queue: deque[str] = deque(
        nid for nid in node_ids if in_degree[nid] == 0
    )
    depth_map: dict[str, int] = {}
    while queue:
        nid = queue.popleft()
        depth_map.setdefault(nid, 0)
        for child in dag_adj[nid]:
            depth_map[child] = max(depth_map.get(child, 0), depth_map[nid] + 1)
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    for n in nodes:
        n.depth = depth_map.get(n.node_id, 0)

    return dag_edges


def _enforce_temporal_direction(
    nodes: list[TechTreeNode],
    edges: list[TechTreeEdge],
) -> list[TechTreeEdge]:
    """Ensure all edges flow from older (source) to newer (target).
    Dagre TB layout then naturally places older nodes on top."""
    year_map = {n.node_id: (n.year or 9999) for n in nodes}
    flipped = 0
    result: list[TechTreeEdge] = []
    for e in edges:
        src_year = year_map.get(e.source, 9999)
        tgt_year = year_map.get(e.target, 9999)
        if src_year > tgt_year:
            result.append(TechTreeEdge(
                source=e.target, target=e.source,
                relation=e.relation, label=e.label,
            ))
            flipped += 1
        else:
            result.append(e)
    if flipped:
        logger.info("Flipped %d edge(s) to enforce temporal direction", flipped)
    return result


def _deduplicate_edges(edges: list[TechTreeEdge]) -> list[TechTreeEdge]:
    """Final edge dedup: keep first occurrence per directed pair, and
    prevent 2-cycles for directional relations (evolves_from, extends)."""
    seen_directed: set[tuple[str, str]] = set()
    seen_undirected: set[frozenset[str]] = set()
    directional = {"evolves_from", "extends"}
    result: list[TechTreeEdge] = []

    for e in edges:
        pair = (e.source, e.target)
        if pair in seen_directed:
            continue
        upair = frozenset({e.source, e.target})
        if e.relation in directional and upair in seen_undirected:
            continue
        seen_directed.add(pair)
        if e.relation in directional:
            seen_undirected.add(upair)
        result.append(e)

    return result


# ---------------------------------------------------------------------------
# Taxonomy Agent
# ---------------------------------------------------------------------------

class TaxonomyInput(BaseModel):
    corpus: PaperCorpus
    scope: ScopeDefinition


class TaxonomyAgent(BaseAgent[TaxonomyInput, TechTree]):
    """Stage 3: build a data-driven TechTree with hierarchical clustering,
    Map-Reduce LLM labelling, and global topology inference."""

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

        # Step 1: cluster papers (sub-field x time-window)
        await self._notify(on_progress, "clustering papers by sub-field and time window …")
        clusters = _build_clusters(corpus, scope)
        self._logger.info("Built %d clusters", len(clusters))

        # Step 2: LLM label each cluster (node_id made unique per cluster)
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

        # Step 3: Infer edges from citations (batched)
        await self._notify(on_progress, "inferring citation-based relationships …")
        citation_edges = await self._infer_edges(
            nodes, clusters, corpus, cluster_node_map,
        )

        # Step 4: Global edge inference (batched, LLM fills missing links)
        await self._notify(on_progress, "inferring global topology …")
        all_edges = await self._infer_global_edges(nodes, citation_edges)

        # Step 5: Self-check for missing sub-fields
        await self._notify(on_progress, "checking sub-field coverage …")
        extra_nodes = await self._self_check(scope, nodes, corpus)
        nodes.extend(extra_nodes)

        # Step 6: Deduplicate nodes (merge on collision)
        unique_nodes = self._merge_duplicate_nodes(nodes)

        # Step 7: Deduplicate edges + filter dangling
        node_ids = {n.node_id for n in unique_nodes}
        valid_edges = _deduplicate_edges([
            e for e in all_edges
            if e.source in node_ids and e.target in node_ids
        ])

        # Step 7.5: Enforce temporal direction (older→newer for dagre TB)
        valid_edges = _enforce_temporal_direction(unique_nodes, valid_edges)

        # Step 8: Calibrate importance & depth (depth also removes cycle edges)
        await self._notify(on_progress, "calibrating node metrics …")
        _calibrate_importance(unique_nodes, lookup)
        valid_edges = _calibrate_depth(unique_nodes, valid_edges)

        tree = TechTree(nodes=unique_nodes, edges=valid_edges)
        self._logger.info(
            "TechTree: %d nodes, %d edges", len(tree.nodes), len(tree.edges),
        )
        return tree

    # ------------------------------------------------------------------
    # Node dedup: merge rather than silently drop
    # ------------------------------------------------------------------

    def _merge_duplicate_nodes(
        self, nodes: list[TechTreeNode],
    ) -> list[TechTreeNode]:
        """When two nodes share the same node_id, keep the one with higher
        importance and merge their representative_paper_ids."""
        index: dict[str, TechTreeNode] = {}
        for n in nodes:
            if n.node_id not in index:
                index[n.node_id] = n
            else:
                existing = index[n.node_id]
                merged_pids = list(dict.fromkeys(
                    existing.representative_paper_ids + n.representative_paper_ids,
                ))
                winner = n if n.importance > existing.importance else existing
                winner.representative_paper_ids = merged_pids
                index[n.node_id] = winner
                self._logger.warning(
                    "Merged duplicate node_id '%s' (kept importance=%.2f, %d papers)",
                    n.node_id, winner.importance, len(merged_pids),
                )
        return list(index.values())

    # ------------------------------------------------------------------
    # Step 2: Label a cluster — direct or Map-Reduce
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
            return await self._label_direct(idx, cluster, papers, corpus)

        self._logger.info(
            "Cluster '%s' has %d papers, using Map-Reduce",
            cluster.name, len(papers),
        )
        return await self._label_map_reduce(idx, cluster, papers, corpus)

    async def _label_direct(
        self,
        idx: int,
        cluster: _Cluster,
        papers: list[PaperResult],
        corpus: PaperCorpus,
    ) -> TechTreeNode | None:
        papers_text = "\n".join(_format_paper(p) for p in papers) or "(no papers)"

        try:
            label = await call_llm(
                [
                    {"role": "system", "content": CLUSTER_LABEL_SYSTEM},
                    {"role": "user", "content": CLUSTER_LABEL_USER.format(
                        cluster_idx=idx + 1,
                        cluster_hint=cluster.name,
                        papers_text=papers_text,
                    )},
                ],
                response_format=_NodeLabel,
            )
        except Exception:
            self._logger.warning("Cluster labelling failed for '%s'", cluster.name)
            return None

        valid_pids = _pid_set(corpus)
        rep_ids = [pid for pid in label.representative_paper_ids if pid in valid_pids]
        unique_id = f"{label.node_id}__{_cluster_slug(cluster.name)}"

        return TechTreeNode(
            node_id=unique_id,
            label=label.label,
            node_type=label.node_type,
            year=label.year,
            description=label.description,
            importance=label.importance,
            depth=label.depth,
            representative_paper_ids=rep_ids,
        )

    async def _label_map_reduce(
        self,
        idx: int,
        cluster: _Cluster,
        papers: list[PaperResult],
        corpus: PaperCorpus,
    ) -> TechTreeNode | None:
        batches = [
            papers[i : i + BATCH_SIZE]
            for i in range(0, len(papers), BATCH_SIZE)
        ]
        total_batches = len(batches)
        cfg = get_settings()
        sem = asyncio.Semaphore(cfg.landscape_map_concurrency)

        async def _summarize(batch_idx: int, batch: list[PaperResult]):
            async with sem:
                papers_text = "\n".join(_format_paper(p) for p in batch)
                try:
                    return await call_llm(
                        [
                            {"role": "system", "content": CLUSTER_SUMMARIZE_SYSTEM},
                            {"role": "user", "content": CLUSTER_SUMMARIZE_USER.format(
                                cluster_hint=cluster.name,
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
                        batch_idx + 1, total_batches, cluster.name,
                    )
                    return None

        summaries = await asyncio.gather(
            *[_summarize(i, b) for i, b in enumerate(batches)],
        )
        valid_summaries = [s for s in summaries if s is not None]

        if not valid_summaries:
            self._logger.warning("All batch summaries failed for '%s', falling back to direct", cluster.name)
            return await self._label_direct(idx, cluster, papers[:BATCH_SIZE], corpus)

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
                        cluster_hint=cluster.name,
                        batch_count=len(valid_summaries),
                        total_papers=len(papers),
                        summaries_text=summaries_text,
                    )},
                ],
                response_format=_NodeLabel,
            )
        except Exception:
            self._logger.warning("Reduce phase failed for '%s'", cluster.name)
            return None

        valid_pids = _pid_set(corpus)
        rep_ids = [pid for pid in label.representative_paper_ids if pid in valid_pids]
        unique_id = f"{label.node_id}__{_cluster_slug(cluster.name)}"

        return TechTreeNode(
            node_id=unique_id,
            label=label.label,
            node_type=label.node_type,
            year=label.year,
            description=label.description,
            importance=label.importance,
            depth=label.depth,
            representative_paper_ids=rep_ids,
        )

    # ------------------------------------------------------------------
    # Step 3: Infer edges from citation graph (batched)
    # ------------------------------------------------------------------

    async def _infer_edges(
        self,
        nodes: list[TechTreeNode],
        clusters: list[_Cluster],
        corpus: PaperCorpus,
        cluster_node_map: dict[str, str],
    ) -> list[TechTreeEdge]:
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
            self._logger.info("No cross-cluster citation links found, using sub-field time chains")
            return self._time_based_edges(nodes, clusters, cluster_node_map)

        sorted_links = sorted(cross_cluster_links.items(), key=lambda x: x[1], reverse=True)

        nodes_text = "\n".join(
            f"- {n.node_id}: {n.label} ({n.year}) — {n.description}"
            for n in nodes if n.node_id in node_id_set
        )

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
            self._logger.info("All edge inference failed, using sub-field time chains")
            return self._time_based_edges(nodes, clusters, cluster_node_map)

        return all_edges

    # ------------------------------------------------------------------
    # Step 4: Global edge inference — batched LLM fills missing links
    # ------------------------------------------------------------------

    async def _infer_global_edges(
        self,
        nodes: list[TechTreeNode],
        existing_edges: list[TechTreeEdge],
    ) -> list[TechTreeEdge]:
        """Use LLM domain knowledge to fill in edges that citation data
        alone cannot capture.  Sliding windows with 50% overlap ensure
        cross-batch node pairs are visible to at least one LLM call."""
        if len(nodes) < 2:
            return existing_edges

        node_id_set = {n.node_id for n in nodes}
        existing_pairs: set[frozenset[str]] = {
            frozenset({e.source, e.target}) for e in existing_edges
        }

        existing_edges_text = "\n".join(
            f"- {e.source} --[{e.relation}]--> {e.target}"
            + (f' "{e.label}"' if e.label else "")
            for e in existing_edges
        ) or "(none yet)"

        sorted_nodes = sorted(nodes, key=lambda n: n.year or 9999)
        new_edges = list(existing_edges)
        added = 0

        n_total = len(sorted_nodes)
        bs = GLOBAL_EDGE_BATCH_SIZE
        stride = max(1, bs // 2)

        if n_total <= bs:
            windows = [(0, n_total)]
        else:
            windows = []
            start = 0
            while start < n_total:
                end = min(start + bs, n_total)
                windows.append((start, end))
                if end >= n_total:
                    break
                start += stride

        for win_idx, (w_start, w_end) in enumerate(windows):
            batch_nodes = sorted_nodes[w_start:w_end]
            nodes_text = "\n".join(
                f"- {n.node_id}: {n.label} ({n.year}, {n.node_type}, "
                f"importance={n.importance:.1f}) — {n.description}"
                for n in batch_nodes
            )

            try:
                result = await call_llm(
                    [
                        {"role": "system", "content": GLOBAL_EDGE_INFERENCE_SYSTEM},
                        {"role": "user", "content": GLOBAL_EDGE_INFERENCE_USER.format(
                            nodes_text=nodes_text,
                            existing_edges_text=existing_edges_text,
                        )},
                    ],
                    response_format=_EdgeBatch,
                )
            except Exception:
                self._logger.warning(
                    "Global edge inference window %d/%d failed",
                    win_idx + 1, len(windows),
                )
                continue

            for ec in result.edges:
                upair = frozenset({ec.source, ec.target})
                if (
                    upair not in existing_pairs
                    and ec.source in node_id_set
                    and ec.target in node_id_set
                ):
                    new_edges.append(TechTreeEdge(
                        source=ec.source,
                        target=ec.target,
                        relation=ec.relation,
                        label=ec.label,
                    ))
                    existing_pairs.add(upair)
                    added += 1

        if added:
            self._logger.info("Global inference added %d edges (%d windows)", added, len(windows))
        return new_edges

    # ------------------------------------------------------------------
    # Improved time-based fallback: sub-field chains, not a single chain
    # ------------------------------------------------------------------

    @staticmethod
    def _time_based_edges(
        nodes: list[TechTreeNode],
        clusters: list[_Cluster],
        cluster_node_map: dict[str, str],
    ) -> list[TechTreeEdge]:
        """Fallback: chain nodes within the same sub-field chronologically,
        then connect sub-field roots to the earliest foundation node."""
        sf_nodes: dict[str, list[TechTreeNode]] = defaultdict(list)
        node_lookup = {n.node_id: n for n in nodes}

        for cluster in clusters:
            nid = cluster_node_map.get(cluster.name)
            if nid and nid in node_lookup:
                sf_nodes[cluster.sub_field].append(node_lookup[nid])

        edges: list[TechTreeEdge] = []
        sf_roots: list[TechTreeNode] = []

        for sf, sf_node_list in sf_nodes.items():
            sorted_sf = sorted(sf_node_list, key=lambda n: n.year or 9999)
            seen: set[str] = set()
            deduped: list[TechTreeNode] = []
            for n in sorted_sf:
                if n.node_id not in seen:
                    seen.add(n.node_id)
                    deduped.append(n)
            sorted_sf = deduped

            for i in range(1, len(sorted_sf)):
                edges.append(TechTreeEdge(
                    source=sorted_sf[i - 1].node_id,
                    target=sorted_sf[i].node_id,
                    relation="evolves_from",
                    label="",
                ))
            if sorted_sf:
                sf_roots.append(sorted_sf[0])

        foundation_nodes = [
            n for n in nodes
            if n.node_type == "foundation" and n.year is not None
        ]
        if foundation_nodes:
            global_root = min(foundation_nodes, key=lambda n: n.year or 9999)
            for root in sf_roots:
                if root.node_id != global_root.node_id:
                    edges.append(TechTreeEdge(
                        source=global_root.node_id,
                        target=root.node_id,
                        relation="inspires",
                        label="",
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
            importance=0.3,
            depth=0,
            representative_paper_ids=rep_ids,
        )

    @staticmethod
    def _subfield_fallback_nodes(
        scope: ScopeDefinition,
        corpus: PaperCorpus,
    ) -> list[TechTreeNode]:
        nodes: list[TechTreeNode] = []
        for i, sf in enumerate(scope.sub_fields):
            rep_ids = corpus.sub_field_mapping.get(sf.name, [])[:5]
            nodes.append(TechTreeNode(
                node_id=f"fallback_sf_{i}_{sf.name[:20].replace(' ', '_')}",
                label=sf.name,
                node_type="unverified",
                year=None,
                description=sf.description,
                importance=0.3,
                depth=0,
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
                importance=mn.importance,
                depth=mn.depth,
                representative_paper_ids=[],
            ))

        if extra:
            self._logger.info("Self-check added %d missing nodes", len(extra))
        return extra
