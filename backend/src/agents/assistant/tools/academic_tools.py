"""Academic search tools — thin wrappers around SCIOS's existing retrieval clients."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from src.agents.assistant.tools.base import BaseTool
from src.agents.tools.s2_client import SemanticScholarClient
from src.agents.tools.web_search import tavily_search

logger = logging.getLogger(__name__)

_ABSTRACT_CHAR_LIMIT = 300
_WEB_CONTENT_CHAR_LIMIT = 500


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


# ---------------------------------------------------------------------------
# SearchAcademicPapersTool
# ---------------------------------------------------------------------------


class SearchPapersArgs(BaseModel):
    query: str = Field(..., description="Search keywords for academic papers.")
    limit: int = Field(5, ge=1, le=20, description="Maximum number of papers to return.")


class SearchAcademicPapersTool(BaseTool):
    name = "search_academic_papers"
    description = (
        "Search academic papers via Semantic Scholar. Returns titles, authors, "
        "year, citation count, abstract snippets and PDF links."
    )
    args_schema = SearchPapersArgs

    async def execute(self, **kwargs: Any) -> str:
        query: str = kwargs["query"]
        limit: int = kwargs.get("limit", 5)

        client = SemanticScholarClient()
        try:
            result = await client.search_papers(query, limit=limit)
        except Exception as exc:
            logger.error("search_academic_papers failed: %s", exc)
            return f"Search failed: {exc}"

        if not result.papers:
            return json.dumps({"query": query, "total": 0, "papers": []}, ensure_ascii=False)

        papers_list = []
        for p in result.papers:
            papers_list.append({
                "title": p.title,
                "authors": p.authors[:5],
                "year": p.published_date[:4] if p.published_date else "",
                "citation_count": p.citation_count,
                "abstract": _truncate(p.abstract, _ABSTRACT_CHAR_LIMIT),
                "pdf_url": p.pdf_url,
                "url": p.url,
            })

        payload = {"query": query, "total": result.total, "papers": papers_list}
        return json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# WebSearchTool
# ---------------------------------------------------------------------------


class WebSearchArgs(BaseModel):
    query: str = Field(..., description="Web search query string.")


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the web via Tavily. Useful as a fallback when Semantic Scholar "
        "has no results, or for finding tech blogs, conference pages and docs."
    )
    args_schema = WebSearchArgs

    async def execute(self, **kwargs: Any) -> str:
        query: str = kwargs["query"]

        try:
            result = await tavily_search(query, max_results=5)
        except Exception as exc:
            logger.error("web_search failed: %s", exc)
            return f"Web search failed: {exc}"

        if not result.results:
            return json.dumps({"query": query, "results": []}, ensure_ascii=False)

        items = []
        for r in result.results:
            items.append({
                "title": r.title,
                "url": r.url,
                "content": _truncate(r.content, _WEB_CONTENT_CHAR_LIMIT),
            })

        return json.dumps({"query": query, "results": items}, ensure_ascii=False, indent=2)
