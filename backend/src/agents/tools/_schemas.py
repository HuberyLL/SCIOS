"""Backward-compatible re-exports of shared Pydantic models.

Canonical definitions now live in ``src.models.paper``.  This module
re-exports them so that existing ``from src.agents.tools._schemas import ...``
statements continue to work without modification.
"""

from src.models.paper import (  # noqa: F401
    PaperResult,
    SearchResult,
    WebSearchItem,
    WebSearchResult,
)
