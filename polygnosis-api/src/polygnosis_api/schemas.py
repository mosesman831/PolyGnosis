"""Pydantic request/response schemas for the PolyGnosis API."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ScoringAlgorithm(str, Enum):
    rrf = "rrf"
    borda = "borda"
    hybrid = "hybrid"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class BoardroomRequest(BaseModel):
    objective: str = Field(..., min_length=1, description="High-stakes problem to solve")
    scoring_algorithm: ScoringAlgorithm | None = Field(
        default=None,
        description="Override config: rrf | borda | hybrid",
    )
    solver_count: int | None = Field(default=None, ge=2, le=5)
    early_resolution: bool | None = None
    quality_gate: bool | None = None
    max_debate_rounds: int | None = Field(default=None, ge=1, le=5)


class BoardroomCreateResponse(BaseModel):
    job_id: str
    status: JobStatus
    poll_url: str


class SolverTrailItem(BaseModel):
    solution_id: str
    solver: str
    model: str | None = None
    tool_class: str | None = None
    rank: int | None = None
    rrf_score: float | None = None
    borda_score: float | None = None
    avg_rank: float | None = None
    critic_score: int | float | None = None
    critic_grade: str | None = None
    solution: str | None = None


class BoardroomResult(BaseModel):
    job_id: str
    objective: str
    domain: str | None = None
    problem_statement: str | None = None
    success_criteria: list[str] = []
    personas: list[str] = []
    early_resolution: bool = False
    scoring_algorithm: str = "hybrid"
    consensus_ranking: dict[str, Any] = {}
    quality_gate: dict[str, Any] | None = None
    final_output: str | None = None
    meta_review: str | None = None
    trail: list[SolverTrailItem] = []
    artifacts_dir: str | None = None
    reflexion_buffer_size: int = 0


class BoardroomJobResponse(BaseModel):
    job_id: str
    status: JobStatus
    phase: str | None = None
    detail: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str
    result: BoardroomResult | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    protocol: str = "polygnosis-v3"
