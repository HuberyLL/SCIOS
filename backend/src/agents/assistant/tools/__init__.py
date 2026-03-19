"""Auto-register all built-in assistant tools on import."""

from src.agents.assistant.tools.dummy_time import GetSystemTimeTool
from src.agents.assistant.tools.registry import ToolRegistry

ToolRegistry.register(GetSystemTimeTool())
