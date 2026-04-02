"""agents.landscape — Dynamic Research Landscape multi-agent pipeline.

Public API
----------
- ``run_landscape_pipeline(topic)`` — full pipeline entry-point.
"""

from .orchestrator import run_landscape_pipeline

__all__ = ["run_landscape_pipeline"]
