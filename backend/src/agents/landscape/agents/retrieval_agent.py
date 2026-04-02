"""Retrieval Agent — iterative, multi-phase paper corpus construction.

Architecture aligned with STORM/GPT-Researcher patterns:
  - Per-unit limits only (per query, per paper) — no global corpus cap
  - Convergence-based stopping — halt when new results are mostly duplicates
  - Adaptive coverage — supplement phase triggers on quality signals, not size

Phases:
  A. Anchor seed papers by title search
  B. Snowball expansion from seeds (convergence-stopped)
  C. Sub-field directed search (per-keyword convergence)
  D. Coverage self-check with LLM-generated supplementary queries
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from pydantic import BaseModel, Field

from src.models.paper import PaperResult

from ...llm_client import call_llm
from ...tools import SemanticScholarClient
from ..prompts.retrieval_prompts import COVERAGE_CHECK_SYSTEM, COVERAGE_CHECK_USER
from ..schemas import (
    CorpusStats,
    PaperCorpus,
    ScopeDefinition,
)
from .base import BaseAgent, ProgressCallback

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-unit limits (necessary: S2 API pagination / rate-limit constraints)
# These limit how much data we fetch in a SINGLE API call, NOT globally.
# ---------------------------------------------------------------------------
PER_QUERY_LIMIT = 100           # max results per S2 search query
SNOWBALL_PER_PAPER_CITE = 100   # max citations fetched per paper
SNOWBALL_PER_PAPER_REF = 100    # max references fetched per paper
SNOWBALL_MIN_CITATIONS = 3      # skip low-cited papers in layer > 0

# ---------------------------------------------------------------------------
# Convergence criteria (replaces global hard caps like TARGET_CORPUS_MAX)
# ---------------------------------------------------------------------------
CONVERGENCE_RATIO = 0.10        # stop when < 10% of fetched papers are new
MIN_CORPUS_FOR_SUPPLEMENT = 200 # below this, always run Phase D regardless
MIN_VIABLE_CORPUS = 30          # hard floor: always try to reach this many papers

# ---------------------------------------------------------------------------
# Budget envelopes keyed by estimated_complexity.
# Values: (snowball_depth, max_concurrent_subfield_searches)
# ---------------------------------------------------------------------------
_BUDGET = {
    "narrow": (3, 20),
    "medium": (2, 15),
    "broad":  (1, 10),
}


class _SupplementaryQueries(BaseModel):
    """LLM output for coverage gap analysis."""
    queries: list[str] = Field(
        ..., min_length=1,
        description="Search queries to fill corpus gaps.",
    )
    rationale: str = Field(
        default="",
        description="Brief explanation of which gaps these queries target.",
    )


class RetrievalAgent(BaseAgent[ScopeDefinition, PaperCorpus]):
    """Stage 2: build a comprehensive paper corpus via iterative retrieval."""

    def __init__(self) -> None:
        super().__init__(name="RetrievalAgent")
        self._client = SemanticScholarClient()

    async def _execute(
        self,
        scope: ScopeDefinition,
        *,
        on_progress: ProgressCallback = None,
    ) -> PaperCorpus:
        paper_map: dict[str, PaperResult] = {}
        seed_map: dict[str, str] = {}  # seed_title -> paper_id
        citation_graph: dict[str, list[str]] = defaultdict(list)
        reference_graph: dict[str, list[str]] = defaultdict(list)

        snowball_depth, max_concurrent_sf = _BUDGET.get(
            scope.estimated_complexity, _BUDGET["medium"],
        )
        self._logger.info(
            "Budget envelope: complexity=%s  snowball_depth=%d  max_concurrent_sf=%d",
            scope.estimated_complexity, snowball_depth, max_concurrent_sf,
        )

        quality_flags: list[str] = []

        # -- Phase A: Anchor seed papers --
        await self._notify(on_progress, "Phase A — anchoring seed papers …")
        seed_map = await self._anchor_seeds(scope, paper_map)
        self._logger.info("Phase A: anchored %d/%d seeds", len(seed_map), len(scope.seed_papers))

        # -- Phase A+: Rescue missing seeds with relaxed search --
        missing = [s for s in scope.seed_papers if s.title not in seed_map]
        if missing:
            await self._notify(on_progress, "Phase A+ — rescuing %d missing seeds …" % len(missing))
            rescued = await self._rescue_seeds(missing, paper_map)
            seed_map.update(rescued)
            self._logger.info("Phase A+: rescued %d/%d missing seeds", len(rescued), len(missing))

        if len(seed_map) < len(scope.seed_papers):
            quality_flags.append("low_seed_coverage")

        # -- Phase B: Snowball expansion (convergence-stopped) --
        await self._notify(on_progress, "Phase B — snowball citation expansion …")
        await self._snowball(
            list(seed_map.values()), paper_map, citation_graph, reference_graph,
            max_depth=snowball_depth,
        )
        self._logger.info("Phase B: corpus=%d after snowball", len(paper_map))

        # -- Phase C: Sub-field directed search (per-keyword convergence) --
        await self._notify(on_progress, "Phase C — sub-field directed search …")
        sub_field_mapping = await self._subfield_search(
            scope, paper_map, max_concurrent=max_concurrent_sf,
        )
        self._logger.info("Phase C: corpus=%d after sub-field fill", len(paper_map))

        # -- Phase D: Coverage self-check (quality-triggered OR corpus too small) --
        needs_supplement = (
            len(paper_map) < MIN_VIABLE_CORPUS
            or self._should_supplement(scope, paper_map, seed_map, sub_field_mapping)
        )
        if needs_supplement:
            await self._notify(on_progress, "Phase D — filling coverage gaps …")
            await self._coverage_supplement(
                scope, paper_map, seed_map, sub_field_mapping,
            )
            self._logger.info("Phase D: corpus=%d after supplement", len(paper_map))

        if len(paper_map) < MIN_VIABLE_CORPUS:
            quality_flags.append("small_corpus")

        # -- Build output --
        stats = self._compute_stats(scope, paper_map, seed_map, sub_field_mapping)
        stats.quality_flags = quality_flags
        corpus = PaperCorpus(
            papers=list(paper_map.values()),
            seed_paper_map=seed_map,
            citation_graph=dict(citation_graph),
            reference_graph=dict(reference_graph),
            sub_field_mapping=sub_field_mapping,
            author_paper_count=self._count_authors(paper_map),
            stats=stats,
        )
        return corpus

    # ------------------------------------------------------------------
    # Phase A: Seed anchoring
    # ------------------------------------------------------------------

    async def _anchor_seeds(
        self,
        scope: ScopeDefinition,
        paper_map: dict[str, PaperResult],
    ) -> dict[str, str]:
        """Search S2 for each seed paper title and anchor it in the corpus.

        Returns a mapping of seed_title -> paper_id for every seed that
        was successfully resolved, preserving the exact correspondence.
        """
        seed_map: dict[str, str] = {}

        async def _find_one(seed):
            paper = await self._client.search_by_title(seed.title)
            if paper and paper.paper_id:
                return paper
            return None

        tasks = [_find_one(s) for s in scope.seed_papers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for seed_def, result in zip(scope.seed_papers, results):
            if isinstance(result, Exception):
                self._logger.warning("Seed search failed for '%s': %s", seed_def.title, result)
                continue
            if result is None:
                self._logger.warning("Seed not found: '%s'", seed_def.title)
                continue
            pid = result.paper_id
            if pid not in paper_map:
                paper_map[pid] = result
            seed_map[seed_def.title] = pid

        return seed_map

    # ------------------------------------------------------------------
    # Phase A+: Rescue missing seeds with relaxed keyword search
    # ------------------------------------------------------------------

    async def _rescue_seeds(
        self,
        missing: list,
        paper_map: dict[str, PaperResult],
    ) -> dict[str, str]:
        """Try to find missing seeds via keyword search + year filtering."""
        rescued: dict[str, str] = {}

        async def _relaxed_search(seed):
            keywords = seed.title.split()[:6]
            query = " ".join(keywords)
            result = await self._client.search_papers(query, limit=20)
            for p in result.papers:
                if not p.paper_id or not p.title:
                    continue
                if seed.expected_year and p.published_date:
                    year_str = p.published_date[:4]
                    if year_str.isdigit() and abs(int(year_str) - seed.expected_year) > 2:
                        continue
                title_lower = p.title.lower()
                seed_words = set(seed.title.lower().split())
                match_ratio = sum(1 for w in seed_words if w in title_lower) / max(len(seed_words), 1)
                if match_ratio >= 0.5:
                    return seed.title, p
            return seed.title, None

        tasks = [_relaxed_search(s) for s in missing]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, Exception):
                continue
            title, paper = res
            if paper and paper.paper_id:
                if paper.paper_id not in paper_map:
                    paper_map[paper.paper_id] = paper
                rescued[title] = paper.paper_id

        return rescued

    # ------------------------------------------------------------------
    # Phase B: Snowball expansion — convergence-stopped
    # ------------------------------------------------------------------

    async def _snowball(
        self,
        start_ids: list[str],
        paper_map: dict[str, PaperResult],
        citation_graph: dict[str, list[str]],
        reference_graph: dict[str, list[str]],
        *,
        max_depth: int = 2,
    ) -> None:
        """BFS-style expansion with convergence-based stopping.

        Instead of a global corpus cap, each layer checks whether it is
        still discovering a meaningful fraction of new papers.  If the
        new-paper ratio drops below ``CONVERGENCE_RATIO`` the expansion
        halts — the literature has been saturated for this seed set.
        """
        frontier = set(start_ids)
        visited: set[str] = set()

        for layer in range(max_depth):
            if not frontier:
                break

            self._logger.info(
                "Snowball layer %d/%d: expanding %d papers",
                layer + 1, max_depth, len(frontier),
            )
            next_frontier: set[str] = set()
            papers_seen_this_layer = 0
            papers_new_this_layer = 0

            async def _expand_one(pid: str):
                cites, refs = await asyncio.gather(
                    self._client.get_paper_citations(pid, limit=SNOWBALL_PER_PAPER_CITE),
                    self._client.get_paper_references(pid, limit=SNOWBALL_PER_PAPER_REF),
                )
                return pid, cites, refs

            tasks = [_expand_one(pid) for pid in frontier if pid not in visited]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in results:
                if isinstance(res, Exception):
                    self._logger.warning("Snowball expand error: %s", res)
                    continue
                pid, cites, refs = res
                visited.add(pid)

                # cites = papers that cite pid (incoming)
                # → pid appears in THEIR citation lists; pid is cited BY them
                for p in cites:
                    if not p.paper_id or not p.title:
                        continue
                    if p.citation_count < SNOWBALL_MIN_CITATIONS and layer > 0:
                        continue
                    papers_seen_this_layer += 1
                    reference_graph[pid].append(p.paper_id)    # pid is cited by p
                    citation_graph[p.paper_id].append(pid)     # p cites pid
                    if p.paper_id not in paper_map:
                        paper_map[p.paper_id] = p
                        next_frontier.add(p.paper_id)
                        papers_new_this_layer += 1

                # refs = papers that pid references (outgoing)
                # → pid cites these papers
                for p in refs:
                    if not p.paper_id or not p.title:
                        continue
                    if p.citation_count < SNOWBALL_MIN_CITATIONS and layer > 0:
                        continue
                    papers_seen_this_layer += 1
                    citation_graph[pid].append(p.paper_id)     # pid cites p
                    reference_graph[p.paper_id].append(pid)    # p is cited by pid
                    if p.paper_id not in paper_map:
                        paper_map[p.paper_id] = p
                        next_frontier.add(p.paper_id)
                        papers_new_this_layer += 1

            frontier = next_frontier - visited

            # Convergence check: are we still discovering new papers?
            if papers_seen_this_layer > 0:
                new_ratio = papers_new_this_layer / papers_seen_this_layer
                self._logger.info(
                    "Snowball layer %d: %d new / %d seen = %.1f%% new",
                    layer + 1, papers_new_this_layer,
                    papers_seen_this_layer, new_ratio * 100,
                )
                if new_ratio < CONVERGENCE_RATIO:
                    self._logger.info(
                        "Convergence reached (%.1f%% < %.1f%%), stopping snowball",
                        new_ratio * 100, CONVERGENCE_RATIO * 100,
                    )
                    break

    # ------------------------------------------------------------------
    # Phase C: Sub-field directed search — per-keyword convergence
    # ------------------------------------------------------------------

    async def _subfield_search(
        self,
        scope: ScopeDefinition,
        paper_map: dict[str, PaperResult],
        *,
        max_concurrent: int = 15,
    ) -> dict[str, list[str]]:
        """Search S2 for each sub-field's keywords.

        For each sub-field, keywords are searched sequentially.  If a keyword
        query returns mostly papers already in the corpus (> 1 - CONVERGENCE_RATIO),
        remaining keywords for that sub-field are skipped — the area is saturated.
        """
        sub_field_mapping: dict[str, list[str]] = defaultdict(list)
        sem = asyncio.Semaphore(max_concurrent)

        async def _search_subfield(sf):
            all_ids: list[str] = []
            async with sem:
                for kw in sf.keywords:
                    result = await self._client.search_papers(kw, limit=PER_QUERY_LIMIT)
                    new_count = 0
                    total_count = 0
                    for p in result.papers:
                        if not p.paper_id:
                            continue
                        total_count += 1
                        all_ids.append(p.paper_id)
                        if p.paper_id not in paper_map:
                            paper_map[p.paper_id] = p
                            new_count += 1

                    if total_count > 0 and (new_count / total_count) < CONVERGENCE_RATIO:
                        logger.debug(
                            "Sub-field '%s' keyword '%s': saturated (%d/%d new), skipping rest",
                            sf.name, kw, new_count, total_count,
                        )
                        break

            return sf.name, all_ids

        tasks = [_search_subfield(sf) for sf in scope.sub_fields]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, Exception):
                self._logger.warning("Sub-field search error: %s", res)
                continue
            sf_name, ids = res
            sub_field_mapping[sf_name] = list(dict.fromkeys(ids))

        return dict(sub_field_mapping)

    # ------------------------------------------------------------------
    # Phase D trigger: quality-based, not size-based
    # ------------------------------------------------------------------

    @staticmethod
    def _should_supplement(
        scope: ScopeDefinition,
        paper_map: dict[str, PaperResult],
        seed_map: dict[str, str],
        sub_field_mapping: dict[str, list[str]],
    ) -> bool:
        """Decide whether to run the LLM supplement phase.

        Triggers on quality signals, not just corpus size:
        - Missing seed papers
        - Any sub-field with 0 papers
        - Corpus below safety minimum
        """
        if len(paper_map) < MIN_CORPUS_FOR_SUPPLEMENT:
            return True
        if len(seed_map) < len(scope.seed_papers):
            return True
        for sf in scope.sub_fields:
            if sf.name not in sub_field_mapping or len(sub_field_mapping[sf.name]) == 0:
                return True
        return False

    # ------------------------------------------------------------------
    # Phase D: Coverage supplement
    # ------------------------------------------------------------------

    async def _coverage_supplement(
        self,
        scope: ScopeDefinition,
        paper_map: dict[str, PaperResult],
        seed_map: dict[str, str],
        sub_field_mapping: dict[str, list[str]],
    ) -> None:
        """Ask the LLM which gaps remain, then run supplementary queries."""
        stats = self._compute_stats(scope, paper_map, seed_map, sub_field_mapping)
        missing_seeds = [
            s.title for s in scope.seed_papers if s.title not in seed_map
        ]

        sub_fields_text = "\n".join(
            f"- {sf.name}: {sf.description}" for sf in scope.sub_fields
        )
        user_msg = COVERAGE_CHECK_USER.format(
            topic=scope.topic,
            sub_fields_text=sub_fields_text,
            total_papers=stats.total_papers,
            seed_found=stats.seed_papers_found,
            seed_expected=stats.seed_papers_expected,
            year_dist=stats.year_distribution,
            subfield_coverage=stats.sub_field_coverage,
            missing_seeds=", ".join(missing_seeds) if missing_seeds else "(all found)",
        )

        try:
            supplement = await call_llm(
                [
                    {"role": "system", "content": COVERAGE_CHECK_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                response_format=_SupplementaryQueries,
            )
        except Exception:
            self._logger.warning(
                "Coverage LLM call failed — falling back to scope search_strategies"
            )
            fallback_queries = [
                q for strat in scope.search_strategies for q in strat.queries
            ]
            supplement = _SupplementaryQueries(
                queries=fallback_queries[:10],
                rationale="LLM fallback: using scope search_strategies",
            )

        self._logger.info(
            "Supplement queries (%d): %s",
            len(supplement.queries), supplement.queries,
        )

        async def _run_query(q: str):
            return await self._client.search_papers(q, limit=PER_QUERY_LIMIT)

        results = await asyncio.gather(
            *[_run_query(q) for q in supplement.queries],
            return_exceptions=True,
        )
        for res in results:
            if isinstance(res, Exception):
                continue
            for p in res.papers:
                if p.paper_id and p.paper_id not in paper_map:
                    paper_map[p.paper_id] = p

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_stats(
        scope: ScopeDefinition,
        paper_map: dict[str, PaperResult],
        seed_map: dict[str, str],
        sub_field_mapping: dict[str, list[str]],
    ) -> CorpusStats:
        year_dist: dict[str, int] = defaultdict(int)
        for p in paper_map.values():
            year_str = (p.published_date or "")[:4]
            if year_str.isdigit():
                year_dist[year_str] += 1

        sf_coverage: dict[str, int] = {
            name: len(ids) for name, ids in sub_field_mapping.items()
        }

        return CorpusStats(
            total_papers=len(paper_map),
            seed_papers_found=len(seed_map),
            seed_papers_expected=len(scope.seed_papers),
            year_distribution=dict(year_dist),
            sub_field_coverage=sf_coverage,
        )

    @staticmethod
    def _count_authors(paper_map: dict[str, PaperResult]) -> dict[str, int]:
        """Count how many papers each author name appears in."""
        counts: dict[str, int] = defaultdict(int)
        for p in paper_map.values():
            for author in p.authors:
                counts[author] += 1
        return dict(counts)
