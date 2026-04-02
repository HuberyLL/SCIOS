"""Scope Agent — defines field boundaries, seed papers, and retrieval strategy.

Uses LLM world knowledge to identify the foundational papers, sub-fields,
and time range for a given research topic. This replaces the old Planner
with a much richer output that anchors the entire downstream pipeline.
"""

from __future__ import annotations

import logging

from ...llm_client import call_llm
from ..prompts.scope_prompts import SCOPE_SYSTEM_PROMPT, SCOPE_USER_TEMPLATE
from ..schemas import ScopeDefinition
from .base import BaseAgent, ProgressCallback

logger = logging.getLogger(__name__)


class ScopeAgent(BaseAgent[str, ScopeDefinition]):
    """Stage 1: turn a free-form topic into a rich ``ScopeDefinition``."""

    def __init__(self) -> None:
        super().__init__(name="ScopeAgent")

    async def _execute(
        self,
        topic: str,
        *,
        on_progress: ProgressCallback = None,
    ) -> ScopeDefinition:
        await self._notify(on_progress, "analysing topic and identifying seed papers …")

        messages = [
            {"role": "system", "content": SCOPE_SYSTEM_PROMPT},
            {"role": "user", "content": SCOPE_USER_TEMPLATE.format(topic=topic)},
        ]
        scope = await call_llm(messages, response_format=ScopeDefinition)

        self._logger.info(
            "ScopeDefinition  seeds=%d  sub_fields=%d  strategies=%d  "
            "time=%d-%d",
            len(scope.seed_papers),
            len(scope.sub_fields),
            len(scope.search_strategies),
            scope.time_range_start,
            scope.time_range_end,
        )
        return scope
