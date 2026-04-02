"""Network Agent — builds a rich collaboration network via S2 Author API.

Key improvement over the old graph_builder: instead of relying only on
co-authorship within the small retrieved corpus, this agent:
  1. Identifies high-impact authors adaptively (no fixed K cap)
  2. Fetches their full profiles via S2 Author API
  3. Fetches their recent papers to build co-authorship from a larger sample
  4. Constructs a richer collaboration network
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from itertools import combinations

from src.models.landscape import (
    CollaborationEdge,
    CollaborationNetwork,
    ScholarNode,
)
from src.models.paper import PaperResult

from ...tools import SemanticScholarClient
from ..schemas import AuthorProfile, PaperCorpus
from .base import BaseAgent, ProgressCallback

logger = logging.getLogger(__name__)

# Per-unit limits (per API call)
AUTHOR_PAPERS_LIMIT = 100     # papers fetched per author
PROFILE_BATCH_SIZE = 5        # concurrent profile fetches
MIN_SHARED_PAPERS = 1

# Adaptive author selection: include authors appearing in >= threshold papers.
# Threshold is computed from corpus distribution (see _identify_top_authors).
MIN_AUTHOR_APPEARANCES = 2    # absolute floor


class _AuthorCandidate:
    """Intermediate holder: may have a resolved S2 authorId or just a name."""
    __slots__ = ("author_id", "name", "score")

    def __init__(self, *, author_id: str, name: str, score: float) -> None:
        self.author_id = author_id
        self.name = name
        self.score = score


class NetworkAgent(BaseAgent[PaperCorpus, CollaborationNetwork]):
    """Stage 4a: build a collaboration network from Author API data."""

    def __init__(self) -> None:
        super().__init__(name="NetworkAgent")
        self._client = SemanticScholarClient()

    async def _execute(
        self,
        corpus: PaperCorpus,
        *,
        on_progress: ProgressCallback = None,
    ) -> CollaborationNetwork:
        # Step 1: Identify high-impact authors from the corpus
        await self._notify(on_progress, "identifying top authors …")
        candidates = self._identify_top_authors(corpus)
        self._logger.info("Identified %d top author candidates", len(candidates))

        if not candidates:
            self._logger.warning("No authors found — building co-authorship fallback")
            return self._coauthorship_fallback(corpus)

        # Step 2: Fetch author profiles (ID-first, name-search fallback)
        await self._notify(on_progress, "fetching author profiles …")
        profiles = await self._fetch_profiles(candidates)
        self._logger.info("Fetched %d author profiles", len(profiles))

        # Step 2+: Profile success-rate check — retry with lower threshold
        success_rate = len(profiles) / max(len(candidates), 1)
        if success_rate < 0.3 and len(profiles) < 5:
            self._logger.warning(
                "Profile success rate %.0f%% too low, retrying with halved threshold",
                success_rate * 100,
            )
            await self._notify(on_progress, "retrying author identification with lower threshold …")
            candidates = self._identify_top_authors(corpus, threshold_divisor=2)
            profiles = await self._fetch_profiles(candidates)
            self._logger.info("Retry: %d profiles from %d candidates", len(profiles), len(candidates))

        # Step 3: Fetch papers for each author to expand co-authorship data
        await self._notify(on_progress, "fetching author paper histories …")
        author_papers = await self._fetch_author_papers(
            [p.author_id for p in profiles],
        )

        # Step 4: Build the collaboration network
        await self._notify(on_progress, "constructing co-authorship network …")
        network = self._build_network(profiles, author_papers, corpus)

        # Step 4+: Empty-network fallback — build from corpus co-authorship
        if not network.nodes:
            self._logger.warning("Network is empty after API approach — using co-authorship fallback")
            network = self._coauthorship_fallback(corpus)

        self._logger.info(
            "CollaborationNetwork: %d scholars, %d edges",
            len(network.nodes), len(network.edges),
        )
        return network

    # ------------------------------------------------------------------
    # Step 1
    # ------------------------------------------------------------------

    def _identify_top_authors(
        self, corpus: PaperCorpus, *, threshold_divisor: int = 1,
    ) -> list[_AuthorCandidate]:
        """Select high-impact authors adaptively based on corpus distribution.

        Prioritises authorId from paper metadata. For papers without
        authorIds, falls back to name-based grouping as a last resort.
        ``threshold_divisor`` > 1 lowers the adaptive threshold for retries.
        """
        id_score: dict[str, float] = defaultdict(float)
        id_count: dict[str, int] = defaultdict(int)
        id_to_name: dict[str, str] = {}

        name_score: dict[str, float] = defaultdict(float)
        name_count: dict[str, int] = defaultdict(int)

        for p in corpus.papers:
            if not p.authors:
                continue
            per_author_cite = p.citation_count / max(len(p.authors), 1)
            bump = 1 + (per_author_cite * 0.01)

            for idx, author_name in enumerate(p.authors):
                aid = p.author_ids[idx] if idx < len(p.author_ids) else ""
                if aid:
                    id_count[aid] += 1
                    id_score[aid] += bump
                    if aid not in id_to_name or len(author_name) > len(id_to_name[aid]):
                        id_to_name[aid] = author_name
                else:
                    name_count[author_name] += 1
                    name_score[author_name] += bump

        all_counts = list(id_count.values()) + list(name_count.values())
        if not all_counts:
            return []

        all_counts.sort(reverse=True)
        p90_idx = max(0, len(all_counts) // 10 - 1)
        adaptive_threshold = max(
            MIN_AUTHOR_APPEARANCES,
            all_counts[p90_idx] if p90_idx < len(all_counts) else MIN_AUTHOR_APPEARANCES,
        )
        if threshold_divisor > 1:
            adaptive_threshold = max(MIN_AUTHOR_APPEARANCES, adaptive_threshold // threshold_divisor)

        candidates: list[_AuthorCandidate] = []
        for aid, score in id_score.items():
            if id_count[aid] >= adaptive_threshold:
                candidates.append(_AuthorCandidate(
                    author_id=aid, name=id_to_name.get(aid, ""), score=score,
                ))
        for name, score in name_score.items():
            if name_count[name] >= adaptive_threshold:
                candidates.append(_AuthorCandidate(
                    author_id="", name=name, score=score,
                ))

        candidates.sort(key=lambda c: c.score, reverse=True)

        id_resolved = sum(1 for c in candidates if c.author_id)
        self._logger.info(
            "Author selection: threshold=%d, %d candidates (%d with authorId, %d name-only)",
            adaptive_threshold, len(candidates), id_resolved,
            len(candidates) - id_resolved,
        )

        return candidates

    # ------------------------------------------------------------------
    # Step 2
    # ------------------------------------------------------------------

    async def _fetch_profiles(
        self, candidates: list[_AuthorCandidate],
    ) -> list[AuthorProfile]:
        """Resolve candidates to S2 author profiles.

        Uses a two-track strategy:
        - Candidates with an authorId → direct ``get_author()`` call (fast, exact)
        - Candidates with only a name → paper-search fallback (slow, fuzzy)
        """
        profiles: list[AuthorProfile] = []
        seen_ids: set[str] = set()

        async def _resolve_by_id(aid: str) -> AuthorProfile | None:
            author_data = await self._client.get_author(aid)
            if not author_data:
                return None
            return AuthorProfile(
                author_id=author_data.get("authorId", aid),
                name=author_data.get("name", ""),
                affiliations=author_data.get("affiliations") or [],
                paper_count=author_data.get("paperCount", 0) or 0,
                citation_count=author_data.get("citationCount", 0) or 0,
                h_index=author_data.get("hIndex", 0) or 0,
            )

        async def _resolve_by_name(name: str) -> AuthorProfile | None:
            result = await self._client.search_papers(name, limit=5)
            for p in result.papers:
                raw_list = await self._client.get_papers_batch(
                    [p.paper_id],
                    fields=["authors.authorId", "authors.affiliations", "authors"],
                )
                for raw in raw_list:
                    for a in (raw.get("authors") or []):
                        if not isinstance(a, dict):
                            continue
                        a_name = a.get("name", "")
                        a_id = a.get("authorId", "")
                        if a_id and _name_match(name, a_name):
                            return await _resolve_by_id(a_id)
            return None

        async def _resolve(candidate: _AuthorCandidate) -> AuthorProfile | None:
            if candidate.author_id:
                return await _resolve_by_id(candidate.author_id)
            return await _resolve_by_name(candidate.name)

        for i in range(0, len(candidates), PROFILE_BATCH_SIZE):
            batch = candidates[i : i + PROFILE_BATCH_SIZE]
            results = await asyncio.gather(
                *[_resolve(c) for c in batch],
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, Exception) or r is None:
                    continue
                if r.author_id not in seen_ids:
                    seen_ids.add(r.author_id)
                    profiles.append(r)

        id_resolved = sum(1 for c in candidates if c.author_id)
        self._logger.info(
            "Profile resolution: %d/%d by ID, %d/%d by name-search",
            min(id_resolved, len(profiles)), id_resolved,
            max(0, len(profiles) - id_resolved), len(candidates) - id_resolved,
        )

        return profiles

    # ------------------------------------------------------------------
    # Step 3
    # ------------------------------------------------------------------

    async def _fetch_author_papers(
        self, author_ids: list[str],
    ) -> dict[str, list[PaperResult]]:
        """Fetch recent papers for each author."""
        result: dict[str, list[PaperResult]] = {}
        failed_count = 0

        async def _fetch_one(aid: str):
            papers = await self._client.get_author_papers(
                aid, limit=AUTHOR_PAPERS_LIMIT,
            )
            return aid, papers

        for i in range(0, len(author_ids), PROFILE_BATCH_SIZE):
            batch = author_ids[i : i + PROFILE_BATCH_SIZE]
            results = await asyncio.gather(
                *[_fetch_one(aid) for aid in batch],
                return_exceptions=True,
            )
            for idx, r in enumerate(results):
                if isinstance(r, Exception):
                    failed_count += 1
                    self._logger.warning(
                        "Failed to fetch papers for author '%s': %s",
                        batch[idx], r,
                    )
                    continue
                aid, papers = r
                result[aid] = papers

        if failed_count:
            self._logger.info(
                "Author paper fetch: %d succeeded, %d failed",
                len(result), failed_count,
            )
        return result

    # ------------------------------------------------------------------
    # Step 4
    # ------------------------------------------------------------------

    def _build_network(
        self,
        profiles: list[AuthorProfile],
        author_papers: dict[str, list[PaperResult]],
        corpus: PaperCorpus,
    ) -> CollaborationNetwork:
        """Build co-authorship network from author paper histories."""
        profile_map = {p.author_id: p for p in profiles}
        profile_name_to_id = {p.name.lower(): p.author_id for p in profiles}
        corpus_pids = {p.paper_id for p in corpus.papers}

        paper_author_sets: dict[str, set[str]] = defaultdict(set)

        for aid, papers in author_papers.items():
            for p in papers:
                if p.paper_id:
                    paper_author_sets[p.paper_id].add(aid)
                    for coauthor_name in p.authors:
                        co_id = profile_name_to_id.get(coauthor_name.lower())
                        if co_id and co_id != aid:
                            paper_author_sets[p.paper_id].add(co_id)

        edge_counter: dict[tuple[str, str], list[str]] = defaultdict(list)
        for pid, aid_set in paper_author_sets.items():
            known = [a for a in aid_set if a in profile_map]
            for a, b in combinations(sorted(known), 2):
                edge_counter[(a, b)].append(pid)

        nodes: list[ScholarNode] = []
        connected_ids: set[str] = set()
        for (a, b), shared in edge_counter.items():
            if len(shared) >= MIN_SHARED_PAPERS:
                connected_ids.add(a)
                connected_ids.add(b)

        for aid in connected_ids:
            prof = profile_map.get(aid)
            if not prof:
                continue
            top_papers = []
            for p in (author_papers.get(aid) or []):
                if p.paper_id in corpus_pids:
                    top_papers.append((p.paper_id, p.citation_count))
            top_papers.sort(key=lambda x: x[1], reverse=True)

            nodes.append(ScholarNode(
                scholar_id=aid,
                name=prof.name,
                affiliations=prof.affiliations,
                paper_count=prof.paper_count,
                citation_count=prof.citation_count,
                top_paper_ids=[pid for pid, _ in top_papers[:10]],
            ))

        edges: list[CollaborationEdge] = []
        for (src, tgt), shared_pids in edge_counter.items():
            if src not in connected_ids or tgt not in connected_ids:
                continue
            if len(shared_pids) < MIN_SHARED_PAPERS:
                continue
            corpus_shared = [pid for pid in shared_pids if pid in corpus_pids]
            edges.append(CollaborationEdge(
                source=src,
                target=tgt,
                weight=len(shared_pids),
                shared_paper_ids=corpus_shared[:20],
            ))

        return CollaborationNetwork(nodes=nodes, edges=edges)


    @staticmethod
    def _coauthorship_fallback(corpus: PaperCorpus) -> CollaborationNetwork:
        """Build a lightweight network from corpus co-authorship (no API calls)."""
        author_papers: dict[str, list[str]] = defaultdict(list)
        author_cite: dict[str, int] = defaultdict(int)

        for p in corpus.papers:
            for name in p.authors:
                author_papers[name].append(p.paper_id)
                author_cite[name] += p.citation_count

        top_authors = sorted(
            author_papers.keys(),
            key=lambda n: (len(author_papers[n]), author_cite[n]),
            reverse=True,
        )[:50]
        top_set = set(top_authors)

        paper_coauthors: dict[str, set[str]] = defaultdict(set)
        for p in corpus.papers:
            present = [a for a in p.authors if a in top_set]
            for a in present:
                paper_coauthors[p.paper_id].update(present)

        edge_counter: dict[tuple[str, str], list[str]] = defaultdict(list)
        for pid, authors in paper_coauthors.items():
            for a, b in combinations(sorted(authors), 2):
                edge_counter[(a, b)].append(pid)

        connected: set[str] = set()
        for (a, b), shared in edge_counter.items():
            if len(shared) >= MIN_SHARED_PAPERS:
                connected.add(a)
                connected.add(b)

        corpus_pids = {p.paper_id for p in corpus.papers}
        nodes = [
            ScholarNode(
                scholar_id=f"name:{name}",
                name=name,
                paper_count=len(author_papers[name]),
                citation_count=author_cite[name],
                top_paper_ids=author_papers[name][:5],
            )
            for name in connected
        ]
        name_to_id = {n.name: n.scholar_id for n in nodes}

        edges = [
            CollaborationEdge(
                source=name_to_id[a],
                target=name_to_id[b],
                weight=len(shared),
                shared_paper_ids=[pid for pid in shared if pid in corpus_pids][:20],
            )
            for (a, b), shared in edge_counter.items()
            if a in connected and b in connected and len(shared) >= MIN_SHARED_PAPERS
        ]

        return CollaborationNetwork(nodes=nodes, edges=edges)


def _name_match(query: str, candidate: str) -> bool:
    """Multi-factor name matching to reduce ambiguity.

    Scoring:
      1.0 — normalised full names are identical
      0.8 — last name + first initial match
      0.3 — last name only
    Threshold: >= 0.6 to accept.
    """
    score = _name_match_score(query, candidate)
    return score >= 0.6


def _name_match_score(query: str, candidate: str) -> float:
    """Return a 0-1 similarity score between two author name strings."""
    q = _normalise_name(query)
    c = _normalise_name(candidate)
    if not q or not c:
        return 0.0

    q_parts = q.split()
    c_parts = c.split()

    if q == c:
        return 1.0

    q_last = q_parts[-1]
    c_last = c_parts[-1]

    if q_last != c_last:
        return 0.0

    q_firsts = q_parts[:-1]
    c_firsts = c_parts[:-1]

    if q_firsts and c_firsts:
        if q_firsts[0] == c_firsts[0]:
            return 0.9
        if q_firsts[0][0] == c_firsts[0][0]:
            return 0.8

    return 0.3


def _normalise_name(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    import re
    return re.sub(r"\s+", " ", re.sub(r"[.\-,]", " ", name.lower())).strip()
