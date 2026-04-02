"""Base class for all landscape agents.

Provides a uniform ``run()`` interface with built-in logging, timing,
and progress reporting.  Subclasses implement ``_execute()`` with their
specific logic.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT", bound=BaseModel)

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]] | None


class BaseAgent(ABC, Generic[InputT, OutputT]):
    """Abstract base for every agent in the landscape pipeline.

    Parameters
    ----------
    name : Human-readable agent name used in logs and progress messages.
    """

    name: str

    def __init__(self, name: str) -> None:
        self.name = name
        self._logger = logging.getLogger(f"{__name__}.{name}")

    async def run(
        self,
        input_data: InputT,
        *,
        on_progress: ProgressCallback = None,
    ) -> OutputT:
        """Execute the agent and return its typed output.

        Handles timing, logging, and progress notification automatically.
        """
        self._logger.info("%s starting", self.name)
        t0 = time.perf_counter()

        await self._notify(on_progress, "starting …")

        try:
            result = await self._execute(input_data, on_progress=on_progress)
        except Exception:
            elapsed = time.perf_counter() - t0
            self._logger.exception(
                "%s failed after %.1fs", self.name, elapsed,
            )
            raise

        elapsed = time.perf_counter() - t0
        self._logger.info("%s completed in %.1fs", self.name, elapsed)
        return result

    @abstractmethod
    async def _execute(
        self,
        input_data: InputT,
        *,
        on_progress: ProgressCallback = None,
    ) -> OutputT:
        """Subclass-specific implementation. Override this, not ``run()``."""
        ...

    async def _notify(self, on_progress: ProgressCallback, message: str) -> None:
        """Send a structured progress event with agent context."""
        if on_progress is not None:
            await on_progress({
                "type": "progress",
                "agent": self.name,
                "message": f"{self.name}: {message}",
            })
