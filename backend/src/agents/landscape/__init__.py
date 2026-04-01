"""agents.landscape — Dynamic Research Landscape pipeline.

Public API
----------
- ``run_landscape_pipeline(topic)`` — full pipeline entry-point.
- ``run_incremental_scan(topic, since_date, existing_paper_ids)`` — incremental monitoring scan.
"""

from .incremental import run_incremental_scan
from .pipeline import run_landscape_pipeline

__all__ = ["run_landscape_pipeline", "run_incremental_scan"]
