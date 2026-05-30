#!/usr/bin/env python3
"""
PolyGnosis — Multi-model adversarial consensus protocol.

Architecture (v3 — Enterprise):
  0. Orchestrate: Build problem statement + dynamically assign specialized personas.
  1. Parallel Solve: Route to 3+ distinct models with persona-driven system prompts.
  2. Cross-Critique + Reflexion: Adversarial review hunts bugs; severe findings
     are logged to a session-local corrections buffer for future run injection.
  3. Formal Consensus Scoring: LLM produces per-axis scores → deterministic
     RRF + Borda Count ranking (prevents critic domination).
  4. Meta-Synthesis: Build unified solution from strongest elements.
  5. Constitutional Quality Gate: Compare synthesis vs top individual solution;
     reject synthesis if it introduces regressions.
  6. Meta-Review: Explain the decision.

Usage:
  python polygnosis/scripts/validate_config.py
  python polygnosis/scripts/boardroom_pipeline.py
  echo "Build a production-grade auth system in Rust" | python polygnosis/scripts/boardroom_pipeline.py
"""

import json
import subprocess
import sys
import time
import re
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import yaml

PROJECT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_DIR / "config.yaml"
CORRECTIONS_BUFFER_PATH = PROJECT_DIR / ".corrections_buffer.json"

# Scoring axes used across the pipeline
SCORING_AXES = ["correctness", "efficiency", "maintainability", "robustness", "security"]


# ═══════════════════════════════════════════════════════════════════════════════
# ── Utilities ─────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def extract_json(text: str) -> str:
    """Salvage JSON from text that may contain markdown fences or prose."""
    text = text.strip()
    fence_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text


def load_config():
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Config not found: {CONFIG_PATH}\nCopy and configure: {CONFIG_PATH}")
    return yaml.safe_load(CONFIG_PATH.read_text())


def run_cmd(cmd, timeout=300):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)


def build_chat_cmd(prompt, model, provider, quiet=True, toolsets=None):
    provider_flag = f" --provider {provider}" if provider else ""
    quiet_flag = " -Q" if quiet else ""
    tools_flag = f" -t {','.join(toolsets)}" if toolsets else ""
    return f"hermes chat -q {json.dumps(prompt)} -m {model}{provider_flag}{quiet_flag}{tools_flag} --source polygnosis"


def run_chat(prompt, model, provider, label, timeout=300, retry_count=0, toolsets=None):
    """Run hermes chat with optional retry. Returns (stdout, returncode)."""
    cmd = build_chat_cmd(prompt, model, provider, toolsets=toolsets)
    last_out = ""
    for attempt in range(retry_count + 1):
        try:
            print(f"  [{label}] running...", file=sys.stderr)
            res = run_cmd(cmd, timeout=timeout)
            last_out = res.stdout.strip()
            if last_out:
                return last_out, res.returncode
        except subprocess.TimeoutExpired:
            print(f"  [{label}] TIMEOUT after {timeout}s", file=sys.stderr)
            return "", -1
        except Exception as e:
            print(f"  [{label}] error: {e}", file=sys.stderr)
            if attempt == retry_count:
                return "", -1
    return last_out, -1


def get_solver_model_name(cfg, idx):
    """Get solver model name: explicit list > solver_N key > fallback."""
    solver_list = cfg.get("solver_models", [])
    if solver_list and idx < len(solver_list) and solver_list[idx]:
        return solver_list[idx]
    key = f"solver_{idx + 1}"
    model = cfg["models"].get(key, "")
    if model:
        return model
    return cfg["models"].get("fallback", "")


def get_provider_for(cfg, role):
    return cfg.get("providers", {}).get(role, "").strip()


# ═══════════════════════════════════════════════════════════════════════════════
# ── Asymmetric Tool Allocation (Objective 2) ──────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

# Toolset taxonomy for persona-based access control.
# "read-only" toolsets: inspect, search, read — no mutations.
# "write" toolsets: can create/modify files.
# Each persona is classified by keyword match, falling through to a default.

PERSONA_TOOLSET_MAP = [
    # Pattern → (toolsets, description)
    # ORDER MATTERS: most-specific patterns first to avoid greedy matches.
    # "data engineer" must be checked before bare "engineer", etc.

    # ── Read-only / review personas (cannot modify files) ──
    (r"security auditor|security analyst|penetration tester|qa engineer|compliance",
     ["web", "file"],
     "read-only (audit/review)"),

    (r"code reviewer|inspector|verifier|validator|critic|auditor|reviewer",
     ["web", "file"],
     "read-only (review/inspect)"),

    # ── Write-capable: domain-specific compound patterns (checked before generics) ──
    (r"data engineer|data architect|dba|database engineer|storage engineer|storage architect",
     ["terminal", "file", "web"],
     "write-capable (data/storage)"),

    (r"devops engineer|platform engineer|sre|cloud architect|cloud engineer|infrastructure engineer|infrastructure architect",
     ["terminal", "file", "web"],
     "write-capable (infrastructure)"),

    (r"fullstack|full.stack|full stack",
     ["terminal", "file", "web"],
     "write-capable (full-stack)"),

    (r"backend developer|frontend developer|backend engineer|frontend engineer",
     ["terminal", "file", "web"],
     "write-capable (full-stack)"),

    (r"solutions architect|system designer|systems architect",
     ["terminal", "file", "web"],
     "write-capable (architect/design)"),

    # ── Generic patterns (checked last among write-capable) ──
    (r"architect|designer",
     ["terminal", "file", "web"],
     "write-capable (architect/design)"),

    (r"developer|engineer|programmer|builder|implementer|coder",
     ["terminal", "file", "web"],
     "write-capable (developer)"),

    # Default for unrecognized personas — lean conservative (read-only)
    (r"",
     ["web", "file"],
     "read-only (unrecognized persona, conservative default)"),
]


def classify_persona_tools(persona: str):
    """Map a persona label to an allowed toolset list and classification label."""
    persona_lower = persona.lower()
    for pattern, toolsets, label in PERSONA_TOOLSET_MAP:
        if re.search(pattern, persona_lower):
            return toolsets, label
    return ["web", "file"], "read-only (fallback)"


# ═══════════════════════════════════════════════════════════════════════════════
# ── Reflexion Corrections Buffer ──────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def load_corrections_buffer():
    """Load session-local corrections buffer. Returns list of correction dicts."""
    try:
        if CORRECTIONS_BUFFER_PATH.exists():
            data = json.loads(CORRECTIONS_BUFFER_PATH.read_text())
            return data.get("corrections", []) if isinstance(data, dict) else []
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_corrections_buffer(corrections):
    """Persist corrections buffer to disk."""
    try:
        CORRECTIONS_BUFFER_PATH.parent.mkdir(parents=True, exist_ok=True)
        CORRECTIONS_BUFFER_PATH.write_text(json.dumps(
            {"version": 2, "corrections": corrections, "updated": time.strftime("%Y-%m-%dT%H:%M:%S")},
            indent=2
        ))
    except OSError as e:
        print(f"  [buffer] WARNING: failed to write corrections buffer: {e}", file=sys.stderr)


def ingest_critique_to_buffer(critique, solver_label, round_num):
    """Extract severe findings from a critique and append to buffer."""
    existing = load_corrections_buffer()
    new_entries = []

    # CRITICAL or HIGH severity bugs → save
    for bug in critique.get("critical_bugs", []):
        severity = bug.get("severity", "").upper()
        if severity in ("CRITICAL", "HIGH"):
            new_entries.append({
                "source": f"boardroom_critique_r{round_num}",
                "solver": solver_label,
                "severity": severity,
                "description": bug.get("description", ""),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })

    # Hallucinations → always save (any hallucination is a critical failure)
    for hal in critique.get("hallucinations_found", []):
        new_entries.append({
            "source": f"boardroom_critique_r{round_num}",
            "solver": solver_label,
            "severity": "HALLUCINATION",
            "description": f"Claimed: {hal.get('claimed', '?')} — Reality: {hal.get('reality', '?')}",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

    if new_entries:
        combined = existing + new_entries
        # Deduplicate by description
        seen = set()
        deduped = []
        for c in combined:
            key = c["description"].strip().lower()[:200]
            if key not in seen:
                seen.add(key)
                deduped.append(c)
        save_corrections_buffer(deduped)
        print(f"  [reflexion] {len(new_entries)} new correction(s) saved to buffer (total: {len(deduped)})", file=sys.stderr)
        return deduped
    return existing


def build_reflexion_injection():
    """Build a prompt snippet from the corrections buffer, or empty string."""
    corrections = load_corrections_buffer()
    if not corrections:
        return ""

    # Take most recent 10 entries to avoid context bloat
    recent = corrections[-10:]
    lines = [
        "\n\n─── LESSONS FROM PRIOR BOARDROOM SESSIONS (Reflexion Buffer) ───",
        "The following failures were caught in previous consensus runs.",
        "DO NOT repeat these mistakes:",
    ]
    for c in recent:
        lines.append(f"- [{c['severity']}] {c['description']}")
    lines.append("─── END REFLEXION BUFFER ───\n")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# ── Formal Consensus Algorithms (RRF + Borda) ─────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def rrf_rank(solutions_scores, k=60):
    """
    Reciprocal Rank Fusion.
    For each axis, rank solutions (ties = min rank).
    score = Σ 1/(k + rank) across all axes.
    Higher score = better. Returns sorted list of (solution_id, rrf_score).
    """
    n = len(solutions_scores)
    if n <= 1:
        return [(s["solution_id"], 1.0) for s in solutions_scores]

    rrf_scores = defaultdict(float)

    for axis in SCORING_AXES:
        # Sort by axis score descending
        ranked = sorted(solutions_scores, key=lambda s: s.get("scores", {}).get(axis, 0), reverse=True)
        for rank, sol in enumerate(ranked, start=1):
            rrf_scores[sol["solution_id"]] += 1.0 / (k + rank)

    return sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)


def borda_rank(solutions_scores):
    """
    Borda Count.
    Per axis: highest score gets (n-1) points, lowest gets 0.
    Sum points across all axes.
    Higher total = better. Returns sorted list of (solution_id, borda_total).
    """
    n = len(solutions_scores)
    if n <= 1:
        return [(s["solution_id"], 1.0) for s in solutions_scores]

    borda_totals = defaultdict(float)

    for axis in SCORING_AXES:
        # Sort by axis score descending
        ranked = sorted(solutions_scores, key=lambda s: s.get("scores", {}).get(axis, 0), reverse=True)
        for idx, sol in enumerate(ranked):
            # Borda: n - 1 - idx (so winner gets n-1, last gets 0)
            borda_totals[sol["solution_id"]] += (n - 1 - idx)

    return sorted(borda_totals.items(), key=lambda x: x[1], reverse=True)


def hybrid_rank(solutions_scores, k=60):
    """
    Hybrid: run both RRF and Borda, then average the normalized rank positions.
    The solution with the lowest average rank is the winner.
    Returns list of (solution_id, avg_rank, rrf_score, borda_score).
    """
    n = len(solutions_scores)
    if n <= 1:
        sol_id = solutions_scores[0]["solution_id"]
        return [(sol_id, 1.0, 1.0, 1.0)]

    rrf = dict(rrf_rank(solutions_scores, k=k))
    borda = dict(borda_rank(solutions_scores))

    # Normalize each to rank positions (1 = best)
    rrf_vals = sorted(rrf.values(), reverse=True)
    borda_vals = sorted(borda.values(), reverse=True)

    def rank_from_scores(val, sorted_vals):
        """Convert score to rank (1-indexed, ties get same rank)."""
        return sorted_vals.index(val) + 1

    results = []
    for s in solutions_scores:
        sid = s["solution_id"]
        r = rank_from_scores(rrf.get(sid, 0.0), rrf_vals)
        b = rank_from_scores(borda.get(sid, 0.0), borda_vals)
        avg = (r + b) / 2.0
        results.append((sid, avg, rrf.get(sid, 0.0), borda.get(sid, 0.0)))

    return sorted(results, key=lambda x: x[1])  # Lower avg_rank = better


def compute_consensus_ranking(scoring_json, algorithm="hybrid", k=60):
    """
    Take the LLM's per-axis scores and apply deterministic ranking algorithms.
    Returns a dict mapping solution_id → consolidated rank info.
    """
    rankings = scoring_json.get("rankings", []) if scoring_json else []

    # Convert to the shape the algorithms expect
    solutions_scores = []
    for r in rankings:
        sol = {
            "solution_id": r.get("solution_id", ""),
            "solver_label": r.get("solver_label", ""),
            "scores": r.get("scores", {}),
            "total": r.get("total", 0),
        }
        solutions_scores.append(sol)

    if not solutions_scores:
        return {}

    if algorithm == "rrf":
        ranked = rrf_rank(solutions_scores, k=k)
    elif algorithm == "borda":
        ranked = borda_rank(solutions_scores)
    else:  # hybrid
        ranked = hybrid_rank(solutions_scores, k=k)

    # Build output dict
    result = {}
    for i, item in enumerate(ranked):
        sid = str(item[0])
        if algorithm == "hybrid" and len(item) >= 4:
            # hybrid_rank returns (solution_id, avg_rank, rrf_score, borda_score)
            result[sid] = {"rank": i + 1, "avg_rank": float(item[1]), "rrf_score": float(item[2]), "borda_score": float(item[3])}
        else:
            # rrf_rank / borda_rank return (solution_id, score)
            result[sid] = {"rank": i + 1, "score": float(item[1])}

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# ── Prompts ──────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def build_orchestrator_prompt(objective):
    return (
        "SYSTEM: You are the Boardroom Orchestrator. You prepare a high-stakes problem "
        "for a multi-model debate with specialized expert personas.\n\n"
        "Given the user's objective, produce:\n"
        "1. A SINGLE self-contained problem statement (requirements, constraints, success criteria, edge cases, expected output format)\n"
        "2. A list of specialized EXPERT PERSONAS to solve the problem — one per solver. "
        "These should be DIFFERENT roles with complementary expertise relevant to the problem domain. "
        "Examples: for database optimization → \"DBA Consultant\", \"Backend Architect\", \"Security Auditor\". "
        "For a compiler task → \"Parser Designer\", \"Optimization Engineer\", \"Type System Expert\".\n\n"
        "Return JSON ONLY. Schema:\n"
        "{\n"
        '  "problem_statement": "<complete problem text given to every solver>",\n'
        '  "success_criteria": ["criterion 1", "criterion 2", ...],\n'
        '  "domain": "<e.g. systems programming, distributed systems, etc.>",\n'
        '  "personas": ["<Role 1 — title + one-line specialization>", "<Role 2>", "<Role 3>"],\n'
        '  "notes": "<optional context for the boardroom>"\n'
        "}\n"
        "No markdown, no code fences, no other text.\n\n"
        f"User Objective: {objective}"
    )


def build_solver_prompt(problem_statement, persona_label, reflexion_context="", toolsets=None, tool_class=None):
    """Build solver prompt with dynamic persona assignment, reflexion buffer, and tool access info."""
    tool_context = ""
    if tool_class:
        tool_context = (
            f"\nTOOL ACCESS: You have been assigned {tool_class} tools. "
            f"({', '.join(toolsets) if toolsets else 'no special tools'}). "
            "Operate within these constraints. If you need tools you don't have, "
            "note what you would do with them in your solution narrative.\n"
        )

    return (
        f"You are the {persona_label} in a multi-model consensus boardroom.\n\n"
        "You are solving this problem from your unique expert perspective. "
        "Your solution will be peer-reviewed by a hostile critic who will hunt "
        "for bugs, logical errors, security flaws, and hallucinations. "
        "Be rigorous. Show your reasoning. Anticipate criticism.\n\n"
        "IMPORTANT: Provide a COMPLETE, production-ready solution from YOUR "
        "specialist angle. Include all code, error handling, verification steps, "
        "and design rationale. Your perspective is unique — lean into it.\n"
        f"{tool_context}"
        f"{reflexion_context}"
        f"PROBLEM:\n{problem_statement}"
    )


def build_critique_prompt(problem_statement, solution_text, solver_label, solution_id):
    return (
        "SYSTEM: You are the Boardroom Critic. Your role is adversarial peer review.\n"
        "You MUST aggressively hunt for problems in the solution below. Be thorough. "
        "Be hostile. This is a code review by the world's most demanding senior engineer.\n\n"
        "Check for:\n"
        "1. BUGS: Logic errors, off-by-one, null pointer, race conditions, incorrect state handling\n"
        "2. EDGE CASES: Does it handle empty input, extreme values, concurrent access, malformed data?\n"
        "3. SECURITY: Injection vectors, insecure defaults, missing auth checks, exposed secrets, unsafe deserialization\n"
        "4. HALLUCINATIONS: Made-up APIs, non-existent functions, imaginary libraries, incorrect syntax\n"
        "5. PERFORMANCE: O(n²) where O(n) exists, unnecessary allocations, blocking patterns\n"
        "6. CORRECTNESS: Does the solution actually solve the stated problem completely?\n"
        "7. ARCHITECTURE: Design flaws, coupling, missing abstractions, wrong patterns\n\n"
        "Return JSON ONLY. Schema:\n"
        "{\n"
        f'  "solution_id": "{solution_id}",\n'
        f'  "solver": "{solver_label}",\n'
        '  "overall_grade": "PASS" or "FAIL" or "PASS_WITH_ISSUES",\n'
        '  "critical_bugs": [{"description": "...", "severity": "CRITICAL|HIGH|MEDIUM|LOW"}],\n'
        '  "hallucinations_found": [{"claimed": "...", "reality": "..."}],\n'
        '  "missing_edge_cases": ["..."],\n'
        '  "strengths": ["..."],\n'
        '  "weaknesses": ["..."],\n'
        '  "score": <integer 0-100 based on overall quality>,\n'
        '  "improvement_suggestions": ["..."]\n'
        "}\n"
        "No markdown, no code fences, no other text.\n\n"
        f"PROBLEM:\n{problem_statement}\n\n"
        f"SOLUTION BY {solver_label}:\n{solution_text}"
    )


def build_revision_prompt(problem_statement, original_solution, critique_json, persona_label):
    return (
        f"You are the {persona_label}. Your solution was critiqued. DEFEND AND IMPROVE.\n\n"
        "The boardroom critic has reviewed your solution. Your task:\n"
        "1. For every valid criticism: FIX IT. Do not dismiss real bugs.\n"
        "2. If the critic is wrong about something: rebut it with evidence.\n"
        "3. Produce a REVISED solution that addresses all valid concerns.\n"
        "4. Maintain your original strengths while fixing weaknesses.\n\n"
        "IMPORTANT: Your revised solution must be COMPLETE — provide the FULL revised output, not diffs.\n\n"
        f"PROBLEM:\n{problem_statement}\n\n"
        f"YOUR ORIGINAL SOLUTION:\n{original_solution}\n\n"
        f"CRITIQUE:\n{critique_json}\n\n"
        "Now produce your revised, defended, improved solution."
    )


def build_scoring_prompt(problem_statement, solutions_with_critiques):
    formatted_solutions = ""
    for si, s in enumerate(solutions_with_critiques, 1):
        formatted_solutions += (
            f"=== Solution {si}: {s['solver_label']} ===\n"
            f"Critic Score: {s.get('critic_score', 'N/A')}\n"
            f"Critic Grade: {s.get('critic_grade', 'N/A')}\n"
            f"Critique Summary: {s.get('critique_summary', 'N/A')}\n"
            f"Solution:\n{s['solution']}\n\n"
        )

    return (
        "SYSTEM: You are the Boardroom Scorer. Score each solution on 5 axes (0-10 each).\n\n"
        "AXES:\n"
        "1. CORRECTNESS: Does it actually solve the problem completely?\n"
        "2. EFFICIENCY: Optimal algorithms and resource usage\n"
        "3. MAINTAINABILITY: Clean code, clear design, good documentation\n"
        "4. ROBUSTNESS: Error handling, edge case coverage, resilience\n"
        "5. SECURITY: No vulnerabilities, secure defaults, defense in depth\n\n"
        "NOTE: Your scores are inputs to a formal ranking algorithm (Reciprocal Rank Fusion "
        "+ Borda Count) — be precise and objective. The algorithm, not your opinion, will "
        "determine the final winner.\n\n"
        "Return JSON ONLY. Schema:\n"
        "{\n"
        '  "rankings": [\n'
        "    {\n"
        '      "solution_id": "s<N>",\n'
        '      "solver_label": "label",\n'
        '      "scores": {"correctness": N, "efficiency": N, "maintainability": N, "robustness": N, "security": N},\n'
        '      "total": N\n'
        "    }\n"
        '  ],\n'
        '  "consensus_opinion": "Which elements from which solutions should go into the final synthesis"\n'
        "}\n"
        "No markdown, no code fences, no other text.\n\n"
        f"PROBLEM:\n{problem_statement}\n\n"
        f"SOLUTIONS + CRITIQUES:\n{formatted_solutions}"
    )


def build_synthesis_prompt(problem_statement, solutions, consensus_ranking, success_criteria):
    """Build synthesis prompt with formal consensus ranking injected."""
    ranking_text = ""
    for sid, rank_info in sorted(consensus_ranking.items(), key=lambda x: x[1].get("rank", 99)):
        label = next((s["solver_label"] for s in solutions if s.get("solution_id") == sid), sid)
        ranking_text += f"  Rank {rank_info['rank']}: {label}\n"

    formatted_solutions = ""
    for s in solutions:
        formatted_solutions += f"=== Solution: {s['solver_label']} ===\n{s.get('solution_text', s.get('solution', ''))}\n\n"

    return (
        "SYSTEM: You are the Boardroom Synthesizer. Produce a UNIFIED enterprise-grade solution.\n\n"
        "Rules:\n"
        "1. Extract the STRONGEST elements from each solution\n"
        "2. Fix any remaining bugs or flaws — do not propagate known issues\n"
        "3. Integrate the best ideas into ONE coherent, complete solution\n"
        "4. Produce production-ready code/output\n"
        "5. The final output must be SELF-CONTAINED — no 'see solution X' references\n\n"
        f"PROBLEM:\n{problem_statement}\n\n"
        f"SUCCESS CRITERIA:\n{chr(10).join('- ' + c for c in success_criteria)}\n\n"
        f"FORMAL CONSENSUS RANKING (RRF + Borda hybrid):\n{ranking_text}\n"
        f"ALL SOLUTIONS:\n{formatted_solutions}\n\n"
        "Now produce the FINAL UNIFIED SOLUTION:"
    )


def build_quality_gate_prompt(problem_statement, synthesis, top_solution, top_label):
    """Compare synthesis against the best individual solution."""
    return (
        "SYSTEM: You are the Constitutional Quality Gate. You compare two solutions and "
        "determine whether the synthesis IMPROVED or REGRESSED relative to the best individual solution.\n\n"
        "Evaluation criteria:\n"
        "1. CORRECTNESS: Is the synthesis at least as correct as the individual solution?\n"
        "2. COMPLETENESS: Does the synthesis cover everything the individual solution did?\n"
        "3. CLARITY: Is the synthesis equally or more clear?\n"
        "4. REGRESSIONS: Did the synthesis introduce any new bugs, omissions, or hallucinations?\n\n"
        "Return JSON ONLY. Schema:\n"
        "{\n"
        '  "verdict": "PASS" or "FAIL",\n'
        '  "reasoning": "Why the synthesis passed or failed the quality gate",\n'
        '  "regressions_found": ["specific regression 1", ...],\n'
        '  "improvements_found": ["specific improvement 1", ...]\n'
        "}\n"
        "No markdown, no code fences, no other text.\n\n"
        f"PROBLEM:\n{problem_statement}\n\n"
        f"TOP INDIVIDUAL SOLUTION ({top_label}):\n{top_solution[:8000]}\n\n"
        f"SYNTHESIZED SOLUTION:\n{synthesis[:8000]}\n\n"
        "Now judge:"
    )


def build_meta_review_prompt(problem_statement, consensus_ranking, solutions, final_output, success_criteria, quality_gate_result=None):
    """Build meta-review prompt with quality gate context."""
    ranking_text = ""
    for sid, rank_info in sorted(consensus_ranking.items(), key=lambda x: x[1].get("rank", 99)):
        label = next((s["solver_label"] for s in solutions if s.get("solution_id") == sid), sid)
        ranking_text += f"Rank {rank_info['rank']}: {label}\n"

    qg_text = ""
    if quality_gate_result:
        qg_text = (
            f"\nQuality Gate Result: {quality_gate_result.get('verdict', 'N/A')}\n"
            f"Reasoning: {quality_gate_result.get('reasoning', 'N/A')}\n"
        )

    return (
        "SYSTEM: You are the Boardroom Meta-Reviewer. Explain the consensus to the user.\n\n"
        "Write a brief Meta-Review summary covering:\n"
        "1. Why this final output was chosen — which solution(s) contributed most and why\n"
        "2. What specific flaws were rejected from each solver's initial draft\n"
        "3. How the critique process improved the final output\n"
        "4. Whether the quality gate passed and what it found\n"
        "5. Any remaining risks or limitations the user should know about\n\n"
        "Format as plain text. Be concise but thorough. No filler.\n\n"
        f"PROBLEM:\n{problem_statement}\n\n"
        f"SUCCESS CRITERIA:\n{chr(10).join('- ' + c for c in success_criteria)}\n\n"
        f"CONSENSUS RANKING (RRF + Borda):\n{ranking_text}{qg_text}\n\n"
        f"FINAL OUTPUT:\n{final_output[:3000]}...\n\n"
        "Now write the Meta-Review:"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ── Pipeline Phases ───────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def phase_orchestrate(cfg, objective, run_dir):
    """Phase 0: Build problem statement + dynamic personas."""
    print("─ Phase 0: Orchestrator (problem statement + personas) ─", file=sys.stderr)

    orch_model = cfg["models"].get("orchestrator", "") or cfg["models"].get("fallback", "")
    orch_provider = get_provider_for(cfg, "orchestrator")
    orch_timeout = cfg.get("settings", {}).get("orchestrator_timeout_sec", 120)

    if not orch_model:
        raise SystemExit("No orchestrator model configured in polygnosis/config.yaml")

    orch_out, _ = run_chat(
        build_orchestrator_prompt(objective), orch_model, orch_provider,
        "orchestrator", timeout=orch_timeout
    )
    (run_dir / "orchestrator_raw.txt").write_text(orch_out)

    try:
        orch_json = json.loads(extract_json(orch_out)) if orch_out else {}
    except json.JSONDecodeError:
        orch_json = {}

    problem_statement = orch_json.get("problem_statement", objective)
    success_criteria = orch_json.get("success_criteria", ["Correctness", "Completeness", "Robustness"])
    personas = orch_json.get("personas", [])
    domain = orch_json.get("domain", "general")

    # If orchestrator didn't produce personas, generate defaults from domain
    if not personas:
        solver_count = min(cfg.get("settings", {}).get("solver_count", 3), 5)
        personas = [f"Senior {domain.title()} Expert {chr(65 + i)}" for i in range(solver_count)]

    (run_dir / "orchestrator.json").write_text(json.dumps(orch_json, indent=2))
    print(f"  Domain: {domain}", file=sys.stderr)
    print(f"  Personas: {personas}", file=sys.stderr)
    print(f"  Problem statement: {len(problem_statement)} chars", file=sys.stderr)

    return problem_statement, success_criteria, personas, domain


def phase_parallel_solve(cfg, problem_statement, personas, run_dir):
    """Phase 1: Parallel solve with dynamic persona-driven prompts."""
    settings = cfg.get("settings", {})
    solver_count = min(settings.get("solver_count", 3), 5)
    solver_timeout = settings.get("solver_timeout_sec", 600)
    min_quorum = settings.get("min_solvers_for_quorum", 2)

    print(f"\n─ Phase 1: Parallel Solve ({solver_count} models, persona-driven) ─", file=sys.stderr)

    reflexion_context = build_reflexion_injection()

    solver_results = {}  # sid -> {"persona": ..., "model": ..., "solution": ...}
    dead_solvers = []

    def execute_solver(idx):
        model = get_solver_model_name(cfg, idx)
        if not model:
            return idx, None, "no model configured"
        persona = personas[idx] if idx < len(personas) else f"Solver-{chr(65 + idx)}"
        provider = get_provider_for(cfg, f"solver_{idx + 1}")

        # Asymmetric tool allocation: classify persona → toolset
        solver_toolsets, tool_class = classify_persona_tools(persona)
        prompt = build_solver_prompt(problem_statement, persona, reflexion_context, solver_toolsets, tool_class)

        stdout, rc = run_chat(prompt, model, provider, persona, timeout=solver_timeout, toolsets=solver_toolsets)
        if rc != 0 or not stdout:
            return idx, None, f"timeout or empty (rc={rc})"
        return idx, {
            "persona": persona, "solution_id": f"s{idx}", "model": model,
            "solution": stdout, "toolsets": solver_toolsets, "tool_class": tool_class
        }, None

    with ThreadPoolExecutor(max_workers=solver_count) as ex:
        futures = {ex.submit(execute_solver, i): i for i in range(solver_count)}
        for f in as_completed(futures):
            idx, result, error = f.result()
            if error:
                dead_solvers.append((idx, error))
                print(f"  [{chr(65+idx)}] FAILED: {error}", file=sys.stderr)
            else:
                assert result is not None
                solver_results[idx] = result
                label = chr(65 + idx)
                persona_slug = result["persona"].replace(" ", "_").replace("/", "-")[:30]
                (run_dir / f"solver_{label}_{persona_slug}_initial.md").write_text(result["solution"])
                print(f"  [{label}] COMPLETE — {result['persona']} [{result.get('tool_class', '?')}] ({result['model']}, {len(result['solution'])} chars)", file=sys.stderr)

    alive_count = len(solver_results)
    if alive_count < min_quorum:
        raise SystemExit(f"Insufficient solvers: {alive_count} alive, {min_quorum} required. Dead: {dead_solvers}")

    print(f"  {alive_count}/{solver_count} solvers completed successfully", file=sys.stderr)
    return solver_results


# ═══════════════════════════════════════════════════════════════════════════════
# ── Phase 1.5: Early Resolution Circuit (Quorum Voting) ──────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

EARLY_RESOLUTION_PROMPT = (
    "SYSTEM: You are the Boardroom Quorum Judge. Evaluate whether the following "
    "independent solutions reached UNANIMOUS CONSENSUS on the core approach.\n\n"
    "Consensus means: all solvers proposed fundamentally the SAME architecture, "
    "algorithm, or solution pattern — even if wording differs. They agree on the "
    "WHAT and HOW, not just the superficial phrasing.\n\n"
    "Non-consensus means: at least one solver took a meaningfully different approach "
    "(different algorithm, different architecture, different data structure, "
    "different trade-offs) that would lead to a substantially different outcome.\n\n"
    "Return JSON ONLY. Schema:\n"
    "{{\n"
    '  "unanimous": true or false,\n'
    '  "confidence": <float 0.0-1.0, how certain you are>,\n'
    '  "consensus_approach": "<one-line description of the agreed approach, if unanimous>",\n'
    '  "divergences": ["<description of any meaningful differences, if not unanimous>"]\n'
    "}}\n"
    "No markdown, no code fences, no other text.\n\n"
    "PROBLEM:\n{problem_statement}\n\n"
    "SOLUTIONS:\n{solutions_text}"
)


def early_resolution_check(cfg, problem_statement, solver_results, run_dir):
    """
    After Phase 1: evaluate whether all solvers reached unanimous consensus.
    If yes, return a consensus_ranking (all tied) and skip critique + scoring.
    Returns (early_resolved: bool, consensus_ranking: dict, scorer_solutions: list).
    """
    settings = cfg.get("settings", {})
    early_resolution_enabled = settings.get("early_resolution_enabled", True)

    if not early_resolution_enabled:
        return False, None, None

    # Only run on 3+ solvers for meaningful quorum
    if len(solver_results) < 3:
        return False, None, None

    print(f"\n─ Phase 1.5: Early Resolution / Quorum Vote ─", file=sys.stderr)

    # Build solutions text for the judge
    solutions_parts = []
    for sid in sorted(solver_results.keys()):
        sol = solver_results[sid]
        solutions_parts.append(
            f"=== {sol['persona']} (solver-{chr(65+sid)}) ===\n"
            f"{sol['solution'][:3000]}\n"
        )
    solutions_text = "\n\n".join(solutions_parts)

    judge_model = cfg["models"].get("orchestrator", "") or cfg["models"].get("fallback", "")
    judge_provider = get_provider_for(cfg, "orchestrator")
    orch_timeout = settings.get("orchestrator_timeout_sec", 120)

    judge_prompt = EARLY_RESOLUTION_PROMPT.format(
        problem_statement=problem_statement,
        solutions_text=solutions_text
    )

    judge_out, rc = run_chat(judge_prompt, judge_model, judge_provider, "quorum-judge", timeout=orch_timeout)
    (run_dir / "early_resolution_raw.txt").write_text(judge_out)

    try:
        verdict = json.loads(extract_json(judge_out)) if judge_out else {}
    except json.JSONDecodeError:
        verdict = {"unanimous": False, "confidence": 0.0, "divergences": ["Judge returned non-JSON — defaulting to no consensus."]}

    (run_dir / "early_resolution.json").write_text(json.dumps(verdict, indent=2))

    is_unanimous = verdict.get("unanimous", False)
    confidence = verdict.get("confidence", 0.0)

    if is_unanimous and confidence >= 0.7:
        consensus_approach = verdict.get("consensus_approach", "unanimous agreement")
        print(f"  ✓ UNANIMOUS CONSENSUS DETECTED (confidence={confidence})", file=sys.stderr)
        print(f"  Approach: {consensus_approach}", file=sys.stderr)
        print(f"  ⚡ EARLY RESOLUTION — skipping Critique + Scoring phases", file=sys.stderr)

        # Build synthetic consensus_ranking: all tied at rank 1
        consensus_ranking = {}
        for sid in sorted(solver_results.keys()):
            consensus_ranking[f"s{sid}"] = {
                "rank": 1,
                "note": "unanimous consensus — all solutions functionally identical",
            }

        # Build scorer_solutions from solver_results directly (no critique data)
        scorer_solutions = []
        for sid in sorted(solver_results.keys()):
            sol = solver_results[sid]
            scorer_solutions.append({
                "solution_id": f"s{sid}",
                "solver_label": sol["persona"],
                "solution": sol["solution"],
                "critic_score": 100,
                "critic_grade": "PASS",
                "critique_summary": "Early resolution: unanimous consensus detected. Critique bypassed.",
            })

        return True, consensus_ranking, scorer_solutions

    else:
        if is_unanimous:
            print(f"  Unanimous but low confidence ({confidence}) — proceeding to full critique", file=sys.stderr)
        else:
            divergences = verdict.get("divergences", ["no details"])
            print(f"  ✗ No consensus — {len(divergences)} divergence(s) found", file=sys.stderr)
            for d in divergences[:3]:
                print(f"    • {d}", file=sys.stderr)
        print(f"  → Proceeding to full critique pipeline", file=sys.stderr)
        return False, None, None


# ═══════════════════════════════════════════════════════════════════════════════

def phase_critique(cfg, problem_statement, solver_results, run_dir):
    """Phase 2: Adversarial critique + reflexion buffer ingestion."""
    settings = cfg.get("settings", {})
    debate_rounds = settings.get("max_debate_rounds", 2)
    critic_timeout = settings.get("critic_timeout_sec", 600)
    solver_timeout = settings.get("solver_timeout_sec", 600)

    print(f"\n─ Phase 2: Adversarial Critique + Reflexion ({debate_rounds} round(s)) ─", file=sys.stderr)

    critic_model = cfg["models"].get("critic", "") or cfg["models"].get("fallback", "")
    critic_provider = get_provider_for(cfg, "critic")
    alive_count = len(solver_results)

    critique_data = {}

    for round_num in range(debate_rounds):
        print(f"  Round {round_num + 1}/{debate_rounds}...", file=sys.stderr)

        def execute_critique(sid, sol_data):
            sol_label = sol_data["persona"]
            sol_text = sol_data["solution"]
            prompt = build_critique_prompt(problem_statement, sol_text, sol_label, f"s{sid}")
            stdout, rc = run_chat(prompt, critic_model, critic_provider, f"C-{sol_label}", timeout=critic_timeout)
            if rc != 0 or not stdout:
                return sid, None
            try:
                crit_json = json.loads(extract_json(stdout))
            except json.JSONDecodeError:
                crit_json = {
                    "solution_id": f"s{sid}",
                    "solver": sol_label,
                    "overall_grade": "PASS_WITH_ISSUES",
                    "score": 50,
                    "raw_text": stdout,
                }
            return sid, crit_json

        with ThreadPoolExecutor(max_workers=alive_count) as ex:
            crit_futures = {}
            for sid in sorted(solver_results.keys()):
                crit_futures[ex.submit(execute_critique, sid, solver_results[sid])] = sid

            for f in as_completed(crit_futures):
                sid, crit = f.result()
                if crit:
                    critique_data[sid] = crit
                    (run_dir / f"critique_{chr(65+sid)}_r{round_num+1}.json").write_text(json.dumps(crit, indent=2))
                    print(f"    [Critique {chr(65+sid)}] score={crit.get('score', 'N/A')}, grade={crit.get('overall_grade', 'N/A')}", file=sys.stderr)

                    # ── Reflexion: ingest severe findings into buffer ──
                    ingest_critique_to_buffer(crit, solver_results[sid]["persona"], round_num + 1)
                else:
                    print(f"    [Critique {chr(65+sid)}] FAILED", file=sys.stderr)

        # Revision round (if not last)
        if round_num < debate_rounds - 1:
            print(f"    Revision round {round_num + 1}...", file=sys.stderr)

            def execute_revision(sid, sol_data):
                persona = sol_data["persona"]
                sol_text = sol_data["solution"]
                crit = critique_data.get(sid, {})
                prompt = build_revision_prompt(
                    problem_statement, sol_text,
                    json.dumps(crit, indent=2), persona
                )
                model = get_solver_model_name(cfg, sid)
                provider = get_provider_for(cfg, f"solver_{sid + 1}")
                stdout, rc = run_chat(prompt, model, provider, f"R-{persona}", timeout=solver_timeout)
                return sid, stdout if (rc == 0 and stdout) else sol_text

            with ThreadPoolExecutor(max_workers=alive_count) as ex:
                rev_futures = {}
                for sid in sorted(solver_results.keys()):
                    rev_futures[ex.submit(execute_revision, sid, solver_results[sid])] = sid

                for f in as_completed(rev_futures):
                    sid, revised = f.result()
                    solver_results[sid]["solution"] = revised
                    (run_dir / f"solver_{chr(65+sid)}_r{round_num+2}.md").write_text(revised)
                    print(f"    [Revision {chr(65+sid)}] {len(revised)} chars", file=sys.stderr)

    return critique_data


def phase_scoring(cfg, problem_statement, solver_results, critique_data, run_dir):
    """Phase 3: LLM per-axis scoring → formal consensus ranking (RRF + Borda)."""
    settings = cfg.get("settings", {})
    algorithm = settings.get("scoring_algorithm", "hybrid")
    rrf_k = settings.get("rrf_k", 60)
    synth_timeout = settings.get("synthesizer_timeout_sec", 300)

    print(f"\n─ Phase 3: Consensus Scoring ({algorithm}) ─", file=sys.stderr)

    # Prepare solutions with critiques for LLM scorer
    scorer_solutions = []
    for sid in sorted(solver_results.keys()):
        sol = solver_results[sid]
        crit = critique_data.get(sid, {})
        scorer_solutions.append({
            "solution_id": f"s{sid}",
            "solver_label": sol["persona"],
            "solution": sol["solution"],
            "critic_score": crit.get("score", "N/A"),
            "critic_grade": crit.get("overall_grade", "N/A"),
            "critique_summary": json.dumps(crit, indent=2) if isinstance(crit, dict) else str(crit),
        })

    scorer_model = cfg["models"].get("synthesizer", "") or cfg["models"].get("fallback", "")
    scorer_provider = get_provider_for(cfg, "synthesizer")

    scoring_out, _ = run_chat(
        build_scoring_prompt(problem_statement, scorer_solutions),
        scorer_model, scorer_provider, "scorer", timeout=synth_timeout
    )

    try:
        scoring_json = json.loads(extract_json(scoring_out)) if scoring_out else {}
    except json.JSONDecodeError:
        scoring_json = {"raw_text": scoring_out}

    (run_dir / "scoring_raw.json").write_text(json.dumps(scoring_json, indent=2))

    # ── Apply formal consensus algorithm ──
    consensus_ranking = compute_consensus_ranking(scoring_json, algorithm=algorithm, k=rrf_k)

    # Merge rankings into scoring_json for artifact clarity
    scoring_json["_consensus_algorithm"] = algorithm
    scoring_json["_consensus_ranking"] = consensus_ranking  # type: ignore[assignment]
    (run_dir / "scoring.json").write_text(json.dumps(scoring_json, indent=2))

    print(f"  Algorithm: {algorithm} (k={rrf_k})", file=sys.stderr)
    for sid, rank_info in sorted(consensus_ranking.items(), key=lambda x: x[1].get("rank", 99)):
        label = next((s["solver_label"] for s in scorer_solutions if s["solution_id"] == sid), sid)
        print(f"    Rank {rank_info['rank']}: {label}", file=sys.stderr)

    return scoring_json, consensus_ranking, scorer_solutions


def phase_synthesis(cfg, problem_statement, solver_results, consensus_ranking,
                    scorer_solutions, success_criteria, run_dir):
    """Phase 4: Meta-Synthesis from ranked solutions."""
    settings = cfg.get("settings", {})
    synth_timeout = settings.get("synthesizer_timeout_sec", 300)

    print(f"\n─ Phase 4: Synthesis ─", file=sys.stderr)

    synth_model = cfg["models"].get("synthesizer", "") or cfg["models"].get("fallback", "")
    synth_provider = get_provider_for(cfg, "synthesizer")

    # Build solution list for the synthesis prompt
    solutions_for_prompt = []
    for sid in sorted(solver_results.keys()):
        sol = solver_results[sid]
        solutions_for_prompt.append({
            "solution_id": f"s{sid}",
            "solver_label": sol["persona"],
            "solution_text": sol["solution"],
            "solution": sol["solution"],
        })

    synthesis, _ = run_chat(
        build_synthesis_prompt(problem_statement, solutions_for_prompt, consensus_ranking, success_criteria),
        synth_model, synth_provider, "synthesizer", timeout=synth_timeout
    )
    (run_dir / "synthesis_raw.md").write_text(synthesis)
    print(f"  Synthesis: {len(synthesis)} chars", file=sys.stderr)

    return synthesis


def phase_quality_gate(cfg, problem_statement, synthesis, consensus_ranking, solver_results, run_dir):
    """Phase 5: Constitutional Quality Gate — compare synthesis vs top individual solution."""
    settings = cfg.get("settings", {})
    qg_enabled = settings.get("quality_gate_enabled", True)
    synth_timeout = settings.get("synthesizer_timeout_sec", 300)

    if not qg_enabled:
        print(f"\n─ Phase 5: Quality Gate (disabled) ─", file=sys.stderr)
        return None, synthesis

    print(f"\n─ Phase 5: Constitutional Quality Gate ─", file=sys.stderr)

    # Find the top-ranked solver
    top_sid = None
    best_rank = 999
    for sid, rank_info in sorted(consensus_ranking.items(), key=lambda x: x[1].get("rank", 99)):
        if rank_info.get("rank", 999) < best_rank:
            best_rank = rank_info["rank"]
            top_sid = sid

    if not top_sid or top_sid == "sNone":
        print(f"  No top-ranked solution found — skipping quality gate", file=sys.stderr)
        return None, synthesis

    # Map solution_id back to solver index
    try:
        top_idx = int(top_sid[1:])  # "s0" → 0, "s1" → 1
    except (ValueError, IndexError):
        print(f"  Cannot parse top solution ID: {top_sid}", file=sys.stderr)
        return None, synthesis

    if top_idx not in solver_results:
        print(f"  Top solution {top_sid} not in results — skipping quality gate", file=sys.stderr)
        return None, synthesis

    top_solution = solver_results[top_idx]["solution"]
    top_label = solver_results[top_idx]["persona"]

    gate_model = cfg["models"].get("synthesizer", "") or cfg["models"].get("fallback", "")
    gate_provider = get_provider_for(cfg, "synthesizer")

    gate_out, _ = run_chat(
        build_quality_gate_prompt(problem_statement, synthesis, top_solution, top_label),
        gate_model, gate_provider, "quality-gate", timeout=synth_timeout
    )

    try:
        gate_result = json.loads(extract_json(gate_out)) if gate_out else {}
    except json.JSONDecodeError:
        gate_result = {"verdict": "PASS", "reasoning": "Quality gate model returned non-JSON — defaulting to PASS."}

    (run_dir / "quality_gate.json").write_text(json.dumps(gate_result, indent=2))

    verdict = gate_result.get("verdict", "PASS")
    print(f"  Verdict: {verdict}", file=sys.stderr)

    if verdict == "FAIL":
        print(f"  SYNTHESIS REJECTED — falling back to top individual solution ({top_label})", file=sys.stderr)
        print(f"  Regressions: {gate_result.get('regressions_found', [])}", file=sys.stderr)
        return gate_result, top_solution
    else:
        if gate_result.get("regressions_found"):
            print(f"  Minor issues noted: {gate_result.get('regressions_found', [])}", file=sys.stderr)
        return gate_result, synthesis


def phase_meta_review(cfg, problem_statement, consensus_ranking, scorer_solutions,
                      final_output, success_criteria, quality_gate_result, run_dir):
    """Phase 6: Meta-Review explaining the consensus."""
    settings = cfg.get("settings", {})
    meta_timeout = settings.get("meta_reviewer_timeout_sec", 180)

    print(f"\n─ Phase 6: Meta-Review ─", file=sys.stderr)

    meta_model = cfg["models"].get("meta_reviewer", "") or cfg["models"].get("fallback", "")
    meta_provider = get_provider_for(cfg, "meta_reviewer")

    meta_review, _ = run_chat(
        build_meta_review_prompt(problem_statement, consensus_ranking, scorer_solutions,
                                 final_output, success_criteria, quality_gate_result),
        meta_model, meta_provider, "meta-reviewer", timeout=meta_timeout
    )
    (run_dir / "meta_review.md").write_text(meta_review)
    print(f"  Meta-Review: {len(meta_review)} chars", file=sys.stderr)

    return meta_review


# ═══════════════════════════════════════════════════════════════════════════════
# ── Main ─────────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    cfg = load_config()
    settings = cfg.get("settings", {})
    artifacts_root = Path(settings.get("artifacts_dir", ".hermes/plans/polygnosis"))

    run_id = time.strftime("%Y%m%d_%H%M%S")
    run_dir = artifacts_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Get objective from stdin or prompt
    if not sys.stdin.isatty():
        objective = sys.stdin.read().strip()
    else:
        objective = input("Objective: ").strip()

    if not objective:
        raise SystemExit("No objective provided.")

    print(f"\n╔══════════════════════════════════════════════════════╗", file=sys.stderr)
    print(f"║   POLYGNOSIS v3 — Consensus + Tools          ║", file=sys.stderr)
    print(f"║   RRF+Borda · Quality Gate · Reflexion · Early Exit   ║", file=sys.stderr)
    print(f"╚══════════════════════════════════════════════════════╝\n", file=sys.stderr)

    # ── Phase 0: Orchestrate ──────────────────────────────────────────────────
    problem_statement, success_criteria, personas, domain = phase_orchestrate(cfg, objective, run_dir)

    # ── Phase 1: Parallel Solve (persona-driven + asymmetric tools) ───────────
    solver_results = phase_parallel_solve(cfg, problem_statement, personas, run_dir)

    # ── Phase 1.5: Early Resolution / Quorum Vote (Objective 1) ───────────────
    early_resolved, consensus_ranking, scorer_solutions = early_resolution_check(
        cfg, problem_statement, solver_results, run_dir
    )

    if early_resolved:
        # Skip Phases 2+3 entirely — jump to Synthesis with unanimous ranking
        scoring_json = {"_early_resolution": True, "_note": "Critique + scoring bypassed"}
        critique_data = {}  # Empty — no critique needed
    else:
        # ── Phase 2: Adversarial Critique + Reflexion ─────────────────────────
        critique_data = phase_critique(cfg, problem_statement, solver_results, run_dir)

        # ── Phase 3: Formal Consensus Scoring (RRF + Borda) ──────────────────
        scoring_json, consensus_ranking, scorer_solutions = phase_scoring(
            cfg, problem_statement, solver_results, critique_data, run_dir
        )

    # ── Phase 4: Synthesis ────────────────────────────────────────────────────
    synthesis = phase_synthesis(
        cfg, problem_statement, solver_results, consensus_ranking,
        scorer_solutions, success_criteria, run_dir
    )

    # ── Phase 5: Constitutional Quality Gate ──────────────────────────────────
    quality_gate_result, final_output = phase_quality_gate(
        cfg, problem_statement, synthesis, consensus_ranking, solver_results, run_dir
    )
    (run_dir / "final_output.md").write_text(final_output)

    # ── Phase 6: Meta-Review ──────────────────────────────────────────────────
    meta_review = phase_meta_review(
        cfg, problem_statement, consensus_ranking, scorer_solutions,
        final_output, success_criteria, quality_gate_result, run_dir
    )

    # ── Final Output ──────────────────────────────────────────────────────────

    # Show corrections buffer summary
    buffer = load_corrections_buffer()
    buffer_count = len(buffer)

    print(f"\nArtifacts: {run_dir}", file=sys.stderr)
    print(f"Reflexion buffer: {buffer_count} correction(s) accumulated", file=sys.stderr)
    print(f"╔══════════════════════════════════════════════════════╗", file=sys.stderr)
    print(f"║   POLYGNOSIS COMPLETE                                 ║", file=sys.stderr)
    print(f"╚══════════════════════════════════════════════════════╝\n", file=sys.stderr)

    # Print final output to stdout: synthesis + quality gate note + meta-review
    if quality_gate_result and quality_gate_result.get("verdict") == "FAIL":
        print("─── NOTE: Quality Gate rejected synthesis — showing top individual solution ───\n")

    print(final_output)

    if meta_review:
        print("\n\n─── Boardroom Meta-Review ───\n")
        print(meta_review)


if __name__ == "__main__":
    main()
