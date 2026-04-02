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
    unpaywall_email: str = ""
    doaj_api_key: str = ""
    crossref_mailto: str = ""
    openalex_mailto: str = ""

    # -- Source routing (Planner-hints-first) --------------------------------
    source_routing_enabled: bool = True
    source_routing_confidence_threshold: float = 0.6
    source_routing_max_sources: int = 3
    source_routing_stage_b_enabled: bool = True
    source_routing_min_papers_stage_b: int = 5

    # -- Assistant mode ------------------------------------------------------
    assistant_model: str = ""
    assistant_system_prompt: str = ""
    assistant_max_tool_rounds: int = 10
    assistant_max_context_tokens: int = 8000
    assistant_memory_max_items: int = 20
    assistant_memory_max_tokens: int = 1200
    assistant_workspace_dir: str = "workspace"

    # -- Synthesizer --------------------------------------------------------
    synthesizer_max_papers: int = 40

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
