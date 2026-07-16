"""Unit tests for RRF / Borda / hybrid consensus ranking."""

from polygnosis_api.consensus import (
    borda_rank,
    compute_consensus_ranking,
    hybrid_rank,
    rrf_rank,
)


def _sample_scores():
    # s0 wins correctness+security, s1 wins efficiency+maintainability, s2 wins robustness
    return [
        {
            "solution_id": "s0",
            "solver_label": "A",
            "scores": {
                "correctness": 9,
                "efficiency": 5,
                "maintainability": 5,
                "robustness": 6,
                "security": 9,
            },
        },
        {
            "solution_id": "s1",
            "solver_label": "B",
            "scores": {
                "correctness": 7,
                "efficiency": 9,
                "maintainability": 9,
                "robustness": 5,
                "security": 6,
            },
        },
        {
            "solution_id": "s2",
            "solver_label": "C",
            "scores": {
                "correctness": 6,
                "efficiency": 6,
                "maintainability": 6,
                "robustness": 9,
                "security": 5,
            },
        },
    ]


def test_rrf_rank_order_and_formula():
    ranked = rrf_rank(_sample_scores(), k=60)
    by_id = dict(ranked)
    # Each axis: rank1 → 1/61, rank2 → 1/62, rank3 → 1/63
    # s0: corr1, eff3, maint3, rob2, sec1
    expected_s0 = 2 * (1 / 61) + (1 / 62) + 2 * (1 / 63)
    # s1: corr2, eff1, maint1, rob3, sec2
    expected_s1 = 2 * (1 / 61) + 2 * (1 / 62) + (1 / 63)
    # s2: corr3, eff2, maint2, rob1, sec3
    expected_s2 = (1 / 61) + 2 * (1 / 62) + 2 * (1 / 63)
    assert abs(by_id["s0"] - expected_s0) < 1e-9
    assert abs(by_id["s1"] - expected_s1) < 1e-9
    assert abs(by_id["s2"] - expected_s2) < 1e-9
    assert expected_s1 > expected_s0 > expected_s2
    assert [sid for sid, _ in ranked] == ["s1", "s0", "s2"]


def test_borda_rank_points():
    ranked = borda_rank(_sample_scores())
    # n=3 → points 2,1,0 per axis
    # s0: corr2 + eff0 + maint0 + rob1 + sec2 = 5
    # s1: corr1 + eff2 + maint2 + rob0 + sec1 = 6
    # s2: corr0 + eff1 + maint1 + rob2 + sec0 = 4
    by_id = dict(ranked)
    assert by_id["s1"] == 6
    assert by_id["s0"] == 5
    assert by_id["s2"] == 4
    assert ranked[0][0] == "s1"


def test_hybrid_averages_rank_positions():
    ranked = hybrid_rank(_sample_scores(), k=60)
    # RRF order: s1, s0, s2 → ranks 1,2,3
    # Borda order: s1, s0, s2 → ranks 1,2,3
    # avg: s1=1.0, s0=2.0, s2=3.0
    by_id = {sid: (avg, rrf, borda) for sid, avg, rrf, borda in ranked}
    assert by_id["s1"][0] == 1.0
    assert by_id["s0"][0] == 2.0
    assert by_id["s2"][0] == 3.0
    assert ranked[0][0] == "s1"


def test_compute_consensus_ranking_hybrid():
    scoring = {
        "rankings": [
            {
                "solution_id": s["solution_id"],
                "solver_label": s["solver_label"],
                "scores": s["scores"],
                "total": sum(s["scores"].values()),
            }
            for s in _sample_scores()
        ]
    }
    result = compute_consensus_ranking(scoring, algorithm="hybrid", k=60)
    assert result["s1"]["rank"] == 1
    assert result["s0"]["rank"] == 2
    assert result["s2"]["rank"] == 3
    assert "rrf_score" in result["s0"]
    assert "borda_score" in result["s0"]


def test_single_solution_edge_case():
    sols = [
        {
            "solution_id": "s0",
            "scores": {
                "correctness": 1,
                "efficiency": 1,
                "maintainability": 1,
                "robustness": 1,
                "security": 1,
            },
        }
    ]
    assert rrf_rank(sols) == [("s0", 1.0)]
    assert borda_rank(sols) == [("s0", 1.0)]
    assert hybrid_rank(sols) == [("s0", 1.0, 1.0, 1.0)]


def test_empty_scoring_returns_empty():
    assert compute_consensus_ranking({}, algorithm="hybrid") == {}
    assert compute_consensus_ranking(None, algorithm="rrf") == {}
