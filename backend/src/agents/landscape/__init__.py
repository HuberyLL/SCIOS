"""agents.landscape — Dynamic Research Landscape pipeline.

Public API
----------
- ``run_landscape_pipeline(topic)`` — full pipeline entry-point.
"""

from .pipeline import run_landscape_pipeline

__all__ = ["run_landscape_pipeline"]
