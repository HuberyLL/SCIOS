"""Planner stage: decompose a user topic into a structured retrieval plan."""

from __future__ import annotations

import logging

from ..llm_client import call_llm
from ..prompts.planner import PLANNER_SYSTEM_PROMPT, PLANNER_USER_TEMPLATE
from .schemas import SearchPlan

logger = logging.getLogger(__name__)


async def generate_search_plan(topic: str) -> SearchPlan:
    """Ask the LLM to turn a free-form *topic* into a ``SearchPlan``."""
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": PLANNER_USER_TEMPLATE.format(topic=topic)},
    ]
    plan = await call_llm(messages, response_format=SearchPlan)
    logger.info(
        "SearchPlan  keywords=%d  web_queries=%d  focus_areas=%d",
        len(plan.paper_keywords),
        len(plan.web_queries),
        len(plan.focus_areas),
    )
    return plan
