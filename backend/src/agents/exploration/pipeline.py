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

from .planner import generate_search_plan
from .retriever import fetch_all_context
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
    1. **Planner** – LLM decomposes topic into keywords & queries.
    2. **Retriever** – concurrent tool calls fetch papers & web data.
    3. **Synthesizer** – LLM distills evidence into structured report.
    """
    t_total = time.perf_counter()

    # --- Stage 1: Plan ---
    await _notify(on_progress, "[1/3] Planning search strategy …")
    logger.info("[1/3] Planning search strategy for: %s", topic)
    t0 = time.perf_counter()
    plan = await generate_search_plan(topic)
    logger.info("[1/3] Planner done  (%.1fs)", time.perf_counter() - t0)

    # --- Stage 2: Retrieve ---
    await _notify(
        on_progress,
        f"[2/3] Retrieving papers & web data ({len(plan.paper_keywords)} keywords) …",
    )
    logger.info(
        "[2/3] Retrieving data  keywords=%d  web_queries=%d",
        len(plan.paper_keywords),
        len(plan.web_queries),
    )
    t0 = time.perf_counter()
    raw_data = await fetch_all_context(plan)
    logger.info("[2/3] Retriever done  (%.1fs)", time.perf_counter() - t0)

    # --- Stage 3: Synthesize ---
    await _notify(on_progress, "[3/3] Synthesizing exploration report …")
    logger.info("[3/3] Synthesizing exploration report")
    t0 = time.perf_counter()
    report = await synthesize_report(topic, raw_data)
    logger.info("[3/3] Synthesizer done  (%.1fs)", time.perf_counter() - t0)

    logger.info(
        "Exploration complete  total=%.1fs  concepts=%d  scholars=%d  papers=%d",
        time.perf_counter() - t_total,
        len(report.core_concepts),
        len(report.key_scholars),
        len(report.must_read_papers),
    )
    return report
