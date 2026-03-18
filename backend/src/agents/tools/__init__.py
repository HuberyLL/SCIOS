"""agents.tools -- external-service tool wrappers for the SCIOS Agent pipeline.

Public API
----------
- ``SemanticScholarClient``  – Semantic Scholar paper search / details / reco.
- ``PaperSearcher``          – Multi-source paper search (arXiv, PubMed).
- ``tavily_search``          – Tavily web search.
- Pydantic schemas: ``PaperResult``, ``SearchResult``,
  ``WebSearchItem``, ``WebSearchResult``.
"""

from ._schemas import PaperResult, SearchResult, WebSearchItem, WebSearchResult
from .paper_fetcher import PaperSearcher
from .s2_client import SemanticScholarClient
from .web_search import tavily_search

__all__ = [
    "SemanticScholarClient",
    "PaperSearcher",
    "tavily_search",
    "PaperResult",
    "SearchResult",
    "WebSearchItem",
    "WebSearchResult",
]
