"""Topic Exploration pipeline — the single public entry-point.

Usage::

    from src.agents.exploration import run_exploration

    report = await run_exploration("Transformer applications in healthcare")
    print(report.model_dump_json(indent=2))
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from src.core.config import get_settings

from ..tools.sources import SOURCE_REGISTRY
from .planner import generate_search_plan
from .retriever import fetch_all_context
from .router import route_sources
from .schemas import ExplorationReport
from .synthesizer import synthesize_report

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], Awaitable[None]] | None


async def _notify(on_progress: ProgressCallback, message: str) -> None:
    if on_progress is not None:
        await on_progress(message)


async def run_exploration(
    topic: str,
    on_progress: ProgressCallback = None,
) -> ExplorationReport:
    """Execute the full Exploration pipeline for *topic*.

    Parameters
    ----------
    topic:
        The research topic to explore.
    on_progress:
        Optional async callback invoked with a human-readable progress
        message at each stage boundary.  Safe to leave as ``None``.

    Stages
    ------
    1. **Planner** – LLM decomposes topic into keywords, queries & source hints.
    2. **Router** – validate hints, produce bounded source list (pure Python).
    3. **Retriever** – concurrent tool calls fetch papers & web data.
    4. **Synthesizer** – LLM distills evidence into structured report.
    """
    cfg = get_settings()
    t_total = time.perf_counter()

    # --- Stage 1: Plan ---
    await _notify(on_progress, "[1/4] Planning search strategy …")
    logger.info("[1/4] Planning search strategy for: %s", topic)
    t0 = time.perf_counter()
    plan = await generate_search_plan(topic)
    logger.info("[1/4] Planner done  (%.1fs)", time.perf_counter() - t0)

    # --- Stage 2: Route (no LLM, pure logic) ---
    await _notify(on_progress, "[2/4] Routing to relevant sources …")
    routed = route_sources(
        plan,
        registry=SOURCE_REGISTRY,
        enabled=cfg.source_routing_enabled,
        confidence_threshold=cfg.source_routing_confidence_threshold,
        max_sources=cfg.source_routing_max_sources,
    )
    logger.info(
        "[2/4] Router  primary=%s  secondary=%s  reason=%s",
        routed.primary, routed.secondary, routed.reason,
    )

    # --- Stage 3: Retrieve ---
    await _notify(
        on_progress,
        f"[3/4] Retrieving papers & web data ({len(plan.paper_keywords)} keywords, "
        f"{len(routed.primary)} sources) …",
    )
    logger.info(
        "[3/4] Retrieving data  keywords=%d  web_queries=%d  sources=%s",
        len(plan.paper_keywords),
        len(plan.web_queries),
        routed.primary,
    )
    t0 = time.perf_counter()
    raw_data = await fetch_all_context(
        plan,
        routed,
        stage_b_enabled=cfg.source_routing_stage_b_enabled,
        min_papers_stage_b=cfg.source_routing_min_papers_stage_b,
    )
    logger.info("[3/4] Retriever done  (%.1fs)", time.perf_counter() - t0)

    # --- Stage 4: Synthesize ---
    await _notify(on_progress, "[4/4] Synthesizing exploration report …")
    logger.info("[4/4] Synthesizing exploration report")
    t0 = time.perf_counter()
    report = await synthesize_report(topic, raw_data, max_papers=cfg.synthesizer_max_papers)
    logger.info("[4/4] Synthesizer done  (%.1fs)", time.perf_counter() - t0)

    logger.info(
        "Exploration complete  total=%.1fs  concepts=%d  scholars=%d  papers=%d",
        time.perf_counter() - t_total,
        len(report.core_concepts),
        len(report.key_scholars),
        len(report.must_read_papers),
    )
    return report
