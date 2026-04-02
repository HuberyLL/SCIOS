"""Multi-Agent Orchestrator for the Dynamic Research Landscape pipeline.

Architecture:
  Stage 1: Scope Agent      (topic -> ScopeDefinition)
  Stage 2: Retrieval Agent   (scope -> PaperCorpus)
  Stage 3: Taxonomy Agent    (corpus + scope -> TechTree)
  Stage 4a/b: Network + Gap  (parallel)
  Stage 5: Critic Agent      (deterministic quality gate -> pass/retry)
  Stage 6: Assembler         (merge -> DynamicResearchLandscape)

Each stage is wrapped in try/except.  The Critic can trigger up to
MAX_RETRIES re-runs, but retries are skipped if no improvement is detected.
When max retries are exhausted with critical quality flags, the output
carries ``meta.quality = "degraded"``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from src.models.landscape import (
    CollaborationNetwork,
    DynamicResearchLandscape,
    ResearchGaps,
)

from .agents.critic_agent import CriticAgent, CriticInput
from .agents.gap_agent import GapAgent, GapInput
from .agents.network_agent import NetworkAgent
from .agents.retrieval_agent import RetrievalAgent
from .agents.scope_agent import ScopeAgent
from .agents.taxonomy_agent import TaxonomyAgent, TaxonomyInput
from .assembler import assemble_landscape
from .schemas import PaperCorpus, ScopeDefinition

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], Awaitable[None]] | None

MAX_RETRIES = 2


class LandscapePipelineError(Exception):
    """Raised when a pipeline stage fails irrecoverably."""

    def __init__(self, stage: str, cause: Exception) -> None:
        self.stage = stage
        self.cause = cause
        super().__init__(f"Pipeline stage '{stage}' failed: {cause}")


async def _notify(on_progress: ProgressCallback, message: str) -> None:
    if on_progress is not None:
        await on_progress(message)


async def run_landscape_pipeline(
    topic: str,
    on_progress: ProgressCallback = None,
) -> DynamicResearchLandscape:
    """Execute the multi-agent DRL landscape pipeline for *topic*."""
    t_total = time.perf_counter()

    # ---- Stage 1: Scope Agent ----
    await _notify(on_progress, "[1/6] Defining research scope …")
    try:
        scope_agent = ScopeAgent()
        scope = await scope_agent.run(topic, on_progress=on_progress)
    except Exception as exc:
        raise LandscapePipelineError("scope", exc) from exc

    logger.info(
        "Scope: complexity=%s  seeds=%d  sub_fields=%d  deprioritized=%d",
        scope.estimated_complexity,
        len(scope.seed_papers),
        len(scope.sub_fields),
        len(scope.deprioritized_sub_fields),
    )

    # ---- Main loop with Critic feedback ----
    corpus: PaperCorpus | None = None
    tech_tree = None
    collab_network = None
    research_gaps = None
    prev_corpus_size = 0
    prev_seed_count = 0
    is_degraded = False

    for attempt in range(1 + MAX_RETRIES):
        retry_label = f" (retry {attempt})" if attempt > 0 else ""

        # ---- Stage 2: Retrieval Agent ----
        if corpus is None:
            await _notify(on_progress, f"[2/6] Retrieving papers{retry_label} …")
            try:
                retrieval_agent = RetrievalAgent()
                corpus = await retrieval_agent.run(scope, on_progress=on_progress)
            except Exception as exc:
                raise LandscapePipelineError("retrieval", exc) from exc

            logger.info(
                "Corpus: %d papers, %d/%d seeds found, flags=%s",
                corpus.stats.total_papers,
                corpus.stats.seed_papers_found,
                corpus.stats.seed_papers_expected,
                corpus.stats.quality_flags,
            )

            # Retry improvement detection: skip if no progress
            if attempt > 0:
                improved = (
                    corpus.stats.total_papers > prev_corpus_size
                    or corpus.stats.seed_papers_found > prev_seed_count
                )
                if not improved:
                    logger.warning(
                        "Retry %d produced no improvement (%d papers, %d seeds) — stopping retries",
                        attempt, corpus.stats.total_papers, corpus.stats.seed_papers_found,
                    )
                    is_degraded = any(
                        f in corpus.stats.quality_flags
                        for f in ("small_corpus", "low_seed_coverage")
                    )
                    break

            prev_corpus_size = corpus.stats.total_papers
            prev_seed_count = corpus.stats.seed_papers_found

        # ---- Stage 3: Taxonomy Agent ----
        if tech_tree is None:
            await _notify(on_progress, f"[3/6] Building technology tree{retry_label} …")
            try:
                taxonomy_agent = TaxonomyAgent()
                tax_input = TaxonomyInput(corpus=corpus, scope=scope)
                tech_tree = await taxonomy_agent.run(tax_input, on_progress=on_progress)
            except Exception as exc:
                raise LandscapePipelineError("taxonomy", exc) from exc

        # ---- Stage 4a + 4b: Network + Gaps (parallel) ----
        run_network = collab_network is None
        run_gaps = research_gaps is None

        if run_network or run_gaps:
            await _notify(
                on_progress,
                f"[4/6] Analysing scholars & research gaps{retry_label} …",
            )
            tasks = []
            if run_network:
                network_agent = NetworkAgent()
                tasks.append(("network", network_agent.run(corpus, on_progress=on_progress)))
            if run_gaps:
                gap_agent = GapAgent()
                gap_input = GapInput(corpus=corpus, tech_tree=tech_tree, scope=scope)
                tasks.append(("gaps", gap_agent.run(gap_input, on_progress=on_progress)))

            results = await asyncio.gather(
                *[t[1] for t in tasks],
                return_exceptions=True,
            )

            for (name, _), result in zip(tasks, results):
                if isinstance(result, Exception):
                    logger.error("%s agent failed: %s", name, result)
                    if name == "network":
                        collab_network = CollaborationNetwork(nodes=[], edges=[])
                    elif name == "gaps":
                        research_gaps = ResearchGaps(
                            gaps=[], summary="Analysis failed.",
                        )
                else:
                    if name == "network":
                        collab_network = result
                    elif name == "gaps":
                        research_gaps = result

        # ---- Stage 5: Critic Agent ----
        await _notify(on_progress, f"[5/6] Quality review{retry_label} …")
        try:
            critic_agent = CriticAgent()
            critic_input = CriticInput(
                scope=scope,
                corpus=corpus,
                tech_tree=tech_tree,
                collaboration_network=collab_network,
                research_gaps=research_gaps,
            )
            quality = await critic_agent.run(critic_input, on_progress=on_progress)
        except Exception as exc:
            logger.error("Critic agent failed: %s — skipping quality gate", exc)
            break

        if quality.passed:
            logger.info("Critic PASSED (attempt %d)", attempt + 1)
            break

        logger.warning(
            "Critic FAILED (attempt %d/%d): retry_targets=%s, issues=%d",
            attempt + 1, 1 + MAX_RETRIES,
            quality.retry_targets,
            len(quality.issues),
        )

        if attempt >= MAX_RETRIES:
            logger.warning("Max retries reached, proceeding with current results")
            is_degraded = any(i.severity == "critical" for i in quality.issues)
            break

        # Selective reset for retry
        if "retrieval" in quality.retry_targets:
            corpus = None
            tech_tree = None
            collab_network = None
            research_gaps = None
        elif "taxonomy" in quality.retry_targets:
            tech_tree = None
            research_gaps = None
        if "network" in quality.retry_targets:
            collab_network = None
        if "gaps" in quality.retry_targets:
            research_gaps = None

    # ---- Stage 6: Assembler ----
    await _notify(on_progress, "[6/6] Assembling final landscape …")
    landscape = assemble_landscape(
        topic=topic,
        papers=corpus.papers,
        tech_tree=tech_tree,
        collaboration_network=collab_network,
        research_gaps=research_gaps,
        quality="degraded" if is_degraded else "complete",
    )

    logger.info(
        "Landscape pipeline complete  total=%.1fs  papers=%d  "
        "tech_nodes=%d  scholars=%d  gaps=%d  quality=%s",
        time.perf_counter() - t_total,
        len(landscape.papers),
        len(landscape.tech_tree.nodes),
        len(landscape.collaboration_network.nodes),
        len(landscape.research_gaps.gaps),
        landscape.meta.quality,
    )
    return landscape
