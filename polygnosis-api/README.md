# PolyGnosis API

> **LatticeAG · Poly series** · Adversarial multi-model consensus as a public HTTP service

Full [PolyGnosis](https://github.com/mosesman831/PolyGnosis) v3 boardroom over HTTP — orchestrate, parallel solve, early resolution, adversarial critique, **RRF + Borda** formal scoring, synthesis, constitutional quality gate, meta-review.

Self-contained package intended as its own repo (`mosesman831/polygnosis-api`). Solvers are **model completions** (OpenAI-compatible / AI Gateway), not Hermes agent sessions.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set POLYGNOSIS_API_KEY
# edit config.yaml model IDs
uvicorn polygnosis_api.main:app --app-dir src --host 0.0.0.0 --port 8080
```

```bash
# Start a boardroom (async — full pipeline takes minutes)
curl -X POST http://localhost:8080/v1/boardroom \
  -H 'content-type: application/json' \
  -d '{"objective":"Design a production-grade JWT auth middleware in Rust"}'

# Poll
curl http://localhost:8080/v1/boardroom/<job_id>
```

## Workflow

```
POST /v1/boardroom
  ↓
0  Orchestrate → problem statement + dynamic personas
1  Parallel solve (3+ heterogeneous models)
1.5 Early resolution (skip critique+scoring if unanimous)
2  Adversarial critique + Reflexion buffer (+ optional revise rounds)
3  LLM per-axis scores → deterministic RRF / Borda / hybrid ranking
4  Meta-synthesis
5  Constitutional quality gate
6  Meta-review
  ↓
GET /v1/boardroom/{job_id} → final_output + consensus_ranking + trail
```

## Consensus scoring

Layer 1: LLM scores each solution on correctness, efficiency, maintainability, robustness, security (0–10).

Layer 2 (deterministic):

| Algorithm | Formula |
|-----------|---------|
| **RRF** | `Σ 1/(k + rank_axis)` — default `k=60` |
| **Borda** | `Σ (n - 1 - rank_axis)` |
| **Hybrid** (default) | average of RRF and Borda rank positions |

Request override: `"scoring_algorithm": "rrf" | "borda" | "hybrid"`.

## API surface

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness |
| `POST` | `/v1/boardroom` | Start consensus job (`202`) |
| `GET` | `/v1/boardroom/{job_id}` | Poll status / result |

## Config

- `config.yaml` — per-role models, timeouts, scoring algorithm, debate rounds
- `.env` — `POLYGNOSIS_API_BASE_URL`, `POLYGNOSIS_API_KEY`

Works with any OpenAI-compatible chat completions endpoint (Vercel AI Gateway, OpenAI, OpenRouter, LexGateway, etc.).

## Relationship to PolyGnosis (Hermes skill)

| | Hermes PolyGnosis | PolyGnosis API |
|--|-------------------|----------------|
| Runtime | `hermes chat` agent sessions + tools | Model completions only |
| Interface | Skill / CLI pipeline | HTTP JSON |
| Consensus | RRF + Borda hybrid | Same algorithms |
| Latency | 10–20+ minutes | Same order (async jobs) |

Agent-backed hosted boardrooms (Eve / Hermes) are a future tier — this repo ships the full protocol on models first.

## License

GPL-3.0 — same as [PolyGnosis](https://github.com/mosesman831/PolyGnosis).
