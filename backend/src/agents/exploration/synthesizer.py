"""Synthesizer stage: distill raw retrieved data into an ExplorationReport."""

from __future__ import annotations

import logging

from ..llm_client import call_llm
from ..prompts.synthesizer import SYNTHESIZER_SYSTEM_PROMPT, SYNTHESIZER_USER_TEMPLATE
from .schemas import ExplorationReport, RawRetrievedData

logger = logging.getLogger(__name__)

MAX_ABSTRACT_CHARS = 300
MAX_WEB_SNIPPET_CHARS = 500
DEFAULT_MAX_PAPERS = 40


def _format_context(raw: RawRetrievedData, *, max_papers: int = DEFAULT_MAX_PAPERS) -> str:
    """Serialize *RawRetrievedData* into a compact text block for the prompt.

    Papers are deduplicated by title, sorted by citation count (highest first),
    and capped at *max_papers* to stay within the model's context window.
    """
    sections: list[str] = []

    all_papers = []
    for sr in (*raw.s2_results, *raw.paper_results):
        for p in sr.papers:
            all_papers.append(p)

    seen_titles: set[str] = set()
    deduped = []
    for p in all_papers:
        key = p.title.strip().lower()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        deduped.append(p)

    deduped.sort(key=lambda p: p.citation_count, reverse=True)

    omitted = max(0, len(deduped) - max_papers)
    deduped = deduped[:max_papers]

    if deduped:
        lines = []
        for i, p in enumerate(deduped, 1):
            abstract = p.abstract[:MAX_ABSTRACT_CHARS].rstrip()
            if len(p.abstract) > MAX_ABSTRACT_CHARS:
                abstract += "…"
            lines.append(
                f"[P{i}] {p.title}\n"
                f"     Authors: {', '.join(p.authors[:5])}\n"
                f"     Year: {p.published_date}  |  Citations: {p.citation_count}\n"
                f"     Source: {p.source}  |  URL: {p.url}\n"
                f"     Abstract: {abstract}"
            )
        if omitted:
            lines.append(f"(… and {omitted} more papers omitted)")
        sections.append("## Papers\n" + "\n\n".join(lines))

    if raw.citation_map:
        cite_lines = []
        for paper_id, citers in raw.citation_map.items():
            titles = ", ".join(c.title for c in citers[:5])
            cite_lines.append(f"  {paper_id} cited by: {titles}")
        sections.append("## Citation relationships\n" + "\n".join(cite_lines))

    for wr in raw.web_results:
        if not wr.results:
            continue
        web_lines = []
        for item in wr.results:
            snippet = item.content[:MAX_WEB_SNIPPET_CHARS].rstrip()
            if len(item.content) > MAX_WEB_SNIPPET_CHARS:
                snippet += "…"
            web_lines.append(
                f"- [{item.title}]({item.url})\n  {snippet}"
            )
        sections.append(f"## Web: {wr.query}\n" + "\n".join(web_lines))

    return "\n\n".join(sections) if sections else "(No evidence retrieved.)"


async def synthesize_report(
    topic: str,
    raw_data: RawRetrievedData,
    *,
    max_papers: int = DEFAULT_MAX_PAPERS,
) -> ExplorationReport:
    """Call the LLM to produce a structured ``ExplorationReport``."""
    context_text = _format_context(raw_data, max_papers=max_papers)
    logger.debug("Synthesizer context length: %d chars", len(context_text))

    messages = [
        {"role": "system", "content": SYNTHESIZER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": SYNTHESIZER_USER_TEMPLATE.format(
                topic=topic,
                context=context_text,
            ),
        },
    ]
    return await call_llm(messages, response_format=ExplorationReport)
