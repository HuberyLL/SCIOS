"""Centralised application settings powered by pydantic-settings.

All API keys, database paths, scheduler parameters and other tunables
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

    # -- Monitoring scheduler -----------------------------------------------
    monitoring_cron_hour: int = 8
    monitoring_cron_minute: int = 0
    monitoring_interval_minutes: int | None = None

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

    # -- Synthesizer --------------------------------------------------------
    synthesizer_max_papers: int = 40

    # -- Email notification (SMTP) ------------------------------------------
    smtp_server: str = ""
    smtp_port: int = 465
    smtp_username: str = ""
    smtp_password: str = ""
    notification_email: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached ``Settings`` singleton."""
    return Settings()
