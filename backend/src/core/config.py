"""Centralised application settings powered by pydantic-settings.

All API keys, database paths and other tunables
are read from environment variables (or a ``.env`` file) and exposed as
typed attributes on a single ``Settings`` instance.

Usage::

    from src.core.config import get_settings

    settings = get_settings()
    print(settings.llm_model)
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- Semantic Scholar -------------------------------------------------
    semantic_scholar_api_key: str = ""

    # -- Tavily ------------------------------------------------------------
    tavily_api_key: str = ""

    # -- LLM ---------------------------------------------------------------
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o"

    # -- Database -----------------------------------------------------------
    db_path: str = "../data/scios.db"

    # -- Multi-source paper search ------------------------------------------
    core_api_key: str = ""
    doaj_api_key: str = ""
    crossref_mailto: str = ""
    openalex_mailto: str = ""

    # -- Assistant mode ------------------------------------------------------
    assistant_model: str = ""
    assistant_system_prompt: str = ""
    assistant_max_tool_rounds: int = 10
    assistant_max_context_tokens: int = 8000
    assistant_memory_max_items: int = 20
    assistant_memory_max_tokens: int = 1200
    assistant_workspace_dir: str = "workspace"

    # -- LLM concurrency / rate-limit ----------------------------------------
    llm_max_concurrent: int = 4
    llm_max_retries: int = 5
    llm_retry_min_wait: float = 2.0
    llm_retry_max_wait: float = 60.0

    # -- Landscape agent concurrency ----------------------------------------
    landscape_gap_branch_concurrency: int = 3
    landscape_map_concurrency: int = 3

    # -- Landscape evaluation / filtering ------------------------------------
    # Paper scoring weights (must sum to 1.0)
    eval_weight_citation: float = 0.35
    eval_weight_influential: float = 0.15
    eval_weight_venue: float = 0.20
    eval_weight_recency: float = 0.10
    eval_weight_structural: float = 0.20

    eval_tier1_pct: float = 0.15
    eval_tier2_pct: float = 0.50

    eval_budget_narrow: int = 150
    eval_budget_medium: int = 300
    eval_budget_broad: int = 500

    # Scholar filtering thresholds
    scholar_min_h_index: int = 5
    scholar_min_corpus_papers: int = 2
    scholar_top_k: int = 50

    # Scholar scoring weights (must sum to 1.0)
    scholar_weight_h_index: float = 0.30
    scholar_weight_relevance: float = 0.30
    scholar_weight_citation: float = 0.25
    scholar_weight_activity: float = 0.15

    # -- Landscape memory / caching -----------------------------------------
    cache_dir: str = "../data/cache"
    s2_cache_enabled: bool = True
    s2_cache_max_mb: int = 500
    topic_cache_max_age_days: int = 7
    topic_warm_start_max_age_days: int = 30



@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached ``Settings`` singleton."""
    return Settings()
