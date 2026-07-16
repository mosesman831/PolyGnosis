"""Formal consensus ranking: Reciprocal Rank Fusion, Borda Count, and Hybrid.

Ported from PolyGnosis boardroom_pipeline.py — deterministic Layer-2 ranking
over LLM per-axis scores so no single opinionated scorer dominates.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

SCORING_AXES = [
    "correctness",
    "efficiency",
    "maintainability",
    "robustness",
    "security",
]


def rrf_rank(solutions_scores: list[dict[str, Any]], k: int = 60) -> list[tuple[str, float]]:
    """
    Reciprocal Rank Fusion (Cormack et al., 2009).

    For each axis, rank solutions (1 = best). Score = Σ 1/(k + rank) across axes.
    Higher score = better.
    """
    n = len(solutions_scores)
    if n <= 1:
        return [(s["solution_id"], 1.0) for s in solutions_scores]

    rrf_scores: dict[str, float] = defaultdict(float)

    for axis in SCORING_AXES:
        ranked = sorted(
            solutions_scores,
            key=lambda s: s.get("scores", {}).get(axis, 0),
            reverse=True,
        )
        for rank, sol in enumerate(ranked, start=1):
            rrf_scores[sol["solution_id"]] += 1.0 / (k + rank)

    return sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)


def borda_rank(solutions_scores: list[dict[str, Any]]) -> list[tuple[str, float]]:
    """
    Borda Count (de Borda, 1781).

    Per axis: highest gets (n-1) points, lowest gets 0. Sum across axes.
    Higher total = better.
    """
    n = len(solutions_scores)
    if n <= 1:
        return [(s["solution_id"], 1.0) for s in solutions_scores]

    borda_totals: dict[str, float] = defaultdict(float)

    for axis in SCORING_AXES:
        ranked = sorted(
            solutions_scores,
            key=lambda s: s.get("scores", {}).get(axis, 0),
            reverse=True,
        )
        for idx, sol in enumerate(ranked):
            borda_totals[sol["solution_id"]] += n - 1 - idx

    return sorted(borda_totals.items(), key=lambda x: x[1], reverse=True)


def hybrid_rank(
    solutions_scores: list[dict[str, Any]], k: int = 60
) -> list[tuple[str, float, float, float]]:
    """
    Hybrid: average of RRF and Borda rank positions.

    Returns (solution_id, avg_rank, rrf_score, borda_score).
    Lower avg_rank = better.
    """
    n = len(solutions_scores)
    if n <= 1:
        sol_id = solutions_scores[0]["solution_id"]
        return [(sol_id, 1.0, 1.0, 1.0)]

    rrf = dict(rrf_rank(solutions_scores, k=k))
    borda = dict(borda_rank(solutions_scores))

    rrf_vals = sorted(rrf.values(), reverse=True)
    borda_vals = sorted(borda.values(), reverse=True)

    def rank_from_scores(val: float, sorted_vals: list[float]) -> int:
        return sorted_vals.index(val) + 1

    results: list[tuple[str, float, float, float]] = []
    for s in solutions_scores:
        sid = s["solution_id"]
        r = rank_from_scores(rrf.get(sid, 0.0), rrf_vals)
        b = rank_from_scores(borda.get(sid, 0.0), borda_vals)
        avg = (r + b) / 2.0
        results.append((sid, avg, rrf.get(sid, 0.0), borda.get(sid, 0.0)))

    return sorted(results, key=lambda x: x[1])


def compute_consensus_ranking(
    scoring_json: dict[str, Any] | None,
    algorithm: str = "hybrid",
    k: int = 60,
) -> dict[str, dict[str, Any]]:
    """
    Apply deterministic ranking to LLM per-axis scores.

    Returns solution_id → {rank, ...score fields}.
    """
    rankings = scoring_json.get("rankings", []) if scoring_json else []

    solutions_scores: list[dict[str, Any]] = []
    for r in rankings:
        solutions_scores.append(
            {
                "solution_id": r.get("solution_id", ""),
                "solver_label": r.get("solver_label", ""),
                "scores": r.get("scores", {}),
                "total": r.get("total", 0),
            }
        )

    if not solutions_scores:
        return {}

    if algorithm == "rrf":
        ranked = rrf_rank(solutions_scores, k=k)
    elif algorithm == "borda":
        ranked = borda_rank(solutions_scores)
    else:
        ranked = hybrid_rank(solutions_scores, k=k)

    result: dict[str, dict[str, Any]] = {}
    for i, item in enumerate(ranked):
        sid = str(item[0])
        if algorithm == "hybrid" and len(item) >= 4:
            result[sid] = {
                "rank": i + 1,
                "avg_rank": float(item[1]),
                "rrf_score": float(item[2]),
                "borda_score": float(item[3]),
            }
        else:
            result[sid] = {"rank": i + 1, "score": float(item[1])}

    return result
