# SPEC-API: PolyGnosis as a Public Service API

> **Status:** Proposal
> **Type:** Feature spec

## Problem

When you ask a single model a question, you get one answer with no reliability signal. Is it right? How confident? Where did it get that from? For high-stakes queries, a single model call is not enough.

## Relationship to PolyGnosis

PolyGnosis already runs adversarial multi-model consensus as a Hermes Agent skill. This spec wraps the same workflow as a public HTTP API — no Hermes dependency, accessible from anything with curl.

## Solution

```
POST /v1/verify
{
  "claim": "Rust's borrow checker prevents all memory safety issues",
  "context": "For a blog post about Rust safety guarantees",
  "mode": "quick"         // "quick" (fast models) or "deep" (frontier models)
}
→
{
  "verdict": "pass",
  "confidence": 0.85,
  "reasoning": "3/3 solvers agree. 1 critique noted safe code exceptions.",
  "trail": [
    {"solver": "Security Auditor",    "response": "...", "score": 0.8},
    {"solver": "Systems Engineer",    "response": "...", "score": 0.9},
    {"solver": "PL Expert",           "response": "...", "score": 0.85}
  ]
}
```

## Workflow

```
POST /v1/verify
  ↓
Solver A (persona 1) → independent answer
Solver B (persona 2) → independent answer
Solver C (persona 3) → independent answer
  ↓ (results shared)
Each solver critiques others' answers
  ↓
Formal scoring (1-5: accuracy, completeness, citations)
  ↓
Synthesis → verdict + confidence + critique trail
  ↓
Return structured response
```

## Key Design Decisions

- **Cost/accuracy slider.** `mode: "quick"` = 3 fast models (e.g., Llama 8B via LexRapid). `mode: "deep"` = 3 frontier models (LexGateway).
- **Cache.** Identical claim + context → cached verdict (TTL: 24h). Keyed by embedding similarity.
- **Strict mode.** `"strict": true` requires every solver to cite sources. Returns `"insufficient evidence"` instead of guessing.
- **Rate limits.** Free: 10/day. Pro: 1000/day. Enterprise: unlimited + SLA.

## Relationship to LexVerdict

| Feature | LexVerdict | PolyGnosis API |
|---------|-----------|----------------|
| Input | Tool call + goal + result | Claim + context |
| Target | Post-execution tool verification | Claim verification & debate |
| Models | 1 fast model | 3 models + critique + scoring |
| Output | pass/steer | verdict + confidence + trail |
| Latency | <100ms | 3-30s |

They're complementary. LexVerdict for fast tool-result checks. PolyGnosis API for high-stakes claim verification.

## Implementation Notes

- Deploy as a CF Worker or FastAPI service (worker fits better with LexGateway routing)
- Solvers call LexGateway under the hood (routes to appropriate model based on mode)
- Critique and scoring phases use the solver outputs as context — no additional model calls needed
- Formal scoring is rule-based (not model-based): 1-5 scale, weighted by citation quality and specificity

## Success Criteria

- 3-model consensus achieves >90% accuracy on known-fact test set (MMLU subset)
- Zero hallucinated citations in strict mode
- Response time: <10s for quick, <30s for deep
