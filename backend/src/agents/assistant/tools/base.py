"""Abstract base class for all assistant tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class BaseTool(ABC):
    """Every tool exposes a *name*, a *description*, an *args_schema*
    (Pydantic model that defines accepted parameters), and an async
    ``execute`` method."""

    name: str
    description: str
    args_schema: type[BaseModel]

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """Run the tool and return a JSON-serialisable result."""
