"""Reflexion corrections buffer — persist severe critique findings across runs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class ReflexionBuffer:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> list[dict[str, Any]]:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text())
                return data.get("corrections", []) if isinstance(data, dict) else []
        except (json.JSONDecodeError, OSError):
            pass
        return []

    def save(self, corrections: list[dict[str, Any]]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "corrections": corrections,
                        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    },
                    indent=2,
                )
            )
        except OSError:
            pass

    def ingest_critique(
        self, critique: dict[str, Any], solver_label: str, round_num: int
    ) -> list[dict[str, Any]]:
        existing = self.load()
        new_entries: list[dict[str, Any]] = []

        for bug in critique.get("critical_bugs", []) or []:
            severity = str(bug.get("severity", "")).upper()
            if severity in ("CRITICAL", "HIGH"):
                new_entries.append(
                    {
                        "source": f"boardroom_critique_r{round_num}",
                        "solver": solver_label,
                        "severity": severity,
                        "description": bug.get("description", ""),
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    }
                )

        for hal in critique.get("hallucinations_found", []) or []:
            new_entries.append(
                {
                    "source": f"boardroom_critique_r{round_num}",
                    "solver": solver_label,
                    "severity": "HALLUCINATION",
                    "description": (
                        f"Claimed: {hal.get('claimed', '?')} — "
                        f"Reality: {hal.get('reality', '?')}"
                    ),
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
            )

        if not new_entries:
            return existing

        combined = existing + new_entries
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for c in combined:
            key = c["description"].strip().lower()[:200]
            if key not in seen:
                seen.add(key)
                deduped.append(c)
        self.save(deduped)
        return deduped

    def injection(self) -> str:
        corrections = self.load()
        if not corrections:
            return ""
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
