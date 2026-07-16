"""Persona → tool-class taxonomy (prompt-level in API mode; no agent tools)."""

from __future__ import annotations

import re

PERSONA_TOOLSET_MAP = [
    (
        r"security auditor|security analyst|penetration tester|qa engineer|compliance",
        ["web", "file"],
        "read-only (audit/review)",
    ),
    (
        r"code reviewer|inspector|verifier|validator|critic|auditor|reviewer",
        ["web", "file"],
        "read-only (review/inspect)",
    ),
    (
        r"data engineer|data architect|dba|database engineer|storage engineer|storage architect",
        ["terminal", "file", "web"],
        "write-capable (data/storage)",
    ),
    (
        r"devops engineer|platform engineer|sre|cloud architect|cloud engineer|"
        r"infrastructure engineer|infrastructure architect",
        ["terminal", "file", "web"],
        "write-capable (infrastructure)",
    ),
    (
        r"fullstack|full.stack|full stack",
        ["terminal", "file", "web"],
        "write-capable (full-stack)",
    ),
    (
        r"backend developer|frontend developer|backend engineer|frontend engineer",
        ["terminal", "file", "web"],
        "write-capable (full-stack)",
    ),
    (
        r"solutions architect|system designer|systems architect",
        ["terminal", "file", "web"],
        "write-capable (architect/design)",
    ),
    (
        r"architect|designer",
        ["terminal", "file", "web"],
        "write-capable (architect/design)",
    ),
    (
        r"developer|engineer|programmer|builder|implementer|coder",
        ["terminal", "file", "web"],
        "write-capable (developer)",
    ),
    (
        r"",
        ["web", "file"],
        "read-only (unrecognized persona, conservative default)",
    ),
]


def classify_persona_tools(persona: str) -> tuple[list[str], str]:
    persona_lower = persona.lower()
    for pattern, toolsets, label in PERSONA_TOOLSET_MAP:
        if re.search(pattern, persona_lower):
            return toolsets, label
    return ["web", "file"], "read-only (fallback)"
