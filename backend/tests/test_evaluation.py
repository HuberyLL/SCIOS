"""Tests for the academic evaluation module (paper scoring, scholar scoring, tiering, pruning)."""

from __future__ import annotations

import pytest

from src.agents.landscape.evaluation import (
    PaperScore,
    ScholarScore,
    apply_budget,
    compute_score_stats,
    filter_scholars,
    get_venue_score,
    score_papers,
    score_scholars,
    tier_papers,
)
from src.models.paper import PaperResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_paper(
    pid: str = "p1",
    citation_count: int = 10,
    influential: int = 3,
    year: str = "2022",
    venue: str = "",
    venue_type: str = "",
    fields: list[str] | None = None,
    ref_count: int = 0,
) -> PaperResult:
    return PaperResult(
        paper_id=pid,
        title=f"Paper {pid}",
        citation_count=citation_count,
        influential_citation_count=influential,
        published_date=year,
        venue=venue,
        venue_type=venue_type,
        fields_of_study=fields or [],
        reference_count=ref_count,
    )


# ---------------------------------------------------------------------------
# Venue score tests
# ---------------------------------------------------------------------------

class TestVenueScore:
    def test_tier1_exact_match(self):
        assert get_venue_score("NeurIPS", "") == 1.0
        assert get_venue_score("ICML", "") == 1.0

    def test_tier1_case_insensitive(self):
        assert get_venue_score("neurips", "") == 1.0

    def test_tier2_match(self):
        assert get_venue_score("EMNLP", "") == 0.7

    def test_tier3_match(self):
        assert get_venue_score("LREC", "") == 0.5

    def test_substring_match(self):
        score = get_venue_score(
            "Neural Information Processing Systems", "",
        )
        assert score == 1.0

    def test_unknown_journal_fallback(self):
        assert get_venue_score("Unknown Journal of Stuff", "Journal") == 0.4

    def test_unknown_conference_fallback(self):
        assert get_venue_score("Some Workshop", "Conference") == 0.3

    def test_preprint_fallback(self):
        assert get_venue_score("", "") == 0.1

    def test_empty_venue_with_type(self):
        assert get_venue_score("", "Journal") == 0.4

    # -- Cross-discipline venue tests --

    def test_cross_discipline_tier1(self):
        assert get_venue_score("Nature Medicine", "") == 1.0
        assert get_venue_score("The Lancet", "") == 1.0
        assert get_venue_score("Cell", "") == 1.0
        assert get_venue_score("Physical Review Letters", "") == 1.0
        assert get_venue_score("PNAS", "") == 1.0

    def test_cross_discipline_tier2(self):
        assert get_venue_score("Bioinformatics", "") == 0.7
        assert get_venue_score("eLife", "") == 0.7
        assert get_venue_score("Nature Machine Intelligence", "") == 0.7

    def test_non_cs_journal_fallback_higher(self):
        score = get_venue_score(
            "Unknown Bio Journal", "Journal",
            fields_of_study=["Biology", "Medicine"],
        )
        assert score == 0.55

    def test_non_cs_conference_fallback_higher(self):
        score = get_venue_score(
            "Unknown Bio Conference", "Conference",
            fields_of_study=["Biology"],
        )
        assert score == 0.45

    def test_non_cs_preprint_fallback_higher(self):
        score = get_venue_score(
            "", "",
            fields_of_study=["Physics"],
        )
        assert score == 0.15

    def test_cs_field_keeps_original_fallback(self):
        score = get_venue_score(
            "Unknown CS Workshop", "Conference",
            fields_of_study=["Computer Science", "Biology"],
        )
        assert score == 0.3


# ---------------------------------------------------------------------------
# Paper scoring tests
# ---------------------------------------------------------------------------

class TestScorePapers:
    def test_basic_scoring(self):
        papers = [
            _make_paper("p1", citation_count=100, influential=30, year="2020",
                        venue="NeurIPS"),
            _make_paper("p2", citation_count=5, influential=0, year="2023",
                        venue="", venue_type=""),
        ]
        scores = score_papers(papers, {}, {}, current_year=2025)
        assert len(scores) == 2
        assert all(isinstance(s, PaperScore) for s in scores)
        assert scores[0].composite >= scores[1].composite

    def test_empty_corpus(self):
        assert score_papers([], {}, {}) == []

    def test_single_paper(self):
        papers = [_make_paper("p1", citation_count=50, year="2020")]
        scores = score_papers(papers, {}, {}, current_year=2025)
        assert len(scores) == 1
        assert 0.0 <= scores[0].composite <= 1.0

    def test_seed_paper_marked_protected(self):
        papers = [_make_paper("seed1", citation_count=1, year="2010")]
        scores = score_papers(
            papers, {}, {},
            seed_paper_ids={"seed1"},
            current_year=2025,
        )
        assert scores[0].tier == "protected"

    def test_structural_score_uses_reference_graph(self):
        papers = [
            _make_paper("hub", citation_count=50, year="2020"),
            _make_paper("leaf", citation_count=5, year="2022"),
        ]
        ref_graph = {
            "leaf": ["hub"],
        }
        scores = score_papers(papers, {}, ref_graph, current_year=2025)
        hub_score = next(s for s in scores if s.paper_id == "hub")
        leaf_score = next(s for s in scores if s.paper_id == "leaf")
        assert hub_score.structural_score > leaf_score.structural_score

    def test_recency_favors_newer(self):
        old = _make_paper("old", citation_count=10, year="2005")
        new = _make_paper("new", citation_count=10, year="2024")
        scores = score_papers([old, new], {}, {}, current_year=2025)
        old_s = next(s for s in scores if s.paper_id == "old")
        new_s = next(s for s in scores if s.paper_id == "new")
        assert new_s.recency_score > old_s.recency_score

    def test_venue_score_propagated(self):
        p = _make_paper("v1", venue="CVPR", citation_count=10, year="2023")
        scores = score_papers([p], {}, {}, current_year=2025)
        assert scores[0].venue_score == 1.0


# ---------------------------------------------------------------------------
# Tiering tests
# ---------------------------------------------------------------------------

class TestTierPapers:
    def test_tier_distribution(self):
        papers = [_make_paper(f"p{i}", citation_count=i * 10, year="2022")
                  for i in range(20)]
        scores = score_papers(papers, {}, {}, current_year=2025)
        tiered = tier_papers(scores)
        tiers = {s.tier for s in tiered}
        assert "tier1" in tiers
        assert "tier2" in tiers
        assert "tier3" in tiers

    def test_protected_not_overwritten(self):
        papers = [_make_paper(f"p{i}", citation_count=1, year="2022") for i in range(10)]
        scores = score_papers(
            papers, {}, {},
            seed_paper_ids={"p0"},
            current_year=2025,
        )
        tiered = tier_papers(scores)
        p0 = next(s for s in tiered if s.paper_id == "p0")
        assert p0.tier == "protected"

    def test_all_protected(self):
        papers = [_make_paper("p0", citation_count=5)]
        scores = score_papers(papers, {}, {}, seed_paper_ids={"p0"})
        tiered = tier_papers(scores)
        assert tiered[0].tier == "protected"


# ---------------------------------------------------------------------------
# Budget pruning tests
# ---------------------------------------------------------------------------

class TestApplyBudget:
    def test_no_pruning_when_under_budget(self):
        papers = [_make_paper(f"p{i}") for i in range(50)]
        scores = score_papers(papers, {}, {})
        scores = tier_papers(scores)
        result = apply_budget(papers, scores, "narrow")
        assert len(result) == 50

    def test_pruning_respects_budget(self):
        papers = [_make_paper(f"p{i}", citation_count=i, year="2022")
                  for i in range(1000)]
        scores = score_papers(papers, {}, {}, current_year=2025)
        scores = tier_papers(scores)
        result = apply_budget(papers, scores, "narrow")
        assert len(result) <= 150

    def test_seed_papers_always_kept(self):
        papers = [_make_paper(f"p{i}", citation_count=i, year="2022")
                  for i in range(500)]
        scores = score_papers(
            papers, {}, {},
            seed_paper_ids={"p0"},
            current_year=2025,
        )
        scores = tier_papers(scores)
        result = apply_budget(papers, scores, "narrow")
        result_ids = {p.paper_id for p in result}
        assert "p0" in result_ids

    def test_broad_budget_larger(self):
        papers = [_make_paper(f"p{i}", citation_count=i, year="2022")
                  for i in range(1000)]
        scores = score_papers(papers, {}, {}, current_year=2025)
        scores = tier_papers(scores)
        narrow = apply_budget(papers, scores, "narrow")
        broad = apply_budget(papers, scores, "broad")
        assert len(broad) >= len(narrow)


# ---------------------------------------------------------------------------
# Score stats tests
# ---------------------------------------------------------------------------

class TestComputeScoreStats:
    def test_empty(self):
        stats = compute_score_stats([])
        assert stats["score_median"] == 0.0
        assert stats["tier_distribution"] == {}

    def test_basic(self):
        papers = [_make_paper(f"p{i}", citation_count=i * 5, year="2022")
                  for i in range(20)]
        scores = score_papers(papers, {}, {}, current_year=2025)
        scores = tier_papers(scores)
        stats = compute_score_stats(scores)
        assert stats["score_median"] > 0.0
        assert sum(stats["tier_distribution"].values()) == 20


# ---------------------------------------------------------------------------
# Scholar scoring tests
# ---------------------------------------------------------------------------

class TestScoreScholars:
    def test_basic_scoring(self):
        candidates = [
            {
                "author_id": "a1", "name": "Alice",
                "h_index": 40, "citation_count": 5000,
                "paper_count": 100, "corpus_paper_count": 10,
                "latest_year": 2024,
            },
            {
                "author_id": "a2", "name": "Bob",
                "h_index": 5, "citation_count": 50,
                "paper_count": 200, "corpus_paper_count": 2,
                "latest_year": 2015,
            },
        ]
        scored = score_scholars(candidates, current_year=2025)
        assert len(scored) == 2
        assert scored[0].author_id == "a1"
        assert scored[0].composite > scored[1].composite

    def test_empty(self):
        assert score_scholars([]) == []

    def test_single_scholar(self):
        candidates = [{
            "author_id": "a1", "name": "Solo",
            "h_index": 20, "citation_count": 1000,
            "paper_count": 50, "corpus_paper_count": 5,
            "latest_year": 2024,
        }]
        scored = score_scholars(candidates, current_year=2025)
        assert len(scored) == 1
        assert 0.0 <= scored[0].composite <= 1.0


# ---------------------------------------------------------------------------
# Scholar filtering tests
# ---------------------------------------------------------------------------

class TestFilterScholars:
    def test_filters_low_h_index(self):
        candidates_raw = [
            {"author_id": "a1", "name": "Low", "h_index": 3,
             "citation_count": 100, "paper_count": 50,
             "corpus_paper_count": 5, "latest_year": 2024},
            {"author_id": "a2", "name": "High", "h_index": 25,
             "citation_count": 5000, "paper_count": 100,
             "corpus_paper_count": 10, "latest_year": 2024},
        ]
        scored = score_scholars(candidates_raw, current_year=2025)
        filtered = filter_scholars(scored, candidates_raw)
        assert all(s.author_id != "a1" for s in filtered)

    def test_filters_low_corpus_papers(self):
        candidates_raw = [
            {"author_id": "a1", "name": "Sparse", "h_index": 20,
             "citation_count": 1000, "paper_count": 50,
             "corpus_paper_count": 1, "latest_year": 2024},
            {"author_id": "a2", "name": "Dense", "h_index": 20,
             "citation_count": 1000, "paper_count": 50,
             "corpus_paper_count": 10, "latest_year": 2024},
        ]
        scored = score_scholars(candidates_raw, current_year=2025)
        filtered = filter_scholars(scored, candidates_raw)
        assert all(s.author_id != "a1" for s in filtered)

    def test_top_k_cutoff(self):
        candidates_raw = [
            {"author_id": f"a{i}", "name": f"Scholar{i}",
             "h_index": 20 + i, "citation_count": 1000 + i * 100,
             "paper_count": 50, "corpus_paper_count": 5,
             "latest_year": 2024}
            for i in range(100)
        ]
        scored = score_scholars(candidates_raw, current_year=2025)
        filtered = filter_scholars(scored, candidates_raw)
        assert len(filtered) <= 50

    def test_empty(self):
        assert filter_scholars([], []) == []
