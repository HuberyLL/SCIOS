"""DRL Landscape pipeline — the single public entry-point.

Usage::

    from src.agents.landscape import run_landscape_pipeline

    landscape = await run_landscape_pipeline("Vision Transformers")
    print(landscape.model_dump_json(indent=2))
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from src.models.landscape import DynamicResearchLandscape

from ..exploration.planner import generate_search_plan
from .analyzer import analyze_landscape
from .assembler import assemble_landscape
from .graph_builder import build_collaboration_network
from .retriever import fetch_enriched_context

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], Awaitable[None]] | None


async def _notify(on_progress: ProgressCallback, message: str) -> None:
    if on_progress is not None:
        await on_progress(message)


async def run_landscape_pipeline(
    topic: str,
    on_progress: ProgressCallback = None,
) -> DynamicResearchLandscape:
    """Execute the full DRL Landscape pipeline for *topic*.

    Stages
    ------
    1. **Planner** (reused) -- LLM decomposes topic into search plan.
    2. **Enriched Retriever** -- S2 + Tavily, author details, references,
       citations.
    3a. **GraphBuilder** (data-driven) -- CollaborationNetwork from
        co-authorship.
    3b. **LLM Analyzer** -- TechTree + ResearchGaps.
        *3a and 3b run concurrently.*
    4. **Assembler** -- merge, sanitise references, emit final JSON.
    """
    t_total = time.perf_counter()

    # --- Stage 1: Plan (reused) ---
    await _notify(on_progress, "[1/4] Planning search strategy …")
    logger.info("[1/4] Planning search strategy for: %s", topic)
    t0 = time.perf_counter()
    plan = await generate_search_plan(topic)
    logger.info("[1/4] Planner done  (%.1fs)", time.perf_counter() - t0)

    # --- Stage 2: Enriched Retrieve (S2 + Tavily) ---
    await _notify(
        on_progress,
        f"[2/4] Retrieving enriched data ({len(plan.paper_keywords)} keywords) …",
    )
    t0 = time.perf_counter()
    enriched_data = await fetch_enriched_context(plan)
    logger.info("[2/4] Enriched Retriever done  (%.1fs)", time.perf_counter() - t0)

    # --- Stage 3a + 3b: GraphBuilder + LLM Analyzer (concurrent) ---
    await _notify(
        on_progress,
        "[3/4] Building collaboration graph & analyzing landscape …",
    )
    t0 = time.perf_counter()
    collab_network, analysis = await asyncio.gather(
        asyncio.to_thread(
            build_collaboration_network,
            enriched_data.enriched_papers,
        ),
        analyze_landscape(topic, enriched_data),
    )
    logger.info("[3/4] GraphBuilder + Analyzer done  (%.1fs)", time.perf_counter() - t0)

    # --- Stage 4: Assemble ---
    await _notify(on_progress, "[4/4] Assembling final landscape …")
    t0 = time.perf_counter()
    landscape = assemble_landscape(
        topic=topic,
        analysis=analysis,
        collaboration_network=collab_network,
        enriched_data=enriched_data,
    )
    logger.info("[4/4] Assembler done  (%.1fs)", time.perf_counter() - t0)

    logger.info(
        "Landscape pipeline complete  total=%.1fs  papers=%d  "
        "tech_nodes=%d  scholars=%d  gaps=%d",
        time.perf_counter() - t_total,
        len(landscape.papers),
        len(landscape.tech_tree.nodes),
        len(landscape.collaboration_network.nodes),
        len(landscape.research_gaps.gaps),
    )
    return landscape
