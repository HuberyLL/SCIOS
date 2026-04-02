"""Critic Agent — deterministic cross-agent consistency checker.

Replaces the previous LLM-based 5-dimension scoring with pure deterministic
checks that are 100% reproducible and don't depend on model availability.

Checks performed:
  1. paper_id referential integrity (tech tree, network, gaps → corpus)
  2. Corpus quality_flags forwarding (from RetrievalAgent)
  3. Tech tree / network non-emptiness
  4. Seed coverage ratio
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from src.models.landscape import CollaborationNetwork, ResearchGaps, TechTree

from ..schemas import PaperCorpus, QualityIssue, QualityReport, ScopeDefinition
from .base import BaseAgent, ProgressCallback

logger = logging.getLogger(__name__)

HARD_MIN_SEED_RATIO = 0.3
HARD_MIN_PAPERS = 10
HARD_REQUIRE_TECH_NODES = 1


class CriticInput(BaseModel):
    scope: ScopeDefinition
    corpus: PaperCorpus
    tech_tree: TechTree
    collaboration_network: CollaborationNetwork
    research_gaps: ResearchGaps


class CriticAgent(BaseAgent[CriticInput, QualityReport]):
    """Stage 5: deterministic quality gate — no LLM calls."""

    def __init__(self) -> None:
        super().__init__(name="CriticAgent")

    async def _execute(
        self,
        input_data: CriticInput,
        *,
        on_progress: ProgressCallback = None,
    ) -> QualityReport:
        scope = input_data.scope
        corpus = input_data.corpus
        tech_tree = input_data.tech_tree
        collab = input_data.collaboration_network
        gaps = input_data.research_gaps

        await self._notify(on_progress, "running deterministic quality checks …")

        issues: list[QualityIssue] = []
        retry_targets: list[str] = []
        corpus_pids = {p.paper_id for p in corpus.papers}

        # ---- 1. Seed coverage ----
        expected = len(scope.seed_papers)
        found = len(corpus.seed_paper_map)
        seed_ratio = found / max(expected, 1)
        if seed_ratio < HARD_MIN_SEED_RATIO:
            issues.append(QualityIssue(
                category="seed_coverage",
                severity="critical",
                description=(
                    f"Only {found}/{expected} seed papers found "
                    f"({seed_ratio:.0%} < {HARD_MIN_SEED_RATIO:.0%})"
                ),
            ))
            retry_targets.append("retrieval")

        # ---- 2. Minimum corpus size ----
        if len(corpus.papers) < HARD_MIN_PAPERS:
            issues.append(QualityIssue(
                category="corpus_size",
                severity="critical",
                description=(
                    f"Corpus has only {len(corpus.papers)} papers "
                    f"(minimum {HARD_MIN_PAPERS})"
                ),
            ))
            retry_targets.append("retrieval")

        # ---- 3. Tech tree non-empty ----
        if len(tech_tree.nodes) < HARD_REQUIRE_TECH_NODES:
            issues.append(QualityIssue(
                category="tech_tree_empty",
                severity="critical",
                description="Tech tree has no nodes — taxonomy stage likely failed",
            ))
            retry_targets.append("taxonomy")

        # ---- 4. Paper-id referential integrity (tech tree) ----
        orphan_tech = 0
        for node in tech_tree.nodes:
            for pid in node.representative_paper_ids:
                if pid not in corpus_pids:
                    orphan_tech += 1
        if orphan_tech:
            issues.append(QualityIssue(
                category="data_consistency",
                severity="warning",
                description=(
                    f"TechTree references {orphan_tech} paper_id(s) "
                    "not found in corpus"
                ),
            ))

        # ---- 5. Paper-id referential integrity (network) ----
        orphan_net = 0
        for scholar in collab.nodes:
            for pid in scholar.top_paper_ids:
                if pid not in corpus_pids:
                    orphan_net += 1
        if orphan_net:
            issues.append(QualityIssue(
                category="data_consistency",
                severity="warning",
                description=(
                    f"CollaborationNetwork references {orphan_net} paper_id(s) "
                    "not found in corpus"
                ),
            ))

        # ---- 6. Paper-id referential integrity (gaps) ----
        orphan_gap = 0
        for gap in gaps.gaps:
            for pid in gap.evidence_paper_ids:
                if pid not in corpus_pids:
                    orphan_gap += 1
        if orphan_gap:
            issues.append(QualityIssue(
                category="data_consistency",
                severity="warning",
                description=(
                    f"ResearchGaps references {orphan_gap} paper_id(s) "
                    "not found in corpus"
                ),
            ))

        # ---- 7. Network emptiness (warning only) ----
        if not collab.nodes:
            issues.append(QualityIssue(
                category="network_empty",
                severity="warning",
                description="Collaboration network has 0 scholars",
            ))

        # ---- 8. Forward quality_flags from corpus ----
        for flag in corpus.stats.quality_flags:
            severity = "critical" if flag in ("small_corpus",) else "warning"
            issues.append(QualityIssue(
                category=f"corpus_flag:{flag}",
                severity=severity,
                description=f"Corpus quality flag: {flag}",
            ))
            if flag in ("low_seed_coverage", "small_corpus") and "retrieval" not in retry_targets:
                retry_targets.append("retrieval")

        # ---- Decision ----
        has_critical = any(i.severity == "critical" for i in issues)
        passed = not has_critical
        retry_targets = list(dict.fromkeys(retry_targets))

        self._logger.info(
            "Critic: passed=%s  issues=%d (critical=%d)  retry=%s",
            passed,
            len(issues),
            sum(1 for i in issues if i.severity == "critical"),
            retry_targets,
        )

        return QualityReport(
            passed=passed,
            issues=issues,
            retry_targets=retry_targets,
            scores={},
        )
