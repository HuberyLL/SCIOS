"""Paper source registry — auto-collects all BasePaperFetcher implementations."""

from ._base import BasePaperFetcher, extract_year, get_source_limiter, normalize_title
from .arxiv import ArxivFetcher
from .biorxiv import BioRxivFetcher, MedRxivFetcher
from .core import CoreFetcher
from .crossref import CrossrefFetcher
from .dblp import DblpFetcher
from .doaj import DoajFetcher
from .europepmc import EuropePMCFetcher
from .openalex import OpenAlexFetcher
from .pmc import PMCFetcher
from .pubmed import PubMedFetcher

def _build_registry() -> dict[str, BasePaperFetcher]:
    """Build the source registry, injecting config values where needed."""
    from src.core.config import get_settings

    try:
        settings = get_settings()
    except Exception:
        settings = None  # type: ignore[assignment]

    crossref_mailto = getattr(settings, "crossref_mailto", "") or ""
    openalex_mailto = getattr(settings, "openalex_mailto", "") or ""
    core_api_key = getattr(settings, "core_api_key", "") or ""
    doaj_api_key = getattr(settings, "doaj_api_key", "") or ""

    return {
        "arxiv": ArxivFetcher(),
        "pubmed": PubMedFetcher(),
        "biorxiv": BioRxivFetcher(),
        "medrxiv": MedRxivFetcher(),
        "crossref": CrossrefFetcher(mailto=crossref_mailto),
        "openalex": OpenAlexFetcher(mailto=openalex_mailto),
        "pmc": PMCFetcher(),
        "europepmc": EuropePMCFetcher(),
        "core": CoreFetcher(api_key=core_api_key),
        "dblp": DblpFetcher(),
        "doaj": DoajFetcher(api_key=doaj_api_key),
    }


SOURCE_REGISTRY: dict[str, BasePaperFetcher] = _build_registry()

DEFAULT_SOURCES = ["arxiv", "pubmed", "biorxiv", "medrxiv", "crossref", "openalex"]

__all__ = [
    "BasePaperFetcher",
    "SOURCE_REGISTRY",
    "DEFAULT_SOURCES",
    "get_source_limiter",
    "normalize_title",
    "extract_year",
    "ArxivFetcher",
    "PubMedFetcher",
    "BioRxivFetcher",
    "MedRxivFetcher",
    "CrossrefFetcher",
    "OpenAlexFetcher",
    "PMCFetcher",
    "EuropePMCFetcher",
    "CoreFetcher",
    "DblpFetcher",
    "DoajFetcher",
]
