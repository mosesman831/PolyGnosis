"""Boardroom prompt templates — ported from PolyGnosis v3."""

from __future__ import annotations

from typing import Any


def build_orchestrator_prompt(objective: str) -> str:
    return (
        "SYSTEM: You are the Boardroom Orchestrator. You prepare a high-stakes problem "
        "for a multi-model debate with specialized expert personas.\n\n"
        "Given the user's objective, produce:\n"
        "1. A SINGLE self-contained problem statement (requirements, constraints, "
        "success criteria, edge cases, expected output format)\n"
        "2. A list of specialized EXPERT PERSONAS to solve the problem — one per solver. "
        "These should be DIFFERENT roles with complementary expertise relevant to the "
        "problem domain. Examples: for database optimization → \"DBA Consultant\", "
        "\"Backend Architect\", \"Security Auditor\". For a compiler task → "
        "\"Parser Designer\", \"Optimization Engineer\", \"Type System Expert\".\n\n"
        "Return JSON ONLY. Schema:\n"
        "{\n"
        '  "problem_statement": "<complete problem text given to every solver>",\n'
        '  "success_criteria": ["criterion 1", "criterion 2", ...],\n'
        '  "domain": "<e.g. systems programming, distributed systems, etc.>",\n'
        '  "personas": ["<Role 1 — title + one-line specialization>", '
        '"<Role 2>", "<Role 3>"],\n'
        '  "notes": "<optional context for the boardroom>"\n'
        "}\n"
        "No markdown, no code fences, no other text.\n\n"
        f"User Objective: {objective}"
    )


def build_solver_prompt(
    problem_statement: str,
    persona_label: str,
    reflexion_context: str = "",
    toolsets: list[str] | None = None,
    tool_class: str | None = None,
) -> str:
    tool_context = ""
    if tool_class:
        tool_context = (
            f"\nPERSPECTIVE CONSTRAINT: You are classified as {tool_class} "
            f"({', '.join(toolsets) if toolsets else 'general'}). "
            "Lean into this lens. If you would use tools you don't have in this "
            "API mode, note what you would verify with them in your narrative.\n"
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


def build_critique_prompt(
    problem_statement: str,
    solution_text: str,
    solver_label: str,
    solution_id: str,
) -> str:
    return (
        "SYSTEM: You are the Boardroom Critic. Your role is adversarial peer review.\n"
        "You MUST aggressively hunt for problems in the solution below. Be thorough. "
        "Be hostile. This is a code review by the world's most demanding senior engineer.\n\n"
        "Check for:\n"
        "1. BUGS: Logic errors, off-by-one, null pointer, race conditions, "
        "incorrect state handling\n"
        "2. EDGE CASES: Does it handle empty input, extreme values, concurrent access, "
        "malformed data?\n"
        "3. SECURITY: Injection vectors, insecure defaults, missing auth checks, "
        "exposed secrets, unsafe deserialization\n"
        "4. HALLUCINATIONS: Made-up APIs, non-existent functions, imaginary libraries, "
        "incorrect syntax\n"
        "5. PERFORMANCE: O(n²) where O(n) exists, unnecessary allocations, "
        "blocking patterns\n"
        "6. CORRECTNESS: Does the solution actually solve the stated problem completely?\n"
        "7. ARCHITECTURE: Design flaws, coupling, missing abstractions, wrong patterns\n\n"
        "Return JSON ONLY. Schema:\n"
        "{\n"
        f'  "solution_id": "{solution_id}",\n'
        f'  "solver": "{solver_label}",\n'
        '  "overall_grade": "PASS" or "FAIL" or "PASS_WITH_ISSUES",\n'
        '  "critical_bugs": [{"description": "...", '
        '"severity": "CRITICAL|HIGH|MEDIUM|LOW"}],\n'
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


def build_revision_prompt(
    problem_statement: str,
    original_solution: str,
    critique_json: str,
    persona_label: str,
) -> str:
    return (
        f"You are the {persona_label}. Your solution was critiqued. DEFEND AND IMPROVE.\n\n"
        "The boardroom critic has reviewed your solution. Your task:\n"
        "1. For every valid criticism: FIX IT. Do not dismiss real bugs.\n"
        "2. If the critic is wrong about something: rebut it with evidence.\n"
        "3. Produce a REVISED solution that addresses all valid concerns.\n"
        "4. Maintain your original strengths while fixing weaknesses.\n\n"
        "IMPORTANT: Your revised solution must be COMPLETE — provide the FULL "
        "revised output, not diffs.\n\n"
        f"PROBLEM:\n{problem_statement}\n\n"
        f"YOUR ORIGINAL SOLUTION:\n{original_solution}\n\n"
        f"CRITIQUE:\n{critique_json}\n\n"
        "Now produce your revised, defended, improved solution."
    )


def build_scoring_prompt(problem_statement: str, solutions_with_critiques: list[dict]) -> str:
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
        "SYSTEM: You are the Boardroom Scorer. Score each solution on 5 axes "
        "(0-10 each).\n\n"
        "AXES:\n"
        "1. CORRECTNESS: Does it actually solve the problem completely?\n"
        "2. EFFICIENCY: Optimal algorithms and resource usage\n"
        "3. MAINTAINABILITY: Clean code, clear design, good documentation\n"
        "4. ROBUSTNESS: Error handling, edge case coverage, resilience\n"
        "5. SECURITY: No vulnerabilities, secure defaults, defense in depth\n\n"
        "NOTE: Your scores are inputs to a formal ranking algorithm "
        "(Reciprocal Rank Fusion + Borda Count) — be precise and objective. "
        "The algorithm, not your opinion, will determine the final winner.\n\n"
        "Return JSON ONLY. Schema:\n"
        "{\n"
        '  "rankings": [\n'
        "    {\n"
        '      "solution_id": "s<N>",\n'
        '      "solver_label": "label",\n'
        '      "scores": {"correctness": N, "efficiency": N, '
        '"maintainability": N, "robustness": N, "security": N},\n'
        '      "total": N\n'
        "    }\n"
        "  ],\n"
        '  "consensus_opinion": "Which elements from which solutions should go '
        'into the final synthesis"\n'
        "}\n"
        "No markdown, no code fences, no other text.\n\n"
        f"PROBLEM:\n{problem_statement}\n\n"
        f"SOLUTIONS + CRITIQUES:\n{formatted_solutions}"
    )


def build_synthesis_prompt(
    problem_statement: str,
    solutions: list[dict],
    consensus_ranking: dict[str, Any],
    success_criteria: list[str],
) -> str:
    ranking_text = ""
    for sid, rank_info in sorted(
        consensus_ranking.items(), key=lambda x: x[1].get("rank", 99)
    ):
        label = next(
            (s["solver_label"] for s in solutions if s.get("solution_id") == sid),
            sid,
        )
        ranking_text += f"  Rank {rank_info['rank']}: {label}\n"

    formatted_solutions = ""
    for s in solutions:
        formatted_solutions += (
            f"=== Solution: {s['solver_label']} ===\n"
            f"{s.get('solution_text', s.get('solution', ''))}\n\n"
        )

    return (
        "SYSTEM: You are the Boardroom Synthesizer. Produce a UNIFIED "
        "enterprise-grade solution.\n\n"
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


def build_quality_gate_prompt(
    problem_statement: str,
    synthesis: str,
    top_solution: str,
    top_label: str,
) -> str:
    return (
        "SYSTEM: You are the Constitutional Quality Gate. You compare two solutions and "
        "determine whether the synthesis IMPROVED or REGRESSED relative to the best "
        "individual solution.\n\n"
        "Evaluation criteria:\n"
        "1. CORRECTNESS: Is the synthesis at least as correct as the individual solution?\n"
        "2. COMPLETENESS: Does the synthesis cover everything the individual solution did?\n"
        "3. CLARITY: Is the synthesis equally or more clear?\n"
        "4. REGRESSIONS: Did the synthesis introduce any new bugs, omissions, "
        "or hallucinations?\n\n"
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


def build_meta_review_prompt(
    problem_statement: str,
    consensus_ranking: dict[str, Any],
    solutions: list[dict],
    final_output: str,
    success_criteria: list[str],
    quality_gate_result: dict | None = None,
) -> str:
    ranking_text = ""
    for sid, rank_info in sorted(
        consensus_ranking.items(), key=lambda x: x[1].get("rank", 99)
    ):
        label = next(
            (s["solver_label"] for s in solutions if s.get("solution_id") == sid),
            sid,
        )
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
    '  "consensus_approach": "<one-line description of the agreed approach, '
    'if unanimous>",\n'
    '  "divergences": ["<description of any meaningful differences, '
    'if not unanimous>"]\n'
    "}}\n"
    "No markdown, no code fences, no other text.\n\n"
    "PROBLEM:\n{problem_statement}\n\n"
    "SOLUTIONS:\n{solutions_text}"
)
