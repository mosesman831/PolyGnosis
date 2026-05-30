---
name: polygnosis
description: "Use when the user needs a verified, multi-model consensus answer for complex, high-stakes tasks. Invoke the PolyGnosis v3 adversarial debate pipeline: 3+ models solve independently with dynamic specializations and asymmetric tool allocation, a critic cross-reviews all solutions, severe bugs are logged to a Reflexion buffer, formal RRF+Borda ranking determines the winner, a Constitutional Quality Gate prevents synthesis regressions. Early Resolution circuit bypasses critique+scoring when solvers reach unanimous consensus. Do NOT use for simple queries or syntax fixes."
version: 3.0.0
author: "Moses / LatticeAG"
license: GPL-3.0
metadata:
  hermes:
    tags: [multi-agent, consensus, peer-review, adversarial, boardroom, reasoning, code-review, rrf, borda, reflexion, quality-gate]
    related_skills: [polybrain]
---

# PolyGnosis (v3 — Enterprise)

Adversarial multi-model consensus protocol for Hermes Agent. When a user asks a complex,
high-stakes question — architectural design, security-critical code, algorithmic
correctness — single-model zero-shot inference is a liability. PolyGnosis:

1. **Dynamically assigns specialized personas** to each solver (e.g., "DBA Consultant",
   "Backend Architect", "Security Auditor") — not generic labels.
2. **Runs parallel solve** with 3+ frontier models, each from their expert perspective.
3. **Adversarial critique** hunts bugs, hallucinations, edge cases; severe findings are
   logged to a **Reflexion corrections buffer** for future run injection.
4. **Formal consensus scoring** via deterministic RRF + Borda Count on top of LLM
   per-axis scores — prevents a single opinionated critic from dominating.
5. **Constitutional Quality Gate** compares synthesis against top individual solution;
   rejects synthesis if it introduces regressions.
6. **Meta-Review** explains the consensus decision.

Built from the PolyBrain orchestration pattern (`polybrain` skill).

## When to Use

- User asks "build a production-grade X" where correctness is critical
- Security-sensitive code (auth, cryptography, input validation)
- Complex algorithm design with edge-case risk
- Architecture decisions that will be expensive to change later
- Any task where a single-model hallucination would be costly
- User explicitly invokes "boardroom" or "adversarial review"

Do NOT use when:
- Simple questions, syntax fixes, or trivial tasks
- Single-model output would be acceptable
- Speed matters more than correctness (full pipeline takes minutes)

## v2 Enterprise Upgrades

| Feature | Description |
|---------|------------|
| **RRF + Borda Count** | Deterministic consensus ranking layer on top of LLM scores. Configurable via `scoring_algorithm` (rrf/borda/hybrid). |
| **Constitutional Quality Gate** | Post-synthesis regression check. If synthesis is worse than the best individual solution, the individual solution wins. |
| **Reflexion Buffer** | CRITICAL/HIGH bugs + hallucinations saved to `.corrections_buffer.json`. Injected into solver prompts on subsequent runs. |
| **Dynamic Personas** | Orchestrator generates domain-appropriate specialist roles instead of generic "Solver-A/B/C". |

## v3 Upgrades

| Feature | Description |
|---------|------------|
| **Early Resolution / Quorum Vote** | After Phase 1, a judge model checks if all solvers reached unanimous consensus. If yes, critique + scoring are bypassed — massive cost savings on simple tasks. Config: `early_resolution_enabled`. |
| **Asymmetric Tool Allocation** | Personas get restricted toolsets: "Security Auditor" → read-only (`web`, `file`), "Developer" → write-capable (`terminal`, `file`, `web`). True specialization at the tool level, not just prompt. Takes effect via `hermes chat -t` flag. |

## Architecture

```
User Objective
  │
  ▼
┌──────────────────┐
│ Orchestrator      │ → Problem statement + success criteria + personas (JSON)
│ (1 model)         │     Personas are domain-specialized: "DBA Consultant",
│                   │     "Backend Architect", "Security Auditor", etc.
└──────┬───────────┘
       │
       ▼
┌──────────────────────────────────────────────┐
│  Phase 1: Parallel Solve (persona-driven)     │
│                                                │
│  ┌─────────────┐ ┌─────────────┐ ┌──────────┐│
│  │DBA Consultant│ │Backend Arch │ │Security  ││
│  │  (Model 1)  │ │  (Model 2)  │ │Auditor(3)││
│  └──────┬──────┘ └──────┬──────┘ └────┬─────┘│
│         │   Solution A   │ Solution C  │       │
│         │          Solution B          │       │
└─────────┼───────────────┼──────────────┼──────┘
          │               │              │
          ▼               ▼              ▼
┌──────────────────────────────────────────────┐
│  Phase 2: Critique + Reflexion                │
│                                                │
│  Critic (per solution):                        │
│    → Hunts bugs, hallucinations, edge cases    │
│    → Scores 0-100                              │
│    → CRITICAL/HIGH findings → Reflexion buffer │
│                                                │
│  Revision round (if enabled):                  │
│    → Solvers fix issues + defend approach      │
└───────┬────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────┐
│  Phase 3: Formal Consensus Scoring             │
│                                                │
│  LLM → per-axis scores (0-10 × 5 axes)        │
│  ↓                                             │
│  Deterministic layer:                          │
│    • Reciprocal Rank Fusion (RRF, k=60)        │
│    • Borda Count (n-1 points for #1)           │
│    • Hybrid: average RRF + Borda ranks         │
│  ↓                                             │
│  Final ranking (algorithmic, not opinionated)  │
└───────┬────────────────────────────────────────┘
        │
        ▼
┌──────────────────┐
│ Synthesizer      │ → Unified enterprise-grade solution
│ (1 model)        │     Extracts strongest elements from ranked solutions
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Quality Gate     │ → Compares synthesis vs top individual solution
│ (1 model)        │     PASS: synthesis is better or equal
│                  │     FAIL: synthesis regressed → output individual solution
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Meta-Reviewer    │ → Explains consensus decision, rejected flaws, quality gate
│ (1 model)        │
└──────┬───────────┘
       │
       ▼
  Final Output
  (Synthesis or top individual + Meta-Review)
```

## Installation

### From the PolyBrain repo

```bash
cd ~/.hermes/skills/research/
cp -r ~/repos/polybrain/PolyGnosis polybrain-boardroom
```

### Configure models

Edit `~/.hermes/skills/research/polybrain-boardroom/config.yaml`:

```yaml
models:
  orchestrator: "claude-sonnet-4"       # Builds problem statement + personas
  solver_1: "llama-4-maverick"          # Diverse model family
  solver_2: "qwen3-235b"                # Different architecture
  solver_3: "mistral-large"             # Different reasoning style
  critic: "claude-sonnet-4"             # Strong adversarial reviewer
  synthesizer: "claude-sonnet-4"        # Builds final output
  meta_reviewer: "claude-sonnet-4"      # Explains consensus
  fallback: "claude-haiku-4-5"          # Fast fallback

settings:
  solver_count: 3
  scoring_algorithm: "hybrid"   # rrf | borda | hybrid
  rrf_k: 60                     # RRF constant (standard: 60)
  quality_gate_enabled: true    # Reject synthesis that regresses
  max_debate_rounds: 2
```

Validate:

```bash
python ~/.hermes/skills/research/polybrain-boardroom/scripts/validate_config.py
```

## Usage

```bash
python ~/.hermes/skills/research/polybrain-boardroom/scripts/boardroom_pipeline.py
# Objective: <paste your problem>
```

## Reflexion Buffer

Severe findings (CRITICAL/HIGH bugs, hallucinations) from the critique phase are
persisted to `.corrections_buffer.json` in the skill directory. On subsequent
PolyGnosis runs, the buffer is injected into solver system prompts so models
learn from past failures within a project session.

To reset the buffer:

```bash
rm ~/.hermes/skills/research/polybrain-boardroom/.corrections_buffer.json
```

## Scoring Algorithm

| Algorithm | How it works | Best for |
|-----------|-------------|----------|
| `rrf` | Sum of 1/(k+rank) per axis. Standard k=60. High scores win. | When score magnitudes are rough estimates |
| `borda` | Points = n-1 for #1, 0 for last. Per axis, then summed. | When relative ordering matters more than raw scores |
| `hybrid` | Both RRF and Borda, then average the normalized ranks. | **Default.** Most robust against any single bias. |

## Constitutional Quality Gate

After synthesis, a gate model compares the synthesized output against the
top-ranked individual solution:

- **PASS**: Synthesis is equal or better → output synthesis
- **FAIL**: Synthesis introduced regressions → output top individual solution instead
- Quality gate verdict is documented in the Meta-Review

## Artifacts

Per-run outputs saved to `settings.artifacts_dir/<run-id>/`:

```
boardroom/<run-id>/
├── orchestrator_raw.txt           # Raw orchestrator output
├── orchestrator.json              # Problem statement + personas
├── solver_A_<persona>_initial.md  # Solver-A initial solution
├── solver_B_<persona>_initial.md  # Solver-B initial solution
├── solver_C_<persona>_initial.md  # Solver-C initial solution
├── critique_A_r1.json             # Critic review (round 1)
├── critique_B_r1.json
├── critique_C_r1.json
├── solver_A_r2.md                 # Revised (round 2, if enabled)
├── scoring_raw.json               # LLM per-axis scores
├── scoring.json                   # RRF+Borda consensus ranking merged
├── synthesis_raw.md               # Synthesizer output
├── quality_gate.json              # Quality gate verdict + reasoning
├── final_output.md                # Final output (synthesis or individual)
└── meta_review.md                 # Why this won
```

Session-local: `PolyGnosis/.corrections_buffer.json` (Reflexion buffer)

## Common Pitfalls

1. **No models configured** — Run `validate_config.py` first.
2. **All solvers timeout** — Increase `solver_timeout_sec`. Complex code gen can take 5+ minutes.
3. **Quality gate rejects synthesis** — Normal. The system protects against regressions. Check `quality_gate.json` for what was rejected.
4. **Reflexion buffer grows large** — Delete `.corrections_buffer.json` between projects. Buffer is session/project-local.
5. **Single model for all roles** — Reduces adversarial diversity. Use distinct model families.
6. **Too many debate rounds** — Each round adds 2-5 minutes. `max_debate_rounds: 2` is the sweet spot.
7. **gpt-5-mini hangs in subprocess** — Known Hermes issue. Avoid as solver/critic model.

## Relationship to PolyBrain

PolyGnosis was built from the PolyBrain orchestration pattern (`hermes chat`
subprocess + `config.yaml` routing) and extends it with adversarial consensus
semantics. It is NOT a replacement — PolyBrain handles research and synthesis
pipelines; PolyGnosis handles correctness-critical consensus where multiple
independent models must converge on a verified answer through formal debate.
