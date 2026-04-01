"""Domain models — the single source of truth for all data structures.

Re-exports every public model so that consumers can write::

    from src.models import DynamicResearchLandscape, PaperResult, ...
"""

from .assistant import AssistantMessage, AssistantSession, Memory, MessageRole  # noqa: F401
from .db import (  # noqa: F401
    MonitorBrief,
    MonitorFrequency,
    MonitorTask,
    TaskRecord,
    TaskStatus,
    get_engine,
    get_session,
)
from .landscape import (  # noqa: F401
    CollaborationEdge,
    CollaborationNetwork,
    DynamicResearchLandscape,
    LandscapeIncrement,
    LandscapeMeta,
    ResearchGap,
    ResearchGaps,
    ScholarNode,
    TechTree,
    TechTreeEdge,
    TechTreeNode,
)
from .paper import (  # noqa: F401
    PaperResult,
    SearchResult,
    WebSearchItem,
    WebSearchResult,
)
