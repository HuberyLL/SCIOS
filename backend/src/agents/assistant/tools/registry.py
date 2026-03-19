"""Central registry that holds all available assistant tools."""

from __future__ import annotations

import logging
from typing import Any

from src.agents.assistant.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Singleton-style class-level registry for :class:`BaseTool` instances."""

    _tools: dict[str, BaseTool] = {}

    @classmethod
    def register(cls, tool: BaseTool) -> None:
        cls._tools[tool.name] = tool
        logger.info("Registered assistant tool: %s", tool.name)

    @classmethod
    def get(cls, name: str) -> BaseTool | None:
        return cls._tools.get(name)

    @classmethod
    def all_tools(cls) -> list[BaseTool]:
        return list(cls._tools.values())

    @classmethod
    def get_all_tools_for_llm(cls) -> list[dict[str, Any]]:
        """Return tool descriptions in the OpenAI *tools* parameter format."""
        tools: list[dict[str, Any]] = []
        for t in cls._tools.values():
            schema = t.args_schema.model_json_schema()
            schema.pop("title", None)
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": schema,
                    },
                }
            )
        return tools
