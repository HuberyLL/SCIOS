"""Gap Analyst Agent — per-branch Map-Reduce gap identification.

Architecture aligned with Map-Reduce pattern:
  Map:    Each tech tree node (branch) gets its own gap analysis
  Reduce: Branch-level gaps are merged, deduplicated, and synthesized

This replaces the old monolithic approach of stuffing ALL frontier papers
and ALL tech tree nodes into a single LLM prompt.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime

from pydantic import BaseModel, Field

from src.models.landscape import ResearchGap, ResearchGaps, TechTree, TechTreeNode
from src.models.paper import PaperResult

from ...llm_client import call_llm
from ..prompts.gap_prompts import (
    GAP_ANALYSIS_SYSTEM,
    GAP_ANALYSIS_USER,
    GAP_MERGE_SYSTEM,
    GAP_MERGE_USER,
)
from ..schemas import PaperCorpus, ScopeDefinition
from .base import BaseAgent, ProgressCallback

logger = logging.getLogger(__name__)

FRONTIER_YEARS = 2
MAX_ABSTRACT_CHARS = 500
MAX_BRANCH_PAPERS_IN_PROMPT = 30


class GapInput(BaseModel):
    corpus: PaperCorpus
    tech_tree: TechTree
    scope: ScopeDefinition


class _GapItem(BaseModel):
    gap_id: str
    title: str
    description: str
    evidence_paper_ids: list[str] = Field(default_factory=list)
    potential_approaches: list[str] = Field(default_factory=list)
    impact: str = Field(default="medium")


class _BranchGapResult(BaseModel):
    """LLM output for per-branch gap analysis."""
    gaps: list[_GapItem] = Field(default_factory=list)
    summary: str = Field(default="")


class _MergedGapResult(BaseModel):
    """LLM output for merged gap analysis."""
    gaps: list[_GapItem] = Field(default_factory=list)
    summary: str = Field(default="")


class GapAgent(BaseAgent[GapInput, ResearchGaps]):
    """Stage 4b: identify research gaps via per-branch analysis + merge."""

    def __init__(self) -> None:
        super().__init__(name="GapAgent")

    async def _execute(
        self,
        input_data: GapInput,
        *,
        on_progress: ProgressCallback = None,
    ) -> ResearchGaps:
        corpus = input_data.corpus
        tech_tree = input_data.tech_tree
        scope = input_data.scope
        valid_pids = {p.paper_id for p in corpus.papers}
        lookup = {p.paper_id: p for p in corpus.papers}

        # Build frontier paper index
        frontier = self._select_frontier_papers(corpus)
        self._logger.info("Selected %d frontier papers", len(frontier))

        # Structural analysis
        stale_branches = self._find_stale_branches(tech_tree, corpus)
        no_alt_branches = self._find_no_alternatives(tech_tree)
        stale_map = {s.split(" (")[0]: s for s in stale_branches}
        no_alt_map = {n.split(" (")[0]: n for n in no_alt_branches}

        # Map phase: analyse each branch in parallel
        await self._notify(on_progress, "analysing gaps per branch …")
        branch_tasks = []
        for node in tech_tree.nodes:
            branch_papers = self._papers_for_branch(node, corpus, lookup)
            branch_frontier = self._frontier_for_branch(node, frontier, corpus)
            stale_text = stale_map.get(node.node_id, "none")
            no_alt_text = no_alt_map.get(node.node_id, "none")

            branch_tasks.append(
                self._analyze_branch(
                    scope, node, branch_papers, branch_frontier,
                    stale_text, no_alt_text,
                )
            )

        branch_results = await asyncio.gather(*branch_tasks, return_exceptions=True)

        all_branch_gaps: list[tuple[str, _BranchGapResult]] = []
        succeeded = 0
        failed = 0
        for node, result in zip(tech_tree.nodes, branch_results):
            if isinstance(result, Exception):
                failed += 1
                self._logger.warning("Branch gap analysis failed for '%s': %s", node.label, result)
                continue
            succeeded += 1
            if result and result.gaps:
                all_branch_gaps.append((node.label, result))

        total_branches = len(tech_tree.nodes)
        self._logger.info(
            "Branch analysis: %d/%d succeeded, %d failed",
            succeeded, total_branches, failed,
        )

        if not all_branch_gaps:
            if failed == total_branches:
                summary = (
                    f"Gap analysis failed for all {total_branches} branches "
                    "— results unavailable."
                )
            else:
                summary = (
                    f"No research gaps identified across {succeeded}/{total_branches} "
                    "successfully analyzed branches."
                )
            return ResearchGaps(gaps=[], summary=summary)

        # Reduce phase: merge and deduplicate
        await self._notify(on_progress, "merging gaps from %d branches …" % len(all_branch_gaps))
        merged = await self._merge_branch_gaps(scope, all_branch_gaps)

        # Deduplicate by gap_id — merge evidence and keep higher impact
        impact_rank = {"high": 3, "medium": 2, "low": 1}
        seen_gaps: dict[str, ResearchGap] = {}
        for g in merged.gaps:
            impact = g.impact if g.impact in ("high", "medium", "low") else "medium"
            clean_pids = [pid for pid in g.evidence_paper_ids if pid in valid_pids]
            gap = ResearchGap(
                gap_id=g.gap_id,
                title=g.title,
                description=g.description,
                evidence_paper_ids=clean_pids,
                potential_approaches=g.potential_approaches,
                impact=impact,
            )
            if g.gap_id in seen_gaps:
                existing = seen_gaps[g.gap_id]
                merged_evidence = list(dict.fromkeys(
                    existing.evidence_paper_ids + gap.evidence_paper_ids
                ))
                keep_impact = (
                    gap.impact
                    if impact_rank.get(gap.impact, 0) > impact_rank.get(existing.impact, 0)
                    else existing.impact
                )
                seen_gaps[g.gap_id] = existing.model_copy(update={
                    "evidence_paper_ids": merged_evidence,
                    "impact": keep_impact,
                })
            else:
                seen_gaps[g.gap_id] = gap

        gaps = list(seen_gaps.values())

        branch_stats = f"Analyzed {succeeded}/{total_branches} branches successfully."
        summary = f"{merged.summary} {branch_stats}" if merged.summary else branch_stats

        return ResearchGaps(gaps=gaps, summary=summary)

    # ------------------------------------------------------------------
    # Map: per-branch analysis
    # ------------------------------------------------------------------

    async def _analyze_branch(
        self,
        scope: ScopeDefinition,
        node: TechTreeNode,
        branch_papers: list[PaperResult],
        frontier: list[PaperResult],
        stale_text: str,
        no_alt_text: str,
    ) -> _BranchGapResult:
        branch_papers_text = "\n".join(
            self._format_paper(p) for p in branch_papers[:MAX_BRANCH_PAPERS_IN_PROMPT]
        ) or "(none)"

        frontier_text = "\n\n".join(
            self._format_paper(p) for p in frontier
        ) or "(none)"

        user_msg = GAP_ANALYSIS_USER.format(
            topic=scope.topic,
            topic_description=scope.topic_description,
            branch_label=node.label,
            branch_description=f"{node.node_id} ({node.label}, {node.year}): {node.description}",
            branch_papers_text=branch_papers_text,
            frontier_papers_text=frontier_text,
            stale_text=stale_text,
            no_alternative_text=no_alt_text,
        )

        return await call_llm(
            [
                {"role": "system", "content": GAP_ANALYSIS_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            response_format=_BranchGapResult,
        )

    # ------------------------------------------------------------------
    # Reduce: merge branch gaps
    # ------------------------------------------------------------------

    async def _merge_branch_gaps(
        self,
        scope: ScopeDefinition,
        branch_gaps: list[tuple[str, _BranchGapResult]],
    ) -> _MergedGapResult:
        all_text_parts: list[str] = []
        for branch_label, result in branch_gaps:
            gap_lines = "\n".join(
                f"  - [{g.gap_id}] {g.title} (impact={g.impact}): {g.description}"
                for g in result.gaps
            )
            all_text_parts.append(f"Branch: {branch_label}\n{gap_lines}")

        all_text = "\n\n".join(all_text_parts)

        try:
            return await call_llm(
                [
                    {"role": "system", "content": GAP_MERGE_SYSTEM},
                    {"role": "user", "content": GAP_MERGE_USER.format(
                        topic=scope.topic,
                        branch_count=len(branch_gaps),
                        all_branch_gaps_text=all_text,
                    )},
                ],
                response_format=_MergedGapResult,
            )
        except Exception:
            self._logger.warning("Gap merge LLM failed, concatenating raw results")
            all_gaps: list[_GapItem] = []
            for _, result in branch_gaps:
                all_gaps.extend(result.gaps)
            return _MergedGapResult(
                gaps=all_gaps,
                summary="Merged from branch analyses (no LLM dedup).",
            )

    # ------------------------------------------------------------------
    # Helpers: paper selection per branch
    # ------------------------------------------------------------------

    @staticmethod
    def _papers_for_branch(
        node: TechTreeNode,
        corpus: PaperCorpus,
        lookup: dict[str, PaperResult],
    ) -> list[PaperResult]:
        """Get papers associated with a tech tree node."""
        papers = [
            lookup[pid] for pid in node.representative_paper_ids
            if pid in lookup
        ]
        papers.sort(key=lambda p: p.citation_count, reverse=True)
        return papers

    @staticmethod
    def _frontier_for_branch(
        node: TechTreeNode,
        all_frontier: list[PaperResult],
        corpus: PaperCorpus,
    ) -> list[PaperResult]:
        """Select frontier papers relevant to a specific branch.

        Uses the node's representative papers' citation neighbourhood
        to find related frontier papers.
        """
        node_pids = set(node.representative_paper_ids)
        related: list[PaperResult] = []

        node_cites: set[str] = set()
        for pid in node_pids:
            node_cites.update(corpus.citation_graph.get(pid, []))
            node_cites.update(corpus.reference_graph.get(pid, []))
        node_cites.update(node_pids)

        for fp in all_frontier:
            if fp.paper_id in node_cites:
                related.append(fp)

        if not related:
            return all_frontier[:5]
        return related

    # ------------------------------------------------------------------
    # Helpers: frontier papers & structural analysis
    # ------------------------------------------------------------------

    @staticmethod
    def _select_frontier_papers(corpus: PaperCorpus) -> list[PaperResult]:
        """Pick the most-cited papers from the last FRONTIER_YEARS years."""
        current_year = datetime.now().year
        cutoff = current_year - FRONTIER_YEARS

        recent: list[PaperResult] = []
        for p in corpus.papers:
            year_str = (p.published_date or "")[:4]
            if year_str.isdigit() and int(year_str) >= cutoff:
                recent.append(p)

        recent.sort(key=lambda p: p.citation_count, reverse=True)
        return recent

    @staticmethod
    def _find_stale_branches(
        tech_tree: TechTree, corpus: PaperCorpus,
    ) -> list[str]:
        current_year = datetime.now().year
        lookup = {p.paper_id: p for p in corpus.papers}
        stale: list[str] = []

        for node in tech_tree.nodes:
            if not node.representative_paper_ids:
                stale.append(f"{node.node_id} ({node.label}): no linked papers")
                continue
            years = []
            for pid in node.representative_paper_ids:
                p = lookup.get(pid)
                if p:
                    y_str = (p.published_date or "")[:4]
                    if y_str.isdigit():
                        years.append(int(y_str))
            if years and max(years) < current_year - 3:
                stale.append(
                    f"{node.node_id} ({node.label}): latest paper from {max(years)}"
                )

        return stale

    @staticmethod
    def _find_no_alternatives(tech_tree: TechTree) -> list[str]:
        has_alternative: set[str] = set()
        for edge in tech_tree.edges:
            if edge.relation == "alternative_to":
                has_alternative.add(edge.source)
                has_alternative.add(edge.target)

        results: list[str] = []
        for node in tech_tree.nodes:
            if node.node_id not in has_alternative:
                incoming = [
                    e for e in tech_tree.edges
                    if e.target == node.node_id and e.relation in ("extends", "evolves_from")
                ]
                if incoming:
                    results.append(f"{node.node_id} ({node.label}): no competing alternatives")

        return results

    @staticmethod
    def _format_paper(p: PaperResult) -> str:
        abstract = (p.abstract or "")[:MAX_ABSTRACT_CHARS]
        if len(p.abstract or "") > MAX_ABSTRACT_CHARS:
            abstract += "…"
        return (
            f"  paper_id={p.paper_id}\n"
            f"  Title: {p.title}\n"
            f"  Year: {p.published_date}  Citations: {p.citation_count}\n"
            f"  Abstract: {abstract}"
        )
