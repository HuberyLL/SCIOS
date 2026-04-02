"""Academic evaluation module — data-driven paper & scholar scoring.

Implements a 5-dimensional paper scoring model and a 4-dimensional scholar
scoring model aligned with standard bibliometric practices (FWCI-inspired
citation normalisation, CCF/CORE venue tiers, h-index).

All thresholds and weights are read from ``src.core.config.get_settings()``
so operators can tune behaviour without code changes.
"""

from __future__ import annotations

import logging
import math
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.core.config import get_settings
from src.models.paper import PaperResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Venue tier mapping — aligned with CCF Recommended List (CS focus)
# ---------------------------------------------------------------------------

_VENUE_TIER: dict[str, float] = {}


def _register(names: list[str], score: float) -> None:
    for n in names:
        _VENUE_TIER[n.lower()] = score


# Tier 1 (score = 1.0): CCF-A conferences & top journals
_register([
    # --- AI / ML ---
    "NeurIPS", "Neural Information Processing Systems",
    "ICML", "International Conference on Machine Learning",
    "ICLR", "International Conference on Learning Representations",
    "AAAI", "AAAI Conference on Artificial Intelligence",
    "IJCAI", "International Joint Conference on Artificial Intelligence",
    # --- NLP ---
    "ACL", "Annual Meeting of the Association for Computational Linguistics",
    "Association for Computational Linguistics",
    # --- CV ---
    "CVPR", "IEEE/CVF Conference on Computer Vision and Pattern Recognition",
    "Conference on Computer Vision and Pattern Recognition",
    "ICCV", "International Conference on Computer Vision",
    "ECCV", "European Conference on Computer Vision",
    # --- Data Mining / IR ---
    "KDD", "ACM SIGKDD",
    "SIGIR", "ACM SIGIR",
    "WWW", "The Web Conference",
    # --- Systems ---
    "OSDI", "USENIX Symposium on Operating Systems Design and Implementation",
    "SOSP", "ACM Symposium on Operating Systems Principles",
    "NSDI",
    # --- SE ---
    "ICSE", "International Conference on Software Engineering",
    "FSE", "Foundations of Software Engineering",
    # --- DB ---
    "SIGMOD", "ACM SIGMOD",
    "VLDB", "Very Large Data Bases",
    # --- Architecture ---
    "ISCA", "International Symposium on Computer Architecture",
    "MICRO",
    "HPCA",
    # --- Security ---
    "IEEE Symposium on Security and Privacy",
    "S&P",
    "CCS", "ACM Conference on Computer and Communications Security",
    "USENIX Security",
    # --- Top journals ---
    "Nature", "Science",
    "JMLR", "Journal of Machine Learning Research",
    "TPAMI", "IEEE Transactions on Pattern Analysis and Machine Intelligence",
    "TKDE", "IEEE Transactions on Knowledge and Data Engineering",
    "TIP", "IEEE Transactions on Image Processing",
    "TNNLS", "IEEE Transactions on Neural Networks and Learning Systems",
    "AIJ", "Artificial Intelligence",
    "TACL", "Transactions of the Association for Computational Linguistics",
    "IJCV", "International Journal of Computer Vision",
], 1.0)

# Tier 2 (score = 0.7): CCF-B / strong venues
_register([
    "EMNLP", "Empirical Methods in Natural Language Processing",
    "NAACL",
    "COLING",
    "EACL",
    "AISTATS",
    "UAI",
    "COLT",
    "ICRA",
    "IROS",
    "WACV",
    "BMVC",
    "MM", "ACM Multimedia",
    "RecSys",
    "CIKM",
    "ICDM",
    "SDM",
    "PAKDD",
    "ECML",
    "ECML-PKDD",
    "WSDM",
    "EMNLP Findings",
    "ACL Findings",
    "INTERSPEECH",
    "ICASSP",
    "MICCAI",
    "BIBM",
    "ASE",
    "ISSTA",
    "ICPC",
    "MIDDLEWARE",
    "EuroSys",
    "ATC", "USENIX Annual Technical Conference",
    "INFOCOM",
    "NDSS",
    "RAID",
    "IMC",
    "CoNEXT",
    "Pattern Recognition",
    "Neural Networks",
    "Knowledge-Based Systems",
    "Information Sciences",
    "Expert Systems with Applications",
    "Neurocomputing",
    "IEEE Transactions on Cybernetics",
    "ACM Computing Surveys",
    "IEEE Communications Surveys & Tutorials",
    "Computational Linguistics",
], 0.7)

# Tier 3 (score = 0.5): CCF-C / workshops / regional venues
_register([
    "LREC",
    "CONLL", "CoNLL",
    "SemEval",
    "ESWC",
    "ISWC",
    "KSEM",
    "ICONIP",
    "PRICAI",
    "ACML",
    "IJCNN",
    "CEC",
    "GECCO",
    "ICPR",
    "ACCV",
    "FG",
    "ICDAR",
    "ECAI",
    "IUI",
    "UIST",
    "CHI",
    "CSCW",
    "MobiCom",
    "SenSys",
    "IPDPS",
    "SC",
    "ICS",
    "PPoPP",
    "ASPLOS",
    "DATE",
    "DAC",
    "CASES",
    "IEEE Access",
    "Applied Sciences",
    "Sensors",
    "Electronics",
    "Mathematics",
    "Symmetry",
    "PLOS ONE",
    "Scientific Reports",
    "Frontiers in Artificial Intelligence",
], 0.5)

# ---------------------------------------------------------------------------
# Cross-discipline top venues (non-CS)
# ---------------------------------------------------------------------------

# Tier 1 cross-discipline: Nature family, top medical, physics, multidisciplinary
_register([
    # --- Multidisciplinary ---
    "PNAS", "Proceedings of the National Academy of Sciences",
    "Nature Communications",
    "Science Advances",
    # --- Biomedical ---
    "Nature Medicine",
    "Nature Biotechnology",
    "Nature Methods",
    "Nature Genetics",
    "The Lancet", "Lancet",
    "Cell",
    "The New England Journal of Medicine", "NEJM",
    "BMJ",
    "JAMA",
    # --- Physics ---
    "Physical Review Letters", "PRL",
    "Nature Physics",
    "Reviews of Modern Physics",
    # --- Materials ---
    "Nature Materials",
    "Advanced Materials",
    # --- Medical Imaging (overlap with CS) ---
    "IEEE Transactions on Medical Imaging", "IEEE TMI",
    "Medical Image Analysis",
], 1.0)

# Tier 2 cross-discipline
_register([
    "Nature Machine Intelligence",
    "Nature Computational Science",
    "Nature Human Behaviour",
    "Nucleic Acids Research",
    "Bioinformatics",
    "PLOS Medicine",
    "IEEE Journal of Biomedical and Health Informatics",
    "Journal of Chemical Information and Modeling",
    "Physical Review X",
    "npj Computational Materials",
    "ACS Nano",
    "Genome Research",
    "Genome Biology",
    "eLife",
], 0.7)

# CS fields recognised by Semantic Scholar for fallback adjustment
_CS_FIELDS = frozenset({
    "computer science", "mathematics",
})


def get_venue_score(
    venue_name: str,
    venue_type: str,
    fields_of_study: list[str] | None = None,
) -> float:
    """Look up venue quality score from the tier table.

    Falls back to type-based defaults for unmatched venues.  When the
    paper's ``fields_of_study`` are entirely outside CS/Math, fallback
    scores are raised to avoid systematic penalisation of non-CS work.
    """
    if venue_name:
        key = venue_name.strip().lower()
        if key in _VENUE_TIER:
            return _VENUE_TIER[key]
        for registered, score in _VENUE_TIER.items():
            if registered in key or key in registered:
                return score

    is_non_cs = False
    if fields_of_study:
        is_non_cs = all(
            f.strip().lower() not in _CS_FIELDS for f in fields_of_study
        )

    vt = venue_type.strip().lower() if venue_type else ""
    if vt == "journal":
        return 0.55 if is_non_cs else 0.4
    if vt == "conference":
        return 0.45 if is_non_cs else 0.3
    return 0.15 if is_non_cs else 0.1


# ---------------------------------------------------------------------------
# Paper scoring
# ---------------------------------------------------------------------------

class PaperScore(BaseModel):
    paper_id: str
    citation_impact: float = 0.0
    influential_ratio: float = 0.0
    venue_score: float = 0.0
    recency_score: float = 0.0
    structural_score: float = 0.0
    composite: float = 0.0
    tier: Literal["tier1", "tier2", "tier3", "protected"] = "tier3"


def score_papers(
    papers: list[PaperResult],
    citation_graph: dict[str, list[str]],
    reference_graph: dict[str, list[str]],
    *,
    seed_paper_ids: set[str] | None = None,
    current_year: int | None = None,
) -> list[PaperScore]:
    """Score every paper on 5 dimensions and return sorted results."""
    if not papers:
        return []

    cfg = get_settings()
    now = current_year or datetime.now().year
    seed_ids = seed_paper_ids or set()

    # Pre-compute annual citation rates for percentile ranking
    annual_rates: dict[str, float] = {}
    for p in papers:
        year = _extract_year(p)
        age = max(1, now - year) if year else 1
        annual_rates[p.paper_id] = p.citation_count / age

    sorted_rates = sorted(annual_rates.values())
    rate_count = len(sorted_rates)

    # Pre-compute corpus in-degree (how many corpus papers cite this one)
    corpus_in_degree: dict[str, int] = defaultdict(int)
    for pid, refs in reference_graph.items():
        for ref_id in refs:
            corpus_in_degree[ref_id] += 1
    max_in_degree = max(corpus_in_degree.values()) if corpus_in_degree else 1

    results: list[PaperScore] = []
    for p in papers:
        # Dim 1: Citation Impact (percentile of annual citation rate)
        rate = annual_rates[p.paper_id]
        rank = _bisect_right(sorted_rates, rate)
        citation_impact = rank / rate_count

        # Dim 2: Influential citation ratio
        inf_ratio = (
            p.influential_citation_count / max(1, p.citation_count)
            if p.citation_count > 0
            else 0.0
        )

        # Dim 3: Venue score
        v_score = get_venue_score(p.venue, p.venue_type, p.fields_of_study)

        # Dim 4: Recency
        year = _extract_year(p)
        age = max(1, now - year) if year else 10
        recency = 1.0 / (1.0 + math.log2(max(1, age)))

        # Dim 5: Structural importance
        structural = corpus_in_degree.get(p.paper_id, 0) / max(1, max_in_degree)

        composite = (
            cfg.eval_weight_citation * citation_impact
            + cfg.eval_weight_influential * inf_ratio
            + cfg.eval_weight_venue * v_score
            + cfg.eval_weight_recency * recency
            + cfg.eval_weight_structural * structural
        )

        tier: Literal["tier1", "tier2", "tier3", "protected"] = "tier3"
        if p.paper_id in seed_ids:
            tier = "protected"

        results.append(PaperScore(
            paper_id=p.paper_id,
            citation_impact=round(citation_impact, 4),
            influential_ratio=round(inf_ratio, 4),
            venue_score=round(v_score, 4),
            recency_score=round(recency, 4),
            structural_score=round(structural, 4),
            composite=round(composite, 4),
            tier=tier,
        ))

    results.sort(key=lambda s: s.composite, reverse=True)
    return results


def tier_papers(scores: list[PaperScore]) -> list[PaperScore]:
    """Assign tier labels based on percentile cutoffs (protected papers keep their tier)."""
    cfg = get_settings()
    non_protected = [s for s in scores if s.tier != "protected"]
    if not non_protected:
        return scores

    non_protected.sort(key=lambda s: s.composite, reverse=True)
    n = len(non_protected)
    t1_cutoff = max(1, int(n * cfg.eval_tier1_pct))
    t2_cutoff = max(t1_cutoff, int(n * cfg.eval_tier2_pct))

    for i, s in enumerate(non_protected):
        if i < t1_cutoff:
            s.tier = "tier1"
        elif i < t2_cutoff:
            s.tier = "tier2"
        else:
            s.tier = "tier3"

    return scores


def apply_budget(
    papers: list[PaperResult],
    scores: list[PaperScore],
    complexity: Literal["narrow", "medium", "broad"],
) -> list[PaperResult]:
    """Prune papers to fit within budget while preserving protected + tier1."""
    cfg = get_settings()
    budget_map = {
        "narrow": cfg.eval_budget_narrow,
        "medium": cfg.eval_budget_medium,
        "broad": cfg.eval_budget_broad,
    }
    budget = budget_map.get(complexity, cfg.eval_budget_medium)

    if len(papers) <= budget:
        return papers

    score_map = {s.paper_id: s for s in scores}
    paper_map = {p.paper_id: p for p in papers}

    kept_ids: list[str] = []
    tier2_candidates: list[tuple[str, float]] = []

    for s in scores:
        if s.tier == "protected" or s.tier == "tier1":
            kept_ids.append(s.paper_id)
        elif s.tier == "tier2":
            tier2_candidates.append((s.paper_id, s.composite))

    tier2_candidates.sort(key=lambda x: x[1], reverse=True)
    remaining_budget = budget - len(kept_ids)
    if remaining_budget > 0:
        for pid, _ in tier2_candidates[:remaining_budget]:
            kept_ids.append(pid)

    kept_set = set(kept_ids)
    result = [paper_map[pid] for pid in kept_ids if pid in paper_map]

    logger.info(
        "Budget pruning: %d -> %d papers (budget=%d, protected+t1=%d, t2_filled=%d)",
        len(papers), len(result), budget,
        sum(1 for s in scores if s.tier in ("protected", "tier1")),
        min(remaining_budget, len(tier2_candidates)) if remaining_budget > 0 else 0,
    )
    return result


def compute_score_stats(scores: list[PaperScore]) -> dict:
    """Return summary statistics for CorpusStats integration."""
    if not scores:
        return {"score_median": 0.0, "score_mean": 0.0, "tier_distribution": {}}

    composites = [s.composite for s in scores]
    tier_dist: dict[str, int] = defaultdict(int)
    for s in scores:
        tier_dist[s.tier] += 1

    return {
        "score_median": round(statistics.median(composites), 4),
        "score_mean": round(statistics.mean(composites), 4),
        "tier_distribution": dict(tier_dist),
    }


# ---------------------------------------------------------------------------
# Scholar scoring
# ---------------------------------------------------------------------------

class ScholarScore(BaseModel):
    author_id: str
    name: str = ""
    h_index_norm: float = 0.0
    field_relevance: float = 0.0
    citation_impact: float = 0.0
    activity_recency: float = 0.0
    composite: float = 0.0


def score_scholars(
    candidates: list[dict],
    *,
    current_year: int | None = None,
) -> list[ScholarScore]:
    """Score scholar candidates on 4 dimensions.

    Each candidate dict must contain:
      - author_id: str
      - name: str
      - h_index: int
      - citation_count: int
      - paper_count: int            (total from S2)
      - corpus_paper_count: int     (papers in current corpus)
      - latest_year: int | None     (most recent publication year in corpus)
    """
    if not candidates:
        return []

    now = current_year or datetime.now().year

    h_indices = sorted(c.get("h_index", 0) for c in candidates)
    cite_counts = sorted(c.get("citation_count", 0) for c in candidates)
    n = len(candidates)

    results: list[ScholarScore] = []
    for c in candidates:
        h_idx = c.get("h_index", 0)
        h_rank = _bisect_right(h_indices, h_idx)
        h_norm = h_rank / n

        total_papers = max(1, c.get("paper_count", 1))
        corpus_papers = c.get("corpus_paper_count", 0)
        relevance = min(1.0, corpus_papers / total_papers)

        cite = c.get("citation_count", 0)
        cite_rank = _bisect_right(cite_counts, cite)
        cite_norm = cite_rank / n

        latest = c.get("latest_year")
        if latest and latest > 0:
            gap = max(0, now - latest)
            activity = 1.0 / (1.0 + math.log2(max(1, gap + 1)))
        else:
            activity = 0.3

        cfg = get_settings()
        composite = (
            cfg.scholar_weight_h_index * h_norm
            + cfg.scholar_weight_relevance * relevance
            + cfg.scholar_weight_citation * cite_norm
            + cfg.scholar_weight_activity * activity
        )

        results.append(ScholarScore(
            author_id=c.get("author_id", ""),
            name=c.get("name", ""),
            h_index_norm=round(h_norm, 4),
            field_relevance=round(relevance, 4),
            citation_impact=round(cite_norm, 4),
            activity_recency=round(activity, 4),
            composite=round(composite, 4),
        ))

    results.sort(key=lambda s: s.composite, reverse=True)
    return results


def filter_scholars(
    scholars: list[ScholarScore],
    candidates_raw: list[dict],
) -> list[ScholarScore]:
    """Apply hard thresholds and top-K cutoff."""
    cfg = get_settings()
    raw_map = {c["author_id"]: c for c in candidates_raw}

    filtered: list[ScholarScore] = []
    for s in scholars:
        raw = raw_map.get(s.author_id, {})
        h = raw.get("h_index", 0)
        corpus_papers = raw.get("corpus_paper_count", 0)
        if h < cfg.scholar_min_h_index:
            continue
        if corpus_papers < cfg.scholar_min_corpus_papers:
            continue
        filtered.append(s)

    return filtered[: cfg.scholar_top_k]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_year(paper: PaperResult) -> int | None:
    """Best-effort year extraction from published_date."""
    if not paper.published_date:
        return None
    try:
        return int(paper.published_date[:4])
    except (ValueError, IndexError):
        return None


def _bisect_right(sorted_list: list, value: float) -> int:
    """Return the number of elements <= value (equivalent to bisect.bisect_right)."""
    lo, hi = 0, len(sorted_list)
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_list[mid] <= value:
            lo = mid + 1
        else:
            hi = mid
    return lo
