"""Full PolyGnosis boardroom pipeline (phases 0–6) for the HTTP API."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from polygnosis_api.consensus import compute_consensus_ranking
from polygnosis_api.config import get_role_model, get_solver_model_name
from polygnosis_api.llm import LLMClient, extract_json
from polygnosis_api.personas import classify_persona_tools
from polygnosis_api.prompts import (
    EARLY_RESOLUTION_PROMPT,
    build_critique_prompt,
    build_meta_review_prompt,
    build_orchestrator_prompt,
    build_quality_gate_prompt,
    build_revision_prompt,
    build_scoring_prompt,
    build_solver_prompt,
    build_synthesis_prompt,
)
from polygnosis_api.reflexion import ReflexionBuffer

logger = logging.getLogger("polygnosis_api.pipeline")

ProgressCallback = Callable[[str, str | None], None]


class BoardroomPipeline:
    """Runs the full adversarial multi-model consensus protocol."""

    def __init__(
        self,
        cfg: dict[str, Any],
        llm: LLMClient,
        reflexion: ReflexionBuffer,
        artifacts_root: Path,
    ):
        self.cfg = cfg
        self.llm = llm
        self.reflexion = reflexion
        self.artifacts_root = artifacts_root

    def run(
        self,
        objective: str,
        *,
        job_id: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        settings = self.cfg.get("settings", {})
        run_id = job_id or time.strftime("%Y%m%d_%H%M%S")
        run_dir = self.artifacts_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        def progress(phase: str, detail: str | None = None) -> None:
            logger.info("phase=%s detail=%s", phase, detail)
            if on_progress:
                on_progress(phase, detail)

        progress("orchestrate", "Building problem statement + personas")
        problem_statement, success_criteria, personas, domain = self._orchestrate(
            objective, run_dir
        )

        progress("solve", f"Parallel solve with {len(personas)} personas")
        solver_results = self._parallel_solve(problem_statement, personas, run_dir)

        progress("early_resolution", "Quorum vote")
        early_resolved, consensus_ranking, scorer_solutions = self._early_resolution(
            problem_statement, solver_results, run_dir
        )

        critique_data: dict[int, Any] = {}
        scoring_json: dict[str, Any] = {}

        if early_resolved:
            scoring_json = {
                "_early_resolution": True,
                "_note": "Critique + scoring bypassed",
            }
            progress("early_resolution", "Unanimous — skipping critique + scoring")
        else:
            progress("critique", "Adversarial critique + reflexion")
            critique_data = self._critique(problem_statement, solver_results, run_dir)
            progress("scoring", "LLM axes → RRF/Borda/hybrid ranking")
            scoring_json, consensus_ranking, scorer_solutions = self._scoring(
                problem_statement, solver_results, critique_data, run_dir
            )

        assert consensus_ranking is not None
        assert scorer_solutions is not None

        progress("synthesis", "Meta-synthesis")
        synthesis = self._synthesis(
            problem_statement,
            solver_results,
            consensus_ranking,
            scorer_solutions,
            success_criteria,
            run_dir,
        )

        progress("quality_gate", "Constitutional quality gate")
        quality_gate_result, final_output = self._quality_gate(
            problem_statement, synthesis, consensus_ranking, solver_results, run_dir
        )
        (run_dir / "final_output.md").write_text(final_output)

        progress("meta_review", "Explaining consensus")
        meta_review = self._meta_review(
            problem_statement,
            consensus_ranking,
            scorer_solutions,
            final_output,
            success_criteria,
            quality_gate_result,
            run_dir,
        )

        progress("complete", None)

        trail = []
        for sid in sorted(solver_results.keys()):
            sol = solver_results[sid]
            sid_key = f"s{sid}"
            rank_info = consensus_ranking.get(sid_key, {})
            crit = critique_data.get(sid, {})
            trail.append(
                {
                    "solution_id": sid_key,
                    "solver": sol["persona"],
                    "model": sol.get("model"),
                    "tool_class": sol.get("tool_class"),
                    "rank": rank_info.get("rank"),
                    "rrf_score": rank_info.get("rrf_score"),
                    "borda_score": rank_info.get("borda_score"),
                    "avg_rank": rank_info.get("avg_rank"),
                    "critic_score": crit.get("score"),
                    "critic_grade": crit.get("overall_grade"),
                    "solution": sol["solution"],
                }
            )

        return {
            "job_id": run_id,
            "objective": objective,
            "domain": domain,
            "problem_statement": problem_statement,
            "success_criteria": success_criteria,
            "personas": personas,
            "early_resolution": bool(early_resolved),
            "scoring_algorithm": settings.get("scoring_algorithm", "hybrid"),
            "consensus_ranking": consensus_ranking,
            "scoring": scoring_json,
            "quality_gate": quality_gate_result,
            "final_output": final_output,
            "meta_review": meta_review,
            "trail": trail,
            "artifacts_dir": str(run_dir),
            "reflexion_buffer_size": len(self.reflexion.load()),
        }

    # ── phases ─────────────────────────────────────────────────────────────

    def _orchestrate(
        self, objective: str, run_dir: Path
    ) -> tuple[str, list[str], list[str], str]:
        settings = self.cfg.get("settings", {})
        model = get_role_model(self.cfg, "orchestrator")
        out = self.llm.complete(
            build_orchestrator_prompt(objective),
            model,
            timeout=float(settings.get("orchestrator_timeout_sec", 120)),
            label="orchestrator",
        )
        (run_dir / "orchestrator_raw.txt").write_text(out)

        try:
            orch_json = json.loads(extract_json(out)) if out else {}
        except json.JSONDecodeError:
            orch_json = {}

        problem_statement = orch_json.get("problem_statement", objective)
        success_criteria = orch_json.get(
            "success_criteria", ["Correctness", "Completeness", "Robustness"]
        )
        personas = orch_json.get("personas", [])
        domain = orch_json.get("domain", "general")

        if not personas:
            solver_count = min(int(settings.get("solver_count", 3)), 5)
            personas = [
                f"Senior {str(domain).title()} Expert {chr(65 + i)}"
                for i in range(solver_count)
            ]

        (run_dir / "orchestrator.json").write_text(json.dumps(orch_json, indent=2))
        return problem_statement, success_criteria, personas, domain

    def _parallel_solve(
        self, problem_statement: str, personas: list[str], run_dir: Path
    ) -> dict[int, dict[str, Any]]:
        settings = self.cfg.get("settings", {})
        solver_count = min(int(settings.get("solver_count", 3)), 5)
        timeout = float(settings.get("solver_timeout_sec", 600))
        min_quorum = int(settings.get("min_solvers_for_quorum", 2))
        reflexion_context = self.reflexion.injection()

        solver_results: dict[int, dict[str, Any]] = {}
        dead: list[tuple[int, str]] = []

        def execute(idx: int):
            model = get_solver_model_name(self.cfg, idx)
            if not model:
                return idx, None, "no model configured"
            persona = personas[idx] if idx < len(personas) else f"Solver-{chr(65 + idx)}"
            toolsets, tool_class = classify_persona_tools(persona)
            prompt = build_solver_prompt(
                problem_statement, persona, reflexion_context, toolsets, tool_class
            )
            text = self.llm.complete(
                prompt, model, timeout=timeout, label=f"solver-{chr(65 + idx)}"
            )
            if not text:
                return idx, None, "empty response"
            return (
                idx,
                {
                    "persona": persona,
                    "solution_id": f"s{idx}",
                    "model": model,
                    "solution": text,
                    "toolsets": toolsets,
                    "tool_class": tool_class,
                },
                None,
            )

        with ThreadPoolExecutor(max_workers=solver_count) as ex:
            futures = {ex.submit(execute, i): i for i in range(solver_count)}
            for f in as_completed(futures):
                idx, result, error = f.result()
                if error or result is None:
                    dead.append((idx, error or "unknown"))
                else:
                    solver_results[idx] = result
                    slug = result["persona"].replace(" ", "_").replace("/", "-")[:30]
                    (run_dir / f"solver_{chr(65 + idx)}_{slug}_initial.md").write_text(
                        result["solution"]
                    )

        if len(solver_results) < min_quorum:
            raise RuntimeError(
                f"Insufficient solvers: {len(solver_results)} alive, "
                f"{min_quorum} required. Dead: {dead}"
            )
        return solver_results

    def _early_resolution(
        self,
        problem_statement: str,
        solver_results: dict[int, dict[str, Any]],
        run_dir: Path,
    ) -> tuple[bool, dict[str, Any] | None, list[dict] | None]:
        settings = self.cfg.get("settings", {})
        if not settings.get("early_resolution_enabled", True):
            return False, None, None
        if len(solver_results) < 3:
            return False, None, None

        parts = []
        for sid in sorted(solver_results.keys()):
            sol = solver_results[sid]
            parts.append(
                f"=== {sol['persona']} (solver-{chr(65 + sid)}) ===\n"
                f"{sol['solution'][:3000]}\n"
            )
        prompt = EARLY_RESOLUTION_PROMPT.format(
            problem_statement=problem_statement,
            solutions_text="\n\n".join(parts),
        )
        model = get_role_model(self.cfg, "orchestrator")
        out = self.llm.complete(
            prompt,
            model,
            timeout=float(settings.get("orchestrator_timeout_sec", 120)),
            label="quorum-judge",
        )
        (run_dir / "early_resolution_raw.txt").write_text(out)
        try:
            verdict = json.loads(extract_json(out)) if out else {}
        except json.JSONDecodeError:
            verdict = {
                "unanimous": False,
                "confidence": 0.0,
                "divergences": ["Judge returned non-JSON"],
            }
        (run_dir / "early_resolution.json").write_text(json.dumps(verdict, indent=2))

        if verdict.get("unanimous") and float(verdict.get("confidence", 0)) >= 0.7:
            consensus_ranking = {
                f"s{sid}": {
                    "rank": 1,
                    "note": "unanimous consensus — critique bypassed",
                }
                for sid in sorted(solver_results.keys())
            }
            scorer_solutions = [
                {
                    "solution_id": f"s{sid}",
                    "solver_label": solver_results[sid]["persona"],
                    "solution": solver_results[sid]["solution"],
                    "critic_score": 100,
                    "critic_grade": "PASS",
                    "critique_summary": "Early resolution: unanimous consensus.",
                }
                for sid in sorted(solver_results.keys())
            ]
            return True, consensus_ranking, scorer_solutions
        return False, None, None

    def _critique(
        self,
        problem_statement: str,
        solver_results: dict[int, dict[str, Any]],
        run_dir: Path,
    ) -> dict[int, Any]:
        settings = self.cfg.get("settings", {})
        debate_rounds = int(settings.get("max_debate_rounds", 2))
        critic_timeout = float(settings.get("critic_timeout_sec", 600))
        solver_timeout = float(settings.get("solver_timeout_sec", 600))
        critic_model = get_role_model(self.cfg, "critic")
        critique_data: dict[int, Any] = {}
        alive = len(solver_results)

        for round_num in range(debate_rounds):

            def execute_critique(sid: int, sol_data: dict):
                prompt = build_critique_prompt(
                    problem_statement,
                    sol_data["solution"],
                    sol_data["persona"],
                    f"s{sid}",
                )
                out = self.llm.complete(
                    prompt,
                    critic_model,
                    timeout=critic_timeout,
                    label=f"critic-{chr(65 + sid)}",
                )
                if not out:
                    return sid, None
                try:
                    crit = json.loads(extract_json(out))
                except json.JSONDecodeError:
                    crit = {
                        "solution_id": f"s{sid}",
                        "solver": sol_data["persona"],
                        "overall_grade": "PASS_WITH_ISSUES",
                        "score": 50,
                        "raw_text": out,
                    }
                return sid, crit

            with ThreadPoolExecutor(max_workers=alive) as ex:
                futs = {
                    ex.submit(execute_critique, sid, solver_results[sid]): sid
                    for sid in sorted(solver_results.keys())
                }
                for f in as_completed(futs):
                    sid, crit = f.result()
                    if crit:
                        critique_data[sid] = crit
                        (
                            run_dir / f"critique_{chr(65 + sid)}_r{round_num + 1}.json"
                        ).write_text(json.dumps(crit, indent=2))
                        self.reflexion.ingest_critique(
                            crit, solver_results[sid]["persona"], round_num + 1
                        )

            if round_num < debate_rounds - 1:

                def execute_revision(sid: int, sol_data: dict):
                    prompt = build_revision_prompt(
                        problem_statement,
                        sol_data["solution"],
                        json.dumps(critique_data.get(sid, {}), indent=2),
                        sol_data["persona"],
                    )
                    model = get_solver_model_name(self.cfg, sid)
                    out = self.llm.complete(
                        prompt,
                        model,
                        timeout=solver_timeout,
                        label=f"revision-{chr(65 + sid)}",
                    )
                    return sid, out if out else sol_data["solution"]

                with ThreadPoolExecutor(max_workers=alive) as ex:
                    futs = {
                        ex.submit(execute_revision, sid, solver_results[sid]): sid
                        for sid in sorted(solver_results.keys())
                    }
                    for f in as_completed(futs):
                        sid, revised = f.result()
                        solver_results[sid]["solution"] = revised
                        (run_dir / f"solver_{chr(65 + sid)}_r{round_num + 2}.md").write_text(
                            revised
                        )

        return critique_data

    def _scoring(
        self,
        problem_statement: str,
        solver_results: dict[int, dict[str, Any]],
        critique_data: dict[int, Any],
        run_dir: Path,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict]]:
        settings = self.cfg.get("settings", {})
        algorithm = settings.get("scoring_algorithm", "hybrid")
        rrf_k = int(settings.get("rrf_k", 60))

        scorer_solutions = []
        for sid in sorted(solver_results.keys()):
            sol = solver_results[sid]
            crit = critique_data.get(sid, {})
            scorer_solutions.append(
                {
                    "solution_id": f"s{sid}",
                    "solver_label": sol["persona"],
                    "solution": sol["solution"],
                    "critic_score": crit.get("score", "N/A"),
                    "critic_grade": crit.get("overall_grade", "N/A"),
                    "critique_summary": (
                        json.dumps(crit, indent=2) if isinstance(crit, dict) else str(crit)
                    ),
                }
            )

        model = get_role_model(self.cfg, "synthesizer")
        out = self.llm.complete(
            build_scoring_prompt(problem_statement, scorer_solutions),
            model,
            timeout=float(settings.get("synthesizer_timeout_sec", 300)),
            label="scorer",
        )
        try:
            scoring_json = json.loads(extract_json(out)) if out else {}
        except json.JSONDecodeError:
            scoring_json = {"raw_text": out}

        (run_dir / "scoring_raw.json").write_text(json.dumps(scoring_json, indent=2))
        consensus_ranking = compute_consensus_ranking(
            scoring_json, algorithm=algorithm, k=rrf_k
        )
        scoring_json["_consensus_algorithm"] = algorithm
        scoring_json["_consensus_ranking"] = consensus_ranking
        (run_dir / "scoring.json").write_text(json.dumps(scoring_json, indent=2))
        return scoring_json, consensus_ranking, scorer_solutions

    def _synthesis(
        self,
        problem_statement: str,
        solver_results: dict[int, dict[str, Any]],
        consensus_ranking: dict[str, Any],
        scorer_solutions: list[dict],
        success_criteria: list[str],
        run_dir: Path,
    ) -> str:
        settings = self.cfg.get("settings", {})
        solutions_for_prompt = [
            {
                "solution_id": f"s{sid}",
                "solver_label": solver_results[sid]["persona"],
                "solution_text": solver_results[sid]["solution"],
                "solution": solver_results[sid]["solution"],
            }
            for sid in sorted(solver_results.keys())
        ]
        model = get_role_model(self.cfg, "synthesizer")
        synthesis = self.llm.complete(
            build_synthesis_prompt(
                problem_statement,
                solutions_for_prompt,
                consensus_ranking,
                success_criteria,
            ),
            model,
            timeout=float(settings.get("synthesizer_timeout_sec", 300)),
            label="synthesizer",
        )
        (run_dir / "synthesis_raw.md").write_text(synthesis)
        return synthesis

    def _quality_gate(
        self,
        problem_statement: str,
        synthesis: str,
        consensus_ranking: dict[str, Any],
        solver_results: dict[int, dict[str, Any]],
        run_dir: Path,
    ) -> tuple[dict[str, Any] | None, str]:
        settings = self.cfg.get("settings", {})
        if not settings.get("quality_gate_enabled", True):
            return None, synthesis

        top_sid = None
        best_rank = 999
        for sid, rank_info in consensus_ranking.items():
            if rank_info.get("rank", 999) < best_rank:
                best_rank = rank_info["rank"]
                top_sid = sid

        if not top_sid:
            return None, synthesis
        try:
            top_idx = int(top_sid[1:])
        except (ValueError, IndexError):
            return None, synthesis
        if top_idx not in solver_results:
            return None, synthesis

        top_solution = solver_results[top_idx]["solution"]
        top_label = solver_results[top_idx]["persona"]
        model = get_role_model(self.cfg, "synthesizer")
        out = self.llm.complete(
            build_quality_gate_prompt(
                problem_statement, synthesis, top_solution, top_label
            ),
            model,
            timeout=float(settings.get("synthesizer_timeout_sec", 300)),
            label="quality-gate",
        )
        try:
            gate_result = json.loads(extract_json(out)) if out else {}
        except json.JSONDecodeError:
            gate_result = {
                "verdict": "PASS",
                "reasoning": "Quality gate returned non-JSON — defaulting to PASS.",
            }
        (run_dir / "quality_gate.json").write_text(json.dumps(gate_result, indent=2))

        if gate_result.get("verdict") == "FAIL":
            return gate_result, top_solution
        return gate_result, synthesis

    def _meta_review(
        self,
        problem_statement: str,
        consensus_ranking: dict[str, Any],
        scorer_solutions: list[dict],
        final_output: str,
        success_criteria: list[str],
        quality_gate_result: dict | None,
        run_dir: Path,
    ) -> str:
        settings = self.cfg.get("settings", {})
        model = get_role_model(self.cfg, "meta_reviewer")
        review = self.llm.complete(
            build_meta_review_prompt(
                problem_statement,
                consensus_ranking,
                scorer_solutions,
                final_output,
                success_criteria,
                quality_gate_result,
            ),
            model,
            timeout=float(settings.get("meta_reviewer_timeout_sec", 180)),
            label="meta-reviewer",
        )
        (run_dir / "meta_review.md").write_text(review)
        return review
