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
from datetime import datetime, timezone

from src.models.landscape import (
    CollaborationNetwork,
    DynamicResearchLandscape,
    ResearchGaps,
    TechTree,
)

from .agents.critic_agent import CriticAgent, CriticInput
from .agents.gap_agent import GapAgent, GapInput
from .agents.network_agent import NetworkAgent
from .agents.retrieval_agent import RetrievalAgent
from .agents.scope_agent import ScopeAgent
from .agents.taxonomy_agent import TaxonomyAgent, TaxonomyInput
from .assembler import assemble_landscape
from .memory.checkpoint import CheckpointManager
from .memory.topic_store import TopicStore
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
    *,
    task_id: str | None = None,
    on_progress: ProgressCallback = None,
) -> DynamicResearchLandscape:
    """Execute the multi-agent DRL landscape pipeline for *topic*.

    If *task_id* is provided, checkpoint/resume support is enabled:
    completed stages are persisted and skipped on re-entry.
    """
    t_total = time.perf_counter()
    ckpt = CheckpointManager()
    topic_store = TopicStore()
    restored: dict[str, str] = ckpt.load(task_id) if task_id else {}

    # ---- Layer 3: Topic Memory — cache hit check ----
    snapshot = topic_store.find(topic)
    if snapshot is not None and topic_store.is_fresh(snapshot):
        cached_landscape = topic_store.load_previous_landscape(snapshot)
        if cached_landscape is not None:
            await _notify(on_progress, "Topic cache hit — returning previous result")
            logger.info(
                "Topic cache HIT for '%s' (age=%s, papers=%d)",
                topic,
                topic_store._age(snapshot),
                snapshot.paper_count,
            )
            topic_store.touch(snapshot)
            return cached_landscape

    # ---- Stage 1: Scope Agent (warm-start from topic memory if available) ----
    await _notify(on_progress, "[1/6] Defining research scope …")
    scope: ScopeDefinition | None = None
    if "scope" in restored:
        try:
            scope = ScopeDefinition.model_validate_json(restored["scope"])
            logger.info("Scope restored from checkpoint")
        except Exception:
            logger.warning("Corrupted scope checkpoint — will re-run ScopeAgent")
    if scope is None and snapshot is not None and topic_store.is_warm_startable(snapshot) and snapshot.scope_json:
        try:
            scope = ScopeDefinition.model_validate_json(snapshot.scope_json)
            logger.info("Scope warm-started from topic memory")
            if task_id:
                ckpt.save(task_id, "scope", scope)
        except Exception:
            logger.warning("Corrupted topic snapshot scope — will re-run ScopeAgent")
    if scope is None:
        try:
            scope_agent = ScopeAgent()
            scope = await scope_agent.run(topic, on_progress=on_progress)
        except Exception as exc:
            raise LandscapePipelineError("scope", exc) from exc
        if task_id:
            ckpt.save(task_id, "scope", scope)

    logger.info(
        "Scope: complexity=%s  seeds=%d  sub_fields=%d  deprioritized=%d",
        scope.estimated_complexity,
        len(scope.seed_papers),
        len(scope.sub_fields),
        len(scope.deprioritized_sub_fields),
    )

    # ---- Main loop with Critic feedback ----
    corpus: PaperCorpus | None = None
    tech_tree: TechTree | None = None
    collab_network: CollaborationNetwork | None = None
    research_gaps: ResearchGaps | None = None
    prev_corpus_size = 0
    prev_seed_count = 0
    is_degraded = False

    if "retrieval" in restored:
        try:
            corpus = PaperCorpus.model_validate_json(restored["retrieval"])
            logger.info("Corpus restored from checkpoint (%d papers)", corpus.stats.total_papers)
        except Exception:
            logger.warning("Corrupted retrieval checkpoint — will re-run RetrievalAgent")
    if "taxonomy" in restored:
        try:
            tech_tree = TechTree.model_validate_json(restored["taxonomy"])
            logger.info("TechTree restored from checkpoint")
        except Exception:
            logger.warning("Corrupted taxonomy checkpoint — will re-run TaxonomyAgent")
    if "network" in restored:
        try:
            collab_network = CollaborationNetwork.model_validate_json(restored["network"])
            logger.info("CollaborationNetwork restored from checkpoint")
        except Exception:
            logger.warning("Corrupted network checkpoint — will re-run NetworkAgent")
    if "gaps" in restored:
        try:
            research_gaps = ResearchGaps.model_validate_json(restored["gaps"])
            logger.info("ResearchGaps restored from checkpoint")
        except Exception:
            logger.warning("Corrupted gaps checkpoint — will re-run GapAgent")

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
            if task_id:
                ckpt.save(task_id, "retrieval", corpus)

        # ---- Stage 3: Taxonomy Agent ----
        if tech_tree is None:
            await _notify(on_progress, f"[3/6] Building technology tree{retry_label} …")
            try:
                taxonomy_agent = TaxonomyAgent()
                tax_input = TaxonomyInput(corpus=corpus, scope=scope)
                tech_tree = await taxonomy_agent.run(tax_input, on_progress=on_progress)
            except Exception as exc:
                raise LandscapePipelineError("taxonomy", exc) from exc
            if task_id:
                ckpt.save(task_id, "taxonomy", tech_tree)

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
            if task_id and collab_network is not None:
                ckpt.save(task_id, "network", collab_network)
            if task_id and research_gaps is not None:
                ckpt.save(task_id, "gaps", research_gaps)

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

    if task_id:
        ckpt.clear(task_id)
        topic_store.save(
            topic=topic,
            scope_json=scope.model_dump_json(),
            corpus_stats_json=corpus.stats.model_dump_json(),
            task_id=task_id,
            paper_count=len(landscape.papers),
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


# ---------------------------------------------------------------------------
# Incremental update entry point
# ---------------------------------------------------------------------------

async def run_incremental_update(
    topic: str,
    *,
    task_id: str | None = None,
    on_progress: ProgressCallback = None,
) -> DynamicResearchLandscape:
    """Incrementally refresh an existing landscape for *topic*.

    1. Load existing landscape from topic memory.
    2. Detect new papers via S2 search.
    3. If new papers found, merge them into the existing landscape.
    4. Save updated snapshot.

    Falls back to a full pipeline run if no previous landscape exists.
    """
    from .memory.incremental import detect_new_papers, merge_increment, compute_increment  # noqa: F811
    from .memory.topic_store import TopicStore

    topic_store = TopicStore()
    snapshot = topic_store.find(topic)

    if snapshot is None:
        await _notify(on_progress, "No previous landscape found — running full pipeline")
        return await run_landscape_pipeline(topic, task_id=task_id, on_progress=on_progress)

    existing = topic_store.load_previous_landscape(snapshot)
    if existing is None:
        await _notify(on_progress, "Previous landscape data unavailable — running full pipeline")
        return await run_landscape_pipeline(topic, task_id=task_id, on_progress=on_progress)

    await _notify(on_progress, "[1/3] Detecting new papers …")
    scope = ScopeDefinition.model_validate_json(snapshot.scope_json)
    existing_pids = {p.paper_id for p in existing.papers}
    new_papers = await detect_new_papers(scope, existing_pids)

    if not new_papers:
        await _notify(on_progress, "No new papers detected — landscape is up to date")
        return existing

    await _notify(on_progress, f"[2/3] Found {len(new_papers)} new papers — merging …")
    from src.models.landscape import LandscapeIncrement
    increment = LandscapeIncrement(
        new_papers=new_papers,
        detected_at=datetime.now(timezone.utc),
    )
    updated = merge_increment(existing, increment)

    await _notify(on_progress, "[3/3] Saving updated landscape …")
    effective_task_id = task_id or snapshot.landscape_task_id
    topic_store.save(
        topic=topic,
        scope_json=scope.model_dump_json(),
        corpus_stats_json=snapshot.corpus_stats_json,
        task_id=effective_task_id,
        paper_count=len(updated.papers),
    )

    logger.info(
        "Incremental update complete: +%d papers, version %d→%d",
        len(new_papers), existing.meta.version, updated.meta.version,
    )
    return updated
