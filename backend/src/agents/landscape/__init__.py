"""agents.landscape — Dynamic Research Landscape multi-agent pipeline.

Public API
----------
- ``run_landscape_pipeline(topic, *, task_id=None)`` — full pipeline entry-point.
- ``run_incremental_update(topic, *, task_id=None)`` — incremental refresh.
"""

from .orchestrator import run_incremental_update, run_landscape_pipeline

__all__ = ["run_landscape_pipeline", "run_incremental_update"]
