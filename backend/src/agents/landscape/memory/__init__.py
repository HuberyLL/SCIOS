"""Memory management subsystem for the Landscape pipeline.

Four layers:
  1. S2 API file cache — avoid redundant HTTP calls
  2. Pipeline checkpoint — resume from last completed stage
  3. Topic memory — cross-run warm start for repeated topics
  4. Incremental update — merge new papers into existing landscape
"""

from .checkpoint import CheckpointManager
from .incremental import compute_increment, detect_new_papers, merge_increment
from .s2_cache import S2Cache
from .topic_store import TopicStore

__all__ = [
    "S2Cache",
    "CheckpointManager",
    "TopicStore",
    "compute_increment",
    "merge_increment",
    "detect_new_papers",
]
