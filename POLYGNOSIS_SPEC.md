# PolyGnosis: A Formal Specification

## Adversarial Multi-Model Consensus Protocol for Autonomous Code Generation

**Version:** 3.0.0  
**Authors:** Moses / LatticeAG  
**License:** GPL-3.0  
**Repository:** https://github.com/mosesman831/PolyGnosis

---

## Abstract

PolyGnosis is an adversarial multi-model consensus protocol designed to eliminate
single-model hallucination risk in autonomous code generation tasks. The system
routes a user objective through a seven-phase pipeline: (0) orchestration and
dynamic persona assignment, (1) parallel independent solving across three or more
heterogeneous large language models, (1.5) early resolution via quorum voting,
(2) adversarial cross-critique with Reflexion-based failure logging, (3) formal
consensus scoring via Reciprocal Rank Fusion (RRF) and Borda Count algorithms,
(4) meta-synthesis of the strongest solution elements, (5) a Constitutional
Quality Gate for regression detection, and (6) a meta-review explaining the
consensus verdict.

PolyGnosis is built from the orchestration pattern pioneered by PolyBrain
(config-driven model routing, `hermes chat` subprocess execution,
`ThreadPoolExecutor` parallelism) and extends it with adversarial consensus,
formal scoring, quality gates, asymmetric tool allocation, and Reflexion-based
self-improvement.

---

## 1. System Architecture

### 1.1 Execution Model

PolyGnosis operates as a single Python process (`boardroom_pipeline.py`) that
spawns Hermes Agent subprocesses via `hermes chat -q`. Each subprocess is a
stateless, single-turn invocation of a specific LLM with a specific role prompt.
No persistent agent state is maintained across subprocess boundaries - all state
transfer occurs through the orchestrator process via filesystem artifacts and
in-memory data structures.

### 1.2 Component Topology

```
┌─────────────────────────────────────────────────────────────┐
│                    PolyGnosis Orchestrator                   │
│                    (boardroom_pipeline.py)                   │
├─────────────────────────────────────────────────────────────┤
│  Phase 0: build_orchestrator_prompt() -> hermes chat         │
│  Phase 1: build_solver_prompt() -> hermes chat × 3 (parallel)│
│  Phase 1.5: EARLY_RESOLUTION_PROMPT -> hermes chat (optional) │
│  Phase 2: build_critique_prompt() -> hermes chat × 3 (par)   │
│  Phase 3: build_scoring_prompt() -> hermes chat + RRF/Borda  │
│  Phase 4: build_synthesis_prompt() -> hermes chat            │
│  Phase 5: build_quality_gate_prompt() -> hermes chat         │
│  Phase 6: build_meta_review_prompt() -> hermes chat          │
├─────────────────────────────────────────────────────────────┤
│  Persistent State:                                           │
│    config.yaml              - model routing configuration    │
│    .corrections_buffer.json - Reflexion failure log          │
│    artifacts/<run-id>/      - per-run output directory       │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 Concurrency Model

Phases 1 and 2 execute model invocations in parallel via
`concurrent.futures.ThreadPoolExecutor`. The maximum worker count is governed by
`solver_count` (default: 3, range: 2-5). Each worker thread blocks on
`subprocess.run()` for the configured timeout (`solver_timeout_sec`, default:
600s). Phases 3-6 execute sequentially because each depends on the complete
output of the prior phase.

---

## 2. Phase 0: Orchestration and Persona Assignment

### 2.1 Purpose

Transform a free-form user objective into a structured problem statement with
measurable success criteria and dynamically generated expert personas.

### 2.2 Algorithm

1. The orchestrator model receives `build_orchestrator_prompt(objective)`.
2. The model returns JSON conforming to the schema:
   ```json
   {
     "problem_statement": "<self-contained problem description>",
     "success_criteria": ["<criterion>", ...],
     "domain": "<e.g. distributed systems>",
     "personas": ["<Role - title + specialization>", ...]
   }
   ```
3. Personas are domain-inferred by the LLM. Examples:
   - Database optimization -> `["DBA Consultant", "Backend Architect", "Security Auditor"]`
   - Compiler design -> `["Parser Designer", "Optimization Engineer", "Type System Expert"]`
4. If the orchestrator returns no personas, a fallback generates `Senior <domain> Expert A/B/C`.

### 2.3 JSON Extraction

Models frequently emit prose, markdown fences, or commentary surrounding JSON.
`extract_json()` applies a two-stage extraction:
1. Regex match for ` ```json ... ``` ` or ` ``` ... ``` ` code fences.
2. Fallback: find the outermost `{` ... `}` pair via `str.find()` / `str.rfind()`.

### 2.4 Fault Tolerance

If the orchestrator returns non-JSON after both extraction strategies, the raw
user objective is used as `problem_statement` and default success criteria
(`["Correctness", "Completeness", "Robustness"]`) are applied.

---

## 3. Phase 1: Parallel Solving with Asymmetric Tool Allocation

### 3.1 Purpose

Generate three or more independent solutions to the problem, each from a
distinct expert persona with persona-appropriate tool restrictions.

### 3.2 Persona-Driven Prompt Construction

Each solver receives `build_solver_prompt(problem_statement, persona_label, reflexion_context, toolsets, tool_class)`:

```
You are the {persona_label} in a multi-model consensus boardroom.

You are solving this problem from your unique expert perspective...
Be rigorous. Show your reasoning. Anticipate criticism.

TOOL ACCESS: You have been assigned {tool_class} tools. ({toolsets}).
Operate within these constraints...

─── LESSONS FROM PRIOR BOARDROOM SESSIONS (Reflexion Buffer) ───
[injected only if buffer is non-empty]
─── END REFLEXION BUFFER ───

PROBLEM:
{problem_statement}
```

### 3.3 Asymmetric Tool Allocation Taxonomy

Personas are classified by regex matching against `PERSONA_TOOLSET_MAP`:

| Classification | Pattern | Toolsets | Rationale |
|---------------|---------|----------|-----------|
| Read-only (audit/review) | `security auditor\|penetration tester\|qa engineer\|compliance` | `web, file` | Auditors inspect, never modify |
| Read-only (review/inspect) | `code reviewer\|inspector\|verifier\|validator\|critic\|auditor\|reviewer` | `web, file` | Reviewers read code, don't write it |
| Write-capable (data/storage) | `data engineer\|data architect\|dba\|database engineer\|storage engineer\|storage architect` | `terminal, file, web` | Data specialists need schema creation |
| Write-capable (infrastructure) | `devops engineer\|platform engineer\|sre\|cloud architect\|cloud engineer\|infrastructure engineer\|infrastructure architect` | `terminal, file, web` | Infra roles need deployment tooling |
| Write-capable (full-stack) | `fullstack\|full.stack\|full stack\|backend developer\|frontend developer\|backend engineer\|frontend engineer` | `terminal, file, web` | Full-stack developers need full access |
| Write-capable (architect/design) | `solutions architect\|system designer\|systems architect` | `terminal, file, web` | Architects design and scaffold |
| Write-capable (architect/design) - generic | `architect\|designer` | `terminal, file, web` | Catch-all for architect/designer titles |
| Write-capable (developer) - generic | `developer\|engineer\|programmer\|builder\|implementer\|coder` | `terminal, file, web` | Catch-all for developer titles |
| Read-only (default) | `""` (empty pattern matches all) | `web, file` | Conservative default: read-only |

**Ordering constraint:** More specific compound patterns (e.g., `data engineer`)
must appear before generic patterns (e.g., `engineer`) to prevent greedy
matching. The map is ordered from most-specific to least-specific.

### 3.4 Toolset Enforcement

Toolsets are passed to `hermes chat` via the `-t` flag:

```
hermes chat -q <prompt> -m <model> -t web,file --source polygnosis
```

This restricts the subprocess agent to only the named toolsets. Read-only
personas cannot execute terminal commands or write files.

### 3.5 Parallel Execution and Fault Tolerance

```python
with ThreadPoolExecutor(max_workers=solver_count) as ex:
    futures = {ex.submit(execute_solver, i): i for i in range(solver_count)}
    for f in as_completed(futures):
        idx, result, error = f.result()
```

Each solver runs independently. Failures are captured as `(idx, error_string)`
tuples in the `dead_solvers` list. The pipeline proceeds if
`len(solver_results) >= min_solvers_for_quorum` (default: 2).

---

## 4. Phase 1.5: Early Resolution via Quorum Voting

### 4.1 Purpose

Detect unanimous consensus among solvers to bypass the expensive critique and
scoring phases. This is a cost-optimization circuit, not a correctness circuit.

### 4.2 Quorum Judge Prompt

A dedicated judge model (reuses the orchestrator model) evaluates truncated
solutions (first 3000 characters each) against the problem statement:

```
SYSTEM: You are the Boardroom Quorum Judge. Evaluate whether the following
independent solutions reached UNANIMOUS CONSENSUS on the core approach.

Consensus means: all solvers proposed fundamentally the SAME architecture,
algorithm, or solution pattern...

Non-consensus means: at least one solver took a meaningfully different approach...

Return JSON ONLY. Schema:
{
  "unanimous": true or false,
  "confidence": <float 0.0-1.0>,
  "consensus_approach": "...",
  "divergences": ["..."]
}
```

### 4.3 Activation Criteria

Early resolution triggers only when ALL of:
1. `early_resolution_enabled` is `true` in config.
2. `len(solver_results) >= 3` (meaningful quorum requires 3+ voters).
3. `verdict["unanimous"] == true` AND `verdict["confidence"] >= 0.7`.

### 4.4 Early Exit Path

When activated, the pipeline:
1. Skips `phase_critique()` and `phase_scoring()` entirely.
2. Constructs a synthetic `consensus_ranking` where all solvers share rank 1.
3. Constructs synthetic `scorer_solutions` with `critic_score: 100`, `critic_grade: "PASS"`, and a note indicating early resolution.
4. Proceeds directly to `phase_synthesis()`.

---

## 5. Phase 2: Adversarial Critique and Reflexion

### 5.1 Purpose

Subject every solver output to a hostile peer review that aggressively hunts
for bugs, hallucinations, security flaws, and architectural problems.

### 5.2 Critique Schema

The critic model returns JSON:

```json
{
  "solution_id": "s0",
  "solver": "Security Auditor",
  "overall_grade": "PASS" | "FAIL" | "PASS_WITH_ISSUES",
  "critical_bugs": [{"description": "...", "severity": "CRITICAL|HIGH|MEDIUM|LOW"}],
  "hallucinations_found": [{"claimed": "...", "reality": "..."}],
  "missing_edge_cases": ["..."],
  "strengths": ["..."],
  "weaknesses": ["..."],
  "score": <integer 0-100>,
  "improvement_suggestions": ["..."]
}
```

### 5.3 Reflexion Buffer Mechanics

The Reflexion buffer implements the Reflexion pattern (Shinn et al., 2023) -
persisting failure episodes for future retrieval. The buffer is a JSON file at
`.corrections_buffer.json` with structure:

```json
{
  "version": 2,
  "corrections": [
    {
      "source": "boardroom_critique_r1",
      "solver": "Backend Architect",
      "severity": "CRITICAL",
      "description": "Race condition in connection pool initialization",
      "timestamp": "2026-05-30T14:22:00"
    }
  ],
  "updated": "2026-05-30T14:22:00"
}
```

**Ingestion rules:**
- `severity == "CRITICAL"` or `severity == "HIGH"` -> saved.
- `severity == "MEDIUM"` or `severity == "LOW"` -> discarded (noise floor).
- All hallucinations (any severity) -> saved as `severity: "HALLUCINATION"`.

**Deduplication:** Entries are deduplicated by the first 200 characters of
`description.strip().lower()`.

**Injection:** On subsequent runs, `build_reflexion_injection()` reads the
buffer, takes the most recent 10 entries, and injects them into solver prompts
between marker lines:

```
─── LESSONS FROM PRIOR BOARDROOM SESSIONS (Reflexion Buffer) ───
The following failures were caught in previous consensus runs.
DO NOT repeat these mistakes:
- [CRITICAL] Race condition in connection pool initialization
- [HALLUCINATION] Claimed: async fn send() from reqwest - Reality: reqwest has no async send()
─── END REFLEXION BUFFER ───
```

### 5.4 Debate Rounds

If `max_debate_rounds >= 2`, after the initial critique phase each solver
receives `build_revision_prompt()` containing their original solution and the
critic's JSON feedback. The solver must fix valid criticisms and rebut incorrect
ones. Revision rounds execute in parallel.

At `max_debate_rounds: 2`, the flow is:
1. Round 1: Critique all solutions (parallel)
2. Round 1 revision: Solvers fix issues (parallel)
3. Round 2: Critique revised solutions (parallel) - final critiques used for scoring.

---

## 6. Phase 3: Formal Consensus Scoring

### 6.1 Two-Layer Scoring Architecture

The scoring phase is a two-layer system to prevent any single opinionated model
from dominating the consensus:

**Layer 1 - LLM Scoring:** A scorer model evaluates each solution on five axes
(0-10 each):

| Axis | Definition |
|------|-----------|
| Correctness | Does it solve the problem completely and correctly? |
| Efficiency | Optimal algorithms, resource usage, complexity analysis |
| Maintainability | Code clarity, abstractions, documentation |
| Robustness | Error handling, edge cases, input validation |
| Security | Vulnerabilities, secure defaults, defense in depth |

**Layer 2 - Deterministic Ranking:** The per-axis scores are passed to a
deterministic algorithm. The algorithm is configurable.

### 6.2 Reciprocal Rank Fusion (RRF)

RRF is an unsupervised rank aggregation method from information retrieval
(Cormack et al., 2009). For each scoring axis, solutions are ranked (1 = best).
The RRF score for solution `s` is:

```
RRF(s) = Σ_{a ∈ axes} 1 / (k + rank_a(s))
```

where `k = 60` (standard BM25-derived constant). Higher RRF scores are better.
Solutions are sorted descending by RRF score.

**Implementation:**
```python
def rrf_rank(solutions_scores, k=60):
    rrf_scores = defaultdict(float)
    for axis in SCORING_AXES:
        ranked = sorted(solutions_scores, key=lambda s: s["scores"][axis], reverse=True)
        for rank, sol in enumerate(ranked, start=1):
            rrf_scores[sol["solution_id"]] += 1.0 / (k + rank)
    return sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
```

### 6.3 Borda Count

Borda Count (de Borda, 1781) assigns points per axis: the highest-scoring
solution gets `n-1` points, second gets `n-2`, ..., last gets `0`. Points are
summed across all five axes. Higher totals are better.

```
Borda(s) = Σ_{a ∈ axes} (n - 1 - rank_a(s))
```

**Implementation:**
```python
def borda_rank(solutions_scores):
    borda_totals = defaultdict(float)
    for axis in SCORING_AXES:
        ranked = sorted(solutions_scores, key=lambda s: s["scores"][axis], reverse=True)
        for idx, sol in enumerate(ranked):
            borda_totals[sol["solution_id"]] += (n - 1 - idx)
    return sorted(borda_totals.items(), key=lambda x: x[1], reverse=True)
```

### 6.4 Hybrid Ranking

The hybrid algorithm runs both RRF and Borda, converts each to rank positions
(1 = best), and averages the normalized ranks:

```
HybridRank(s) = (RRFRank(s) + BordaRank(s)) / 2
```

Solutions are sorted ascending by `HybridRank` (lower = better). Ties share the
same rank position.

**Implementation:**
```python
def hybrid_rank(solutions_scores, k=60):
    rrf = dict(rrf_rank(solutions_scores, k=k))
    borda = dict(borda_rank(solutions_scores))
    rrf_vals = sorted(rrf.values(), reverse=True)
    borda_vals = sorted(borda.values(), reverse=True)

    def rank_from_scores(val, sorted_vals):
        return sorted_vals.index(val) + 1

    results = []
    for s in solutions_scores:
        sid = s["solution_id"]
        r = rank_from_scores(rrf.get(sid, 0.0), rrf_vals)
        b = rank_from_scores(borda.get(sid, 0.0), borda_vals)
        avg = (r + b) / 2.0
        results.append((sid, avg, rrf.get(sid, 0.0), borda.get(sid, 0.0)))
    return sorted(results, key=lambda x: x[1])
```

### 6.5 Algorithm Selection Rationale

| Algorithm | Strengths | Weaknesses |
|-----------|----------|------------|
| RRF (k=60) | Robust to outlier scores; standard in IR literature | Does not use score magnitudes, only ranks |
| Borda Count | Uses full rank distribution; simple to verify | Sensitive to irrelevant alternatives |
| Hybrid | Combines strengths of both; most robust to any single bias | Slightly more compute (both algorithms run) |

The hybrid is the default because it is most resilient: if RRF and Borda disagree,
the average dampens the disagreement. If they agree, the hybrid reinforces
confidence.

---

## 7. Phase 4: Meta-Synthesis

### 7.1 Purpose

Construct a single unified solution from the strongest elements of all ranked
solutions.

### 7.2 Synthesis Prompt

The synthesizer receives:
- The problem statement
- The success criteria
- The formal consensus ranking (e.g., "Rank 1: Security Auditor")
- All solution texts

The prompt instructs the synthesizer to:
1. Extract the strongest elements from each solution.
2. Fix any remaining bugs - do not propagate known issues from critique.
3. Produce a self-contained, production-ready output.
4. Never reference "solution X" - the output must stand alone.

---

## 8. Phase 5: Constitutional Quality Gate

### 8.1 Purpose

Prevent the synthesis phase from introducing regressions.

### 8.2 Gate Protocol

1. Identify the top-ranked individual solution from the consensus ranking.
2. Submit both the synthesis and the top individual solution to a gate model
   with `build_quality_gate_prompt()`.
3. The gate model returns JSON:
   ```json
   {
     "verdict": "PASS" | "FAIL",
     "reasoning": "...",
     "regressions_found": ["..."],
     "improvements_found": ["..."]
   }
   ```

### 8.3 Verdict Handling

- **PASS:** The synthesis is delivered as the final output.
- **FAIL:** The top individual solution replaces the synthesis. The quality gate
  result is included in the meta-review so the user knows a regression was
  detected and handled.

### 8.4 Fault Tolerance

If the gate model returns non-JSON, the default verdict is `PASS` - erring on
the side of delivering the synthesis rather than blocking. This is logged in
`quality_gate.json`.

---

## 9. Phase 6: Meta-Review

### 9.1 Purpose

Provide a human-readable explanation of the consensus decision.

### 9.2 Meta-Review Content

The meta-review covers:
1. Why the final output was chosen - which solutions contributed most.
2. Specific flaws rejected from each solver's initial draft.
3. How the critique process improved the final output.
4. Whether the quality gate passed and what it found.
5. Any remaining risks or limitations.

---

## 10. Configuration Contract

### 10.1 Required Fields

All fields in `config.yaml` are validated by `validate_config.py` before
pipeline execution. The contract:

```yaml
models:                           # ALL 8 keys must have non-empty values
  orchestrator: <model-alias>
  solver_1: <model-alias>
  solver_2: <model-alias>
  solver_3: <model-alias>
  critic: <model-alias>
  synthesizer: <model-alias>
  meta_reviewer: <model-alias>
  fallback: <model-alias>

settings:                         # ALL 15 keys must be present
  solver_count: <2-5>
  solver_timeout_sec: <int>
  critic_timeout_sec: <int>
  synthesizer_timeout_sec: <int>
  meta_reviewer_timeout_sec: <int>
  orchestrator_timeout_sec: <int>
  scoring_algorithm: "rrf" | "borda" | "hybrid"
  rrf_k: <positive int, typically 60>
  max_debate_rounds: <1-5>
  min_solvers_for_quorum: <1 to solver_count>
  quality_gate_enabled: <bool>
  early_resolution_enabled: <bool>
  artifacts_dir: <path>
```

### 10.2 Provider Overrides

Optional per-role provider overrides:

```yaml
providers:
  orchestrator: ""
  solver_1: ""
  solver_2: ""
  solver_3: ""
  critic: ""
  synthesizer: ""
  meta_reviewer: ""
  fallback: ""
```

Empty values use the Hermes Agent default provider. The `hermes chat --provider`
flag is only appended when the value is non-empty.

---

## 11. Fault Tolerance and Graceful Degradation

### 11.1 Solver Failure

If a solver times out or returns empty output, it is logged to `dead_solvers`
and excluded from all subsequent phases. The pipeline proceeds if
`len(alive_solvers) >= min_solvers_for_quorum`.

### 11.2 Critic Failure

If the critic fails for a specific solution, that solution proceeds to scoring
with a default critique (`score: 50`, `overall_grade: "PASS_WITH_ISSUES"`).
This prevents a single critic failure from blocking the entire pipeline.

### 11.3 Scorer Failure

If the scorer model returns non-JSON, the raw text is wrapped in
`{"raw_text": "..."}`. The consensus ranking will be empty, and the synthesis
phase will proceed without formal rankings - drawing from all solutions equally.

### 11.4 Quality Gate Failure

If the gate model returns non-JSON, the default verdict is `PASS` - the
synthesis is delivered. This is the fail-safe: better to deliver a potentially
imperfect synthesis than to block delivery entirely.

### 11.5 Early Resolution Judge Failure

If the quorum judge returns non-JSON, the default is `unanimous: false` - the
pipeline proceeds to full critique. This is the conservative choice: when in
doubt, run the full adversarial protocol.

---

## 12. Artifact Schema

Every run produces a timestamped directory under `artifacts_dir`:

```
polygnosis/<YYYYMMDD_HHMMSS>/
├── orchestrator_raw.txt
├── orchestrator.json
├── solver_A_<persona>_initial.md
├── solver_B_<persona>_initial.md
├── solver_C_<persona>_initial.md
├── early_resolution_raw.txt       # Only if Phase 1.5 ran
├── early_resolution.json          # Only if Phase 1.5 ran
├── critique_A_r1.json
├── critique_B_r1.json
├── critique_C_r1.json
├── solver_A_r2.md                 # Only if debate_rounds >= 2
├── scoring_raw.json
├── scoring.json                   # Includes _consensus_ranking
├── synthesis_raw.md
├── quality_gate.json
├── final_output.md
└── meta_review.md
```

Session-local state: `.corrections_buffer.json` (in the skill directory, not
per-run).

---

## 13. References

1. Cormack, G. V., Clarke, C. L. A., & Buettcher, S. (2009). Reciprocal Rank
   Fusion outperforms Condorcet and individual rank learning methods. *SIGIR '09*.
2. de Borda, J. C. (1781). Mémoire sur les élections au scrutin. *Histoire de
   l'Académie Royale des Sciences*.
3. Shinn, N., Cassano, F., Gopinath, A., Narasimhan, K., & Yao, S. (2023).
   Reflexion: Language Agents with Verbal Reinforcement Learning. *NeurIPS 2023*.
4. PolyBrain - Multi-model orchestration for Hermes Agent.
   https://github.com/mosesman831/PolyBrain
