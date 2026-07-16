# PolyGnosis API

> **LatticeAG · Poly series** · Status: shipping (in-tree; extract to `mosesman831/polygnosis-api`)
> **Type:** Public service API
> **Protocol:** PolyGnosis v3 (full boardroom)

## Problem

Single-model answers have no reliability signal. For high-stakes objectives (architecture, security-sensitive code, correctness-critical designs), you need adversarial multi-model consensus — not one completion.

## Relationship to PolyGnosis

[PolyGnosis](https://github.com/mosesman831/PolyGnosis) is the Hermes Agent skill that runs the boardroom via `hermes chat` agent sessions with asymmetric tool allocation.

**This repo** exposes the **same seven-phase protocol** as an HTTP API:

- Model-only solvers (OpenAI-compatible gateway) — no Hermes dependency
- Async jobs (`POST` → poll `GET`) because full runs take minutes
- Formal **RRF + Borda** (hybrid default) consensus ranking — not rule-of-thumb scores

## Solution

```
POST /v1/boardroom
{
  "objective": "Design a production-grade JWT auth middleware in Rust",
  "scoring_algorithm": "hybrid",
  "solver_count": 3
}
→ 202 { "job_id": "...", "poll_url": "/v1/boardroom/..." }

GET /v1/boardroom/{job_id}
→
{
  "status": "completed",
  "result": {
    "final_output": "...",
    "meta_review": "...",
    "scoring_algorithm": "hybrid",
    "consensus_ranking": {
      "s1": {"rank": 1, "avg_rank": 1.0, "rrf_score": 0.081, "borda_score": 8},
      "s0": {"rank": 2, "avg_rank": 2.0, "rrf_score": 0.079, "borda_score": 6}
    },
    "quality_gate": {"verdict": "PASS", ...},
    "trail": [ { "solver": "...", "rank": 1, "solution": "..." }, ... ]
  }
}
```

## Full workflow (must match PolyGnosis v3)

```
0   Orchestrate          → problem statement + dynamic personas
1   Parallel solve       → 3+ heterogeneous models, persona lenses
1.5 Early resolution     → skip critique+scoring on unanimous quorum
2   Critique + Reflexion → adversarial review, revise rounds, failure buffer
3   Formal scoring       → LLM 5-axis scores → RRF / Borda / hybrid
4   Synthesis            → unified solution from ranked elements
5   Quality gate         → reject synthesis regressions
6   Meta-review          → human-readable consensus explanation
```

### Layer-2 consensus (required)

```
RRF(s)   = Σ_axis  1 / (k + rank_axis(s))     # k = 60
Borda(s) = Σ_axis  (n - 1 - rank_axis(s))
Hybrid   = avg(RRF_rank(s), Borda_rank(s))    # default
```

LLM scores are **inputs only**. Final winner is determined by the deterministic algorithm.

## Key design decisions

- **Async by default.** Full boardroom is multi-minute; sync HTTP is the wrong shape.
- **Model-only v1.** No agent sandboxes in this repo. Persona tool classes are prompt constraints. Agent backends (Hermes / Eve) are a future `/v1/boardroom` executor swap, not the default path.
- **Hybrid scoring default.** Most resilient when RRF and Borda disagree.
- **Graceful degradation.** Dead solvers, non-JSON critiques/scores/gates follow PolyGnosis fault-tolerance rules.
- **Artifacts on disk.** Every job writes a run directory (orchestrator, solvers, critiques, scoring.json with `_consensus_ranking`, synthesis, gate, meta-review).

## Non-goals (v1)

- Hermes / Eve agent sessions with live tools
- Sub-second claim verification (that would be a lite product)
- Replacing LexVerdict-style post-tool checks

## Success criteria

- Consensus ranking unit tests match RRF / Borda / hybrid formulas from `POLYGNOSIS_SPEC.md`
- End-to-end job completes against an OpenAI-compatible gateway with configured models
- Response includes `consensus_ranking` with `rrf_score` / `borda_score` under hybrid mode
- Quality gate can reject synthesis and fall back to top individual solution

## References

1. Cormack et al. (2009) — Reciprocal Rank Fusion  
2. de Borda (1781) — Borda Count  
3. Shinn et al. (2023) — Reflexion  
4. PolyGnosis formal spec — https://github.com/mosesman831/PolyGnosis/blob/main/POLYGNOSIS_SPEC.md
