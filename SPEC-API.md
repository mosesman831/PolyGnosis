# SPEC-API: PolyGnosis as a Public Service API

> **Status:** Implemented in-tree (`polygnosis-api/`) — extract to a separate public repo when ready  
> **Type:** Feature / product split  
> **Code:** [`polygnosis-api/`](./polygnosis-api/)

## Problem

When you ask a single model a question, you get one answer with no reliability signal. For high-stakes objectives, a single model call is not enough.

## Decision

Ship **PolyGnosis API** as a standalone FastAPI service (own package, own README/SPEC) — not a lite claim-verify endpoint, and not a Hermes skill wrap.

The public API runs the **full PolyGnosis v3 boardroom**:

```
0 Orchestrate → 1 Parallel solve → 1.5 Early resolution
→ 2 Critique + Reflexion → 3 RRF/Borda/hybrid scoring
→ 4 Synthesis → 5 Quality gate → 6 Meta-review
```

Formal Layer-2 consensus is required:

```
RRF(s)   = Σ 1/(k + rank_a(s))
Borda(s) = Σ (n - 1 - rank_a(s))
Hybrid   = avg(RRF_rank, Borda_rank)   # default
```

## Separate repo

Target public repo: `mosesman831/polygnosis-api`.

Until that repo is created, the complete service lives in [`polygnosis-api/`](./polygnosis-api/) in this repository (GPL-3.0, installable, tested). Extract by copying that directory into a new git remote.

## Relationship to this repo

| | Hermes skill (this root) | `polygnosis-api/` |
|--|--------------------------|-------------------|
| Runtime | `hermes chat` agent sessions + asymmetric tools | Model completions (OpenAI-compatible gateway) |
| Interface | Skill / CLI | `POST /v1/boardroom` + poll |
| Consensus | RRF + Borda hybrid | Same algorithms (ported + unit-tested) |
| State | Reflexion buffer + artifacts | Same pattern |

They share the protocol. They do **not** share the executor.

## API shape

```
POST /v1/boardroom
{
  "objective": "Design a production-grade JWT auth middleware in Rust",
  "scoring_algorithm": "hybrid"
}
→ 202 { "job_id": "...", "poll_url": "/v1/boardroom/..." }

GET /v1/boardroom/{job_id}
→ status + final_output + consensus_ranking + trail + quality_gate + meta_review
```

Async by design — full runs take minutes.

## Explicit non-goals for v1 API

- Hermes / Eve agent sessions as the default path (future optional executor)
- Sub-second claim verification (different product)
- Replacing LexVerdict post-tool checks

## Success criteria

- Installable FastAPI service under `polygnosis-api/`
- Unit tests lock RRF / Borda / hybrid formulas to `POLYGNOSIS_SPEC.md`
- Hybrid responses expose `rrf_score` + `borda_score` in `consensus_ranking`
- Quality gate can reject synthesis and fall back to the top individual solution
