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
import contextvars
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

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

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]] | None

MAX_RETRIES = 2

# ---------------------------------------------------------------------------
# Contextvar-based log correlation
# ---------------------------------------------------------------------------

_current_task_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_current_task_id", default="-",
)
_current_stage: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_current_stage", default="-",
)


class _PipelineLogFilter(logging.Filter):
    """Inject task_id and stage into every log record from landscape modules."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.task_id = _current_task_id.get("-")  # type: ignore[attr-defined]
        record.stage = _current_stage.get("-")  # type: ignore[attr-defined]
        return True


def install_pipeline_log_filter() -> None:
    """Attach the pipeline filter to the root landscape logger once."""
    root = logging.getLogger("src.agents.landscape")
    if not any(isinstance(f, _PipelineLogFilter) for f in root.filters):
        root.addFilter(_PipelineLogFilter())


install_pipeline_log_filter()

# ---------------------------------------------------------------------------
# Stage definitions (static registry)
# ---------------------------------------------------------------------------

_STAGES: dict[str, dict[str, Any]] = {
    "scope":     {"index": 1, "label": "Scope Agent",     "pct_start": 0,  "pct_end": 10},
    "retrieval": {"index": 2, "label": "Retrieval Agent",  "pct_start": 10, "pct_end": 45},
    "taxonomy":  {"index": 3, "label": "Taxonomy Agent",   "pct_start": 45, "pct_end": 65},
    "network":   {"index": 4, "label": "Network Agent",    "pct_start": 65, "pct_end": 73},
    "gaps":      {"index": 4, "label": "Gap Agent",        "pct_start": 73, "pct_end": 80},
    "critic":    {"index": 5, "label": "Critic Agent",     "pct_start": 80, "pct_end": 90},
    "assembler": {"index": 6, "label": "Assembler",        "pct_start": 90, "pct_end": 100},
}

STAGE_TOTAL = 6


class LandscapePipelineError(Exception):
    """Raised when a pipeline stage fails irrecoverably."""

    def __init__(self, stage: str, cause: Exception) -> None:
        self.stage = stage
        self.cause = cause
        super().__init__(f"Pipeline stage '{stage}' failed: {cause}")


# ---------------------------------------------------------------------------
# Structured progress helpers
# ---------------------------------------------------------------------------

async def _emit(
    on_progress: ProgressCallback,
    stage_id: str,
    status: str,
    message: str,
    t_stage: float,
    *,
    detail: dict | None = None,
    pct_override: int | None = None,
) -> None:
    """Send a structured ProgressEvent dict to the callback."""
    if on_progress is None:
        return
    info = _STAGES[stage_id]
    pct = pct_override if pct_override is not None else info["pct_start"]
    await on_progress({
        "type": "progress",
        "stage_id": stage_id,
        "stage_index": info["index"],
        "stage_total": STAGE_TOTAL,
        "status": status,
        "message": message,
        "progress_pct": pct,
        "elapsed_s": round(time.perf_counter() - t_stage, 1),
        "detail": detail,
    })


def _make_stage_callback(
    on_progress: ProgressCallback,
    stage_id: str,
    t_stage: float,
) -> ProgressCallback:
    """Wrap the outer callback so agent sub-messages carry stage context."""
    if on_progress is None:
        return None
    info = _STAGES[stage_id]

    async def _cb(event: dict[str, Any]) -> None:
        event.setdefault("stage_id", stage_id)
        event.setdefault("stage_index", info["index"])
        event.setdefault("stage_total", STAGE_TOTAL)
        event.setdefault("status", "running")
        event.setdefault("progress_pct", info["pct_start"])
        event.setdefault("elapsed_s", round(time.perf_counter() - t_stage, 1))
        await on_progress(event)

    return _cb


# ---------------------------------------------------------------------------
# Stage timing tracker for summary
# ---------------------------------------------------------------------------

class _StageTimer:
    """Accumulates per-stage timing and result info for final summary."""

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def record(
        self, stage_id: str, elapsed: float, status: str, info: str = "",
    ) -> None:
        label = _STAGES[stage_id]["label"]
        idx = _STAGES[stage_id]["index"]
        self._records.append({
            "stage_id": stage_id,
            "index": idx,
            "label": label,
            "elapsed": elapsed,
            "status": status,
            "info": info,
        })

    def summary(self, total_elapsed: float) -> str:
        lines = ["Pipeline Summary:"]
        for r in self._records:
            info_part = f"  ({r['info']})" if r['info'] else ""
            lines.append(
                f"  Stage {r['index']}/{STAGE_TOTAL} ({r['label']}): "
                f"{r['elapsed']:.1f}s  {r['status']}{info_part}"
            )
        lines.append(f"  Total: {total_elapsed:.1f}s")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run_landscape_pipeline(
    topic: str,
    *,
    task_id: str | None = None,
    on_progress: ProgressCallback = None,
) -> DynamicResearchLandscape:
    """Execute the multi-agent DRL landscape pipeline for *topic*."""
    t_total = time.perf_counter()
    timer = _StageTimer()

    _current_task_id.set(task_id or "-")

    ckpt = CheckpointManager()
    topic_store = TopicStore()
    restored: dict[str, str] = ckpt.load(task_id) if task_id else {}

    # ---- Layer 3: Topic Memory — cache hit check ----
    snapshot = topic_store.find(topic)
    if snapshot is not None and topic_store.is_fresh(snapshot):
        cached_landscape = topic_store.load_previous_landscape(snapshot)
        if cached_landscape is not None:
            await _emit(on_progress, "scope", "completed",
                        "Topic cache hit — returning previous result", t_total,
                        pct_override=100)
            logger.info(
                "Topic cache HIT for '%s' (age=%s, papers=%d)",
                topic, topic_store._age(snapshot), snapshot.paper_count,
            )
            topic_store.touch(snapshot)
            return cached_landscape

    # ==================================================================
    # Stage 1: Scope Agent
    # ==================================================================
    _current_stage.set("scope")
    t_stage = time.perf_counter()
    await _emit(on_progress, "scope", "running",
                "Defining research scope …", t_stage)
    logger.info("=== Stage 1/%d START: Scope Agent ===", STAGE_TOTAL)

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
            stage_cb = _make_stage_callback(on_progress, "scope", t_stage)
            scope = await scope_agent.run(topic, on_progress=stage_cb)
        except Exception as exc:
            timer.record("scope", time.perf_counter() - t_stage, "FAILED")
            raise LandscapePipelineError("scope", exc) from exc
        if task_id:
            ckpt.save(task_id, "scope", scope)

    scope_elapsed = time.perf_counter() - t_stage
    scope_info = f"complexity={scope.estimated_complexity}, seeds={len(scope.seed_papers)}, sub_fields={len(scope.sub_fields)}"
    timer.record("scope", scope_elapsed, "OK", scope_info)
    logger.info("=== Stage 1/%d DONE: %s, %.1fs ===", STAGE_TOTAL, scope_info, scope_elapsed)
    await _emit(on_progress, "scope", "completed",
                f"Scope defined — {scope.estimated_complexity} complexity",
                t_stage, detail={
                    "complexity": scope.estimated_complexity,
                    "seed_count": len(scope.seed_papers),
                    "sub_field_count": len(scope.sub_fields),
                }, pct_override=_STAGES["scope"]["pct_end"])

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

        # ==============================================================
        # Stage 2: Retrieval Agent
        # ==============================================================
        if corpus is None:
            _current_stage.set("retrieval")
            t_stage = time.perf_counter()
            await _emit(on_progress, "retrieval", "running",
                        f"Retrieving papers{retry_label} …", t_stage)
            logger.info("=== Stage 2/%d START: Retrieval Agent%s ===", STAGE_TOTAL, retry_label)
            try:
                retrieval_agent = RetrievalAgent()
                stage_cb = _make_stage_callback(on_progress, "retrieval", t_stage)
                corpus = await retrieval_agent.run(scope, on_progress=stage_cb)
            except Exception as exc:
                timer.record("retrieval", time.perf_counter() - t_stage, "FAILED")
                raise LandscapePipelineError("retrieval", exc) from exc

            ret_elapsed = time.perf_counter() - t_stage
            ret_info = f"{corpus.stats.total_papers} papers, {corpus.stats.seed_papers_found}/{corpus.stats.seed_papers_expected} seeds"
            logger.info("=== Stage 2/%d DONE: %s, %.1fs ===", STAGE_TOTAL, ret_info, ret_elapsed)

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
                    timer.record("retrieval", ret_elapsed, "OK (no improvement)", ret_info)
                    break

            timer.record("retrieval", ret_elapsed, "OK", ret_info)
            prev_corpus_size = corpus.stats.total_papers
            prev_seed_count = corpus.stats.seed_papers_found
            if task_id:
                ckpt.save(task_id, "retrieval", corpus)

            await _emit(on_progress, "retrieval", "completed",
                        f"Retrieved {corpus.stats.total_papers} papers",
                        t_stage, detail={
                            "paper_count": corpus.stats.total_papers,
                            "seed_found": corpus.stats.seed_papers_found,
                            "seed_expected": corpus.stats.seed_papers_expected,
                        }, pct_override=_STAGES["retrieval"]["pct_end"])

        # ==============================================================
        # Stage 3: Taxonomy Agent
        # ==============================================================
        if tech_tree is None:
            _current_stage.set("taxonomy")
            t_stage = time.perf_counter()
            await _emit(on_progress, "taxonomy", "running",
                        f"Building technology tree{retry_label} …", t_stage)
            logger.info("=== Stage 3/%d START: Taxonomy Agent%s ===", STAGE_TOTAL, retry_label)
            try:
                taxonomy_agent = TaxonomyAgent()
                tax_input = TaxonomyInput(corpus=corpus, scope=scope)
                stage_cb = _make_stage_callback(on_progress, "taxonomy", t_stage)
                tech_tree = await taxonomy_agent.run(tax_input, on_progress=stage_cb)
            except Exception as exc:
                timer.record("taxonomy", time.perf_counter() - t_stage, "FAILED")
                raise LandscapePipelineError("taxonomy", exc) from exc
            if task_id:
                ckpt.save(task_id, "taxonomy", tech_tree)

            tax_elapsed = time.perf_counter() - t_stage
            tax_info = f"{len(tech_tree.nodes)} nodes, {len(tech_tree.edges)} edges"
            timer.record("taxonomy", tax_elapsed, "OK", tax_info)
            logger.info("=== Stage 3/%d DONE: %s, %.1fs ===", STAGE_TOTAL, tax_info, tax_elapsed)
            await _emit(on_progress, "taxonomy", "completed",
                        f"Built tech tree with {len(tech_tree.nodes)} nodes",
                        t_stage, detail={
                            "node_count": len(tech_tree.nodes),
                            "edge_count": len(tech_tree.edges),
                        }, pct_override=_STAGES["taxonomy"]["pct_end"])

        # ==============================================================
        # Stage 4a + 4b: Network + Gaps (parallel)
        # ==============================================================
        run_network = collab_network is None
        run_gaps = research_gaps is None

        if run_network or run_gaps:
            _current_stage.set("network+gaps")
            t_stage = time.perf_counter()

            if run_network:
                await _emit(on_progress, "network", "running",
                            f"Analysing scholars{retry_label} …", t_stage)
            if run_gaps:
                await _emit(on_progress, "gaps", "running",
                            f"Identifying research gaps{retry_label} …", t_stage)

            logger.info("=== Stage 4/%d START: Network + Gaps (parallel)%s ===", STAGE_TOTAL, retry_label)

            tasks: list[tuple[str, Any]] = []
            if run_network:
                network_agent = NetworkAgent()
                net_cb = _make_stage_callback(on_progress, "network", t_stage)
                tasks.append(("network", network_agent.run(corpus, on_progress=net_cb)))
            if run_gaps:
                gap_agent = GapAgent()
                gap_input = GapInput(corpus=corpus, tech_tree=tech_tree, scope=scope)
                gap_cb = _make_stage_callback(on_progress, "gaps", t_stage)
                tasks.append(("gaps", gap_agent.run(gap_input, on_progress=gap_cb)))

            results = await asyncio.gather(
                *[t[1] for t in tasks],
                return_exceptions=True,
            )

            for (name, _), result in zip(tasks, results):
                if isinstance(result, Exception):
                    logger.error("%s agent failed: %s", name, result)
                    if name == "network":
                        collab_network = CollaborationNetwork(nodes=[], edges=[])
                        await _emit(on_progress, "network", "failed",
                                    "Network analysis failed — using empty fallback", t_stage)
                    elif name == "gaps":
                        research_gaps = ResearchGaps(gaps=[], summary="Analysis failed.")
                        await _emit(on_progress, "gaps", "failed",
                                    "Gap analysis failed — using empty fallback", t_stage)
                else:
                    if name == "network":
                        collab_network = result
                    elif name == "gaps":
                        research_gaps = result

            if task_id and collab_network is not None:
                ckpt.save(task_id, "network", collab_network)
            if task_id and research_gaps is not None:
                ckpt.save(task_id, "gaps", research_gaps)

            s4_elapsed = time.perf_counter() - t_stage
            if run_network and collab_network is not None:
                net_info = f"{len(collab_network.nodes)} scholars"
                timer.record("network", s4_elapsed, "OK", net_info)
                await _emit(on_progress, "network", "completed",
                            f"Found {len(collab_network.nodes)} scholars",
                            t_stage, detail={"scholar_count": len(collab_network.nodes)},
                            pct_override=_STAGES["network"]["pct_end"])
            if run_gaps and research_gaps is not None:
                gap_info = f"{len(research_gaps.gaps)} gaps"
                timer.record("gaps", s4_elapsed, "OK", gap_info)
                await _emit(on_progress, "gaps", "completed",
                            f"Identified {len(research_gaps.gaps)} research gaps",
                            t_stage, detail={"gap_count": len(research_gaps.gaps)},
                            pct_override=_STAGES["gaps"]["pct_end"])

            logger.info("=== Stage 4/%d DONE: %.1fs ===", STAGE_TOTAL, s4_elapsed)

        # ==============================================================
        # Stage 5: Critic Agent
        # ==============================================================
        _current_stage.set("critic")
        t_stage = time.perf_counter()
        await _emit(on_progress, "critic", "running",
                    f"Quality review{retry_label} …", t_stage)
        logger.info("=== Stage 5/%d START: Critic Agent%s ===", STAGE_TOTAL, retry_label)

        try:
            critic_agent = CriticAgent()
            stage_cb = _make_stage_callback(on_progress, "critic", t_stage)
            critic_input = CriticInput(
                scope=scope,
                corpus=corpus,
                tech_tree=tech_tree,
                collaboration_network=collab_network,
                research_gaps=research_gaps,
            )
            quality = await critic_agent.run(critic_input, on_progress=stage_cb)
        except Exception as exc:
            crit_elapsed = time.perf_counter() - t_stage
            logger.error("Critic agent failed: %s — skipping quality gate", exc)
            timer.record("critic", crit_elapsed, "SKIPPED (error)")
            await _emit(on_progress, "critic", "completed",
                        "Quality review skipped due to error", t_stage,
                        pct_override=_STAGES["critic"]["pct_end"])
            break

        crit_elapsed = time.perf_counter() - t_stage
        if quality.passed:
            logger.info("=== Stage 5/%d DONE: PASS, %.1fs ===", STAGE_TOTAL, crit_elapsed)
            timer.record("critic", crit_elapsed, "PASS")
            await _emit(on_progress, "critic", "completed",
                        "Quality review passed", t_stage,
                        pct_override=_STAGES["critic"]["pct_end"])
            break

        logger.warning(
            "Critic FAILED (attempt %d/%d): retry_targets=%s, issues=%d",
            attempt + 1, 1 + MAX_RETRIES,
            quality.retry_targets, len(quality.issues),
        )

        if attempt >= MAX_RETRIES:
            logger.warning("Max retries reached, proceeding with current results")
            is_degraded = any(i.severity == "critical" for i in quality.issues)
            timer.record("critic", crit_elapsed, "FAIL (max retries)")
            await _emit(on_progress, "critic", "completed",
                        "Quality review: proceeding with degraded results", t_stage,
                        pct_override=_STAGES["critic"]["pct_end"])
            break

        timer.record("critic", crit_elapsed, f"FAIL → retry {attempt + 1}")
        await _emit(on_progress, "critic", "completed",
                    f"Quality review failed — retrying (attempt {attempt + 1})", t_stage,
                    pct_override=_STAGES["critic"]["pct_end"])

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

    # ==================================================================
    # Stage 6: Assembler
    # ==================================================================
    _current_stage.set("assembler")
    t_stage = time.perf_counter()
    await _emit(on_progress, "assembler", "running",
                "Assembling final landscape …", t_stage)
    logger.info("=== Stage 6/%d START: Assembler ===", STAGE_TOTAL)

    landscape = assemble_landscape(
        topic=topic,
        papers=corpus.papers,
        tech_tree=tech_tree,
        collaboration_network=collab_network,
        research_gaps=research_gaps,
        quality="degraded" if is_degraded else "complete",
    )

    asm_elapsed = time.perf_counter() - t_stage
    asm_info = f"papers={len(landscape.papers)}, quality={landscape.meta.quality}"
    timer.record("assembler", asm_elapsed, "OK", asm_info)
    logger.info("=== Stage 6/%d DONE: %s, %.1fs ===", STAGE_TOTAL, asm_info, asm_elapsed)

    await _emit(on_progress, "assembler", "completed",
                "Landscape assembled", t_stage,
                detail={
                    "paper_count": len(landscape.papers),
                    "tech_nodes": len(landscape.tech_tree.nodes),
                    "scholars": len(landscape.collaboration_network.nodes),
                    "gaps": len(landscape.research_gaps.gaps),
                    "quality": landscape.meta.quality,
                }, pct_override=100)

    if task_id:
        ckpt.clear(task_id)
        topic_store.save(
            topic=topic,
            scope_json=scope.model_dump_json(),
            corpus_stats_json=corpus.stats.model_dump_json(),
            task_id=task_id,
            paper_count=len(landscape.papers),
        )

    total_elapsed = time.perf_counter() - t_total
    logger.info("\n%s", timer.summary(total_elapsed))
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

    Falls back to a full pipeline run if no previous landscape exists.
    """
    from .memory.incremental import detect_new_papers, merge_increment  # noqa: F811
    from .memory.topic_store import TopicStore as TS

    _current_task_id.set(task_id or "-")

    topic_store = TS()
    snapshot = topic_store.find(topic)

    if snapshot is None:
        await _emit(on_progress, "scope", "running",
                    "No previous landscape found — running full pipeline",
                    time.perf_counter())
        return await run_landscape_pipeline(topic, task_id=task_id, on_progress=on_progress)

    existing = topic_store.load_previous_landscape(snapshot)
    if existing is None:
        await _emit(on_progress, "scope", "running",
                    "Previous landscape data unavailable — running full pipeline",
                    time.perf_counter())
        return await run_landscape_pipeline(topic, task_id=task_id, on_progress=on_progress)

    t0 = time.perf_counter()
    await _emit(on_progress, "retrieval", "running",
                "Detecting new papers …", t0, pct_override=20)
    scope = ScopeDefinition.model_validate_json(snapshot.scope_json)
    existing_pids = {p.paper_id for p in existing.papers}
    new_papers = await detect_new_papers(scope, existing_pids)

    if not new_papers:
        await _emit(on_progress, "assembler", "completed",
                    "No new papers detected — landscape is up to date",
                    t0, pct_override=100)
        return existing

    await _emit(on_progress, "assembler", "running",
                f"Found {len(new_papers)} new papers — merging …",
                t0, pct_override=60)
    from src.models.landscape import LandscapeIncrement
    increment = LandscapeIncrement(
        new_papers=new_papers,
        detected_at=datetime.now(timezone.utc),
    )
    updated = merge_increment(existing, increment)

    await _emit(on_progress, "assembler", "completed",
                "Updated landscape saved", t0, pct_override=100)
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
