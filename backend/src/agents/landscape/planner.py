"""Planner stage: decompose a user topic into a structured retrieval plan.

Migrated from the former exploration module.
"""

from __future__ import annotations

import logging

from ..llm_client import call_llm
from .schemas import SearchPlan

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """\
You are an expert academic search strategist.

Given a research topic (which may be vague or broad), your job is to produce a
precise retrieval plan so that downstream tools can fetch the most relevant
academic papers and web resources.

## Available paper sources

| id          | Coverage                                                    |
|-------------|-------------------------------------------------------------|
| arxiv       | Preprints in CS, physics, math, quantitative biology, stats |
| pubmed      | Biomedical and life-science journal articles (MEDLINE)      |
| biorxiv     | Biology preprints                                           |
| medrxiv     | Medical / clinical preprints                                |
| crossref    | Broad multidisciplinary DOI registry                        |
| openalex    | Broad open academic graph (all disciplines)                 |
| pmc         | Full-text biomedical articles (PubMed Central)              |
| europepmc   | European biomedical literature aggregator                   |
| core        | Open-access aggregator across repositories worldwide        |
| dblp        | Computer science bibliography (conferences & journals)      |
| doaj        | Directory of Open Access Journals                           |

## Output rules

- **paper_keywords** (3-5): English keyword phrases for Semantic Scholar / arXiv.
  Use established academic terminology; avoid overly generic words.
- **web_queries** (2-3): English questions targeting recent trends, survey
  articles, or industry applications (sent to a web search engine).
- **focus_areas** (2-4): Distinct research sub-directions to guide the report.
- **source_hints** (2-4): Pick the source *id*s from the table above that are
  most relevant to this topic.  Only include sources that are likely to return
  high-quality results for the specific topic.
- **domain_tags** (1-2): Classify the topic into domains chosen from:
  biomedical, computer_science, physics, chemistry, social_science,
  multidisciplinary.
- **confidence** (0.0-1.0): How certain you are that *source_hints* covers the
  right sources.  Use >=0.7 for well-scoped domains (e.g. a pure biomedical
  topic -> pubmed + biorxiv), <0.5 for ambiguous or highly cross-disciplinary
  topics.

Always respond in the structured JSON format requested.
"""

PLANNER_USER_TEMPLATE = """\
Research topic: {topic}

Produce a search plan for this topic.
"""


async def generate_search_plan(topic: str) -> SearchPlan:
    """Ask the LLM to turn a free-form *topic* into a ``SearchPlan``."""
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": PLANNER_USER_TEMPLATE.format(topic=topic)},
    ]
    plan = await call_llm(messages, response_format=SearchPlan)
    logger.info(
        "SearchPlan  keywords=%d  web_queries=%d  focus_areas=%d",
        len(plan.paper_keywords),
        len(plan.web_queries),
        len(plan.focus_areas),
    )
    return plan
