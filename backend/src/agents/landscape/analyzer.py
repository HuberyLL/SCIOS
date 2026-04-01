"""LLM Analyzer: produce TechTree + ResearchGaps.

Calls the LLM with ``response_format=LandscapeAnalysis`` to get
structured output.  The prompt includes paper_ids explicitly so the
model can reference them in its output.
"""

from __future__ import annotations

import logging

from ..llm_client import call_llm
from .prompts import ANALYZER_SYSTEM_PROMPT, ANALYZER_USER_TEMPLATE
from .schemas import EnrichedRetrievedData, LandscapeAnalysis

logger = logging.getLogger(__name__)

MAX_ABSTRACT_CHARS = 400
MAX_WEB_SNIPPET_CHARS = 500
DEFAULT_MAX_PAPERS = 40


def _format_evidence(data: EnrichedRetrievedData, *, max_papers: int = DEFAULT_MAX_PAPERS) -> str:
    """Serialize enriched data into a compact text block for the analyzer prompt.

    Each paper entry includes its ``paper_id`` so the LLM can reference it.
    """
    sections: list[str] = []

    papers = sorted(
        [ep.paper for ep in data.enriched_papers],
        key=lambda p: p.citation_count,
        reverse=True,
    )

    omitted = max(0, len(papers) - max_papers)
    papers = papers[:max_papers]

    if papers:
        lines: list[str] = []
        for i, p in enumerate(papers, 1):
            abstract = p.abstract[:MAX_ABSTRACT_CHARS].rstrip()
            if len(p.abstract) > MAX_ABSTRACT_CHARS:
                abstract += "…"
            lines.append(
                f"[P{i}] paper_id={p.paper_id}\n"
                f"     Title: {p.title}\n"
                f"     Authors: {', '.join(p.authors[:5])}\n"
                f"     Year: {p.published_date}  |  Citations: {p.citation_count}\n"
                f"     Source: {p.source}  |  URL: {p.url}\n"
                f"     Abstract: {abstract}"
            )
        if omitted:
            lines.append(f"(… and {omitted} more papers omitted)")
        sections.append("## Papers\n" + "\n\n".join(lines))

    if data.citation_map:
        cite_lines: list[str] = []
        for paper_id, citers in data.citation_map.items():
            titles = ", ".join(c.title for c in citers[:5])
            cite_lines.append(f"  {paper_id} cited by: {titles}")
        sections.append("## Citation relationships\n" + "\n".join(cite_lines))

    if data.reference_map:
        ref_lines: list[str] = []
        for paper_id, refs in data.reference_map.items():
            titles = ", ".join(r.title for r in refs[:5])
            ref_lines.append(f"  {paper_id} references: {titles}")
        sections.append("## Reference relationships\n" + "\n".join(ref_lines))

    for wr in data.web_results:
        if not wr.results:
            continue
        web_lines: list[str] = []
        for item in wr.results:
            snippet = item.content[:MAX_WEB_SNIPPET_CHARS].rstrip()
            if len(item.content) > MAX_WEB_SNIPPET_CHARS:
                snippet += "…"
            web_lines.append(f"- [{item.title}]({item.url})\n  {snippet}")
        sections.append(f"## Web: {wr.query}\n" + "\n".join(web_lines))

    return "\n\n".join(sections) if sections else "(No evidence retrieved.)"


async def analyze_landscape(
    topic: str,
    data: EnrichedRetrievedData,
    *,
    max_papers: int = DEFAULT_MAX_PAPERS,
) -> LandscapeAnalysis:
    """Call the LLM to produce a ``LandscapeAnalysis``."""
    context_text = _format_evidence(data, max_papers=max_papers)
    logger.debug("Analyzer evidence length: %d chars", len(context_text))

    messages = [
        {"role": "system", "content": ANALYZER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": ANALYZER_USER_TEMPLATE.format(
                topic=topic,
                context=context_text,
            ),
        },
    ]
    return await call_llm(messages, response_format=LandscapeAnalysis)
