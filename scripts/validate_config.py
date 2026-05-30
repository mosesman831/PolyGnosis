#!/usr/bin/env python3
"""Validate PolyGnosis config.yaml (v3 — enterprise)."""
import yaml
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"

REQUIRED_MODEL_KEYS = [
    "orchestrator", "solver_1", "solver_2", "solver_3",
    "critic", "synthesizer", "meta_reviewer", "fallback"
]

REQUIRED_SETTINGS = [
    "solver_count", "solver_timeout_sec", "critic_timeout_sec",
    "synthesizer_timeout_sec", "meta_reviewer_timeout_sec",
    "orchestrator_timeout_sec", "max_debate_rounds",
    "min_solvers_for_quorum", "artifacts_dir",
    "scoring_algorithm", "rrf_k", "quality_gate_enabled",
    "early_resolution_enabled"
]

REQUIRED_PROVIDER_KEYS = [
    "orchestrator", "solver_1", "solver_2", "solver_3",
    "critic", "synthesizer", "meta_reviewer", "fallback"
]

VALID_ALGORITHMS = {"rrf", "borda", "hybrid"}


def main():
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Config not found: {CONFIG_PATH}")

    cfg = yaml.safe_load(CONFIG_PATH.read_text())

    errors = []
    warnings = []

    # Check models section
    models = cfg.get("models", {})
    missing_models = [k for k in REQUIRED_MODEL_KEYS if not models.get(k)]
    if missing_models:
        errors.append(f"Missing model aliases in models: {', '.join(missing_models)}")

    # Check solver_models list
    solver_list = cfg.get("solver_models", [])
    solver_count = cfg.get("settings", {}).get("solver_count", 3)
    if solver_list:
        non_empty = [m for m in solver_list if m]
        if len(non_empty) < solver_count:
            warnings.append(
                f"solver_models has {len(non_empty)} non-empty entries but solver_count={solver_count}. "
                "Solver_N keys will be used as fallback."
            )

    # Check settings
    settings = cfg.get("settings", {})
    missing_settings = [k for k in REQUIRED_SETTINGS if k not in settings]
    if missing_settings:
        errors.append(f"Missing settings keys: {', '.join(missing_settings)}")

    # Check providers (optional but keys must exist)
    providers = cfg.get("providers", {})
    if providers:
        missing_prov = [k for k in REQUIRED_PROVIDER_KEYS if k not in providers]
        if missing_prov:
            errors.append(f"Missing provider keys: {', '.join(missing_prov)}")

    # Validate values
    if settings:
        sc = settings.get("solver_count", 3)
        if not (2 <= sc <= 5):
            errors.append(f"solver_count={sc} must be between 2 and 5")

        mq = settings.get("min_solvers_for_quorum", 2)
        if mq < 1 or mq > sc:
            errors.append(f"min_solvers_for_quorum={mq} must be between 1 and solver_count ({sc})")

        algo = settings.get("scoring_algorithm", "hybrid")
        if algo not in VALID_ALGORITHMS:
            errors.append(f"scoring_algorithm='{algo}' must be one of: {', '.join(VALID_ALGORITHMS)}")

        rrf_k = settings.get("rrf_k", 60)
        if rrf_k <= 0:
            errors.append(f"rrf_k={rrf_k} must be positive. Standard value is 60.")

        dr = settings.get("max_debate_rounds", 2)
        if dr < 1 or dr > 5:
            errors.append(f"max_debate_rounds={dr} must be between 1 and 5")

    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"  - {w}")
        print()

    if errors:
        raise SystemExit("\n".join(errors))

    print("PolyGnosis config.yaml OK")
    print(f"  Scoring: {settings.get('scoring_algorithm', '?')} (RRF k={settings.get('rrf_k', '?')})")
    print(f"  Quality Gate: {'enabled' if settings.get('quality_gate_enabled') else 'disabled'}")
    print(f"  Early Resolution: {'enabled' if settings.get('early_resolution_enabled') else 'disabled'}")
    solver_labels = [chr(65 + i) for i in range(solver_count)]
    print(f"  Solvers: {', '.join(solver_labels)} ({solver_count} models)")
    print(f"  Debate rounds: {settings.get('max_debate_rounds', 2)}")
    print(f"  Quorum: {settings.get('min_solvers_for_quorum', 2)} minimum")
    print(f"  Artifacts: {settings.get('artifacts_dir', '.hermes/plans/polybrain/boardroom')}")


if __name__ == "__main__":
    main()
