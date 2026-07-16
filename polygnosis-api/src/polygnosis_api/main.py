"""PolyGnosis API — FastAPI entrypoint."""

from __future__ import annotations

import copy
import logging
import threading
from pathlib import Path

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException

from polygnosis_api.config import Settings, load_boardroom_config
from polygnosis_api.jobs import JobStore
from polygnosis_api.llm import LLMClient
from polygnosis_api.pipeline import BoardroomPipeline
from polygnosis_api.reflexion import ReflexionBuffer
from polygnosis_api.schemas import (
    BoardroomCreateResponse,
    BoardroomJobResponse,
    BoardroomRequest,
    BoardroomResult,
    HealthResponse,
    JobStatus,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("polygnosis_api")

VERSION = "1.0.0"
settings = Settings()
store = JobStore()

app = FastAPI(
    title="PolyGnosis API",
    description=(
        "Adversarial multi-model consensus protocol as a public HTTP API. "
        "Full PolyGnosis v3 workflow: orchestrate → parallel solve → early resolution → "
        "critique → RRF+Borda scoring → synthesis → quality gate → meta-review."
    ),
    version=VERSION,
)


def _job_response(job) -> BoardroomJobResponse:
    result = None
    if job.result:
        result = BoardroomResult(**job.result)
    return BoardroomJobResponse(
        job_id=job.job_id,
        status=job.status,
        phase=job.phase,
        detail=job.detail,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
        result=result,
    )


def _run_boardroom(job_id: str, request: BoardroomRequest) -> None:
    store.update(job_id, status=JobStatus.running, phase="starting", detail="Loading config")
    try:
        cfg = copy.deepcopy(load_boardroom_config(settings.config_path))
        settings_block = cfg.setdefault("settings", {})
        if request.scoring_algorithm is not None:
            settings_block["scoring_algorithm"] = request.scoring_algorithm.value
        if request.solver_count is not None:
            settings_block["solver_count"] = request.solver_count
        if request.early_resolution is not None:
            settings_block["early_resolution_enabled"] = request.early_resolution
        if request.quality_gate is not None:
            settings_block["quality_gate_enabled"] = request.quality_gate
        if request.max_debate_rounds is not None:
            settings_block["max_debate_rounds"] = request.max_debate_rounds

        artifacts = Path(settings.artifacts_dir)
        artifacts.mkdir(parents=True, exist_ok=True)

        pipeline = BoardroomPipeline(
            cfg=cfg,
            llm=LLMClient(settings),
            reflexion=ReflexionBuffer(settings.corrections_buffer),
            artifacts_root=artifacts,
        )

        def on_progress(phase: str, detail: str | None) -> None:
            store.update(job_id, phase=phase, detail=detail)

        result = pipeline.run(
            request.objective, job_id=job_id, on_progress=on_progress
        )
        store.update(
            job_id,
            status=JobStatus.completed,
            phase="complete",
            detail=None,
            result=result,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Boardroom job %s failed", job_id)
        store.update(
            job_id,
            status=JobStatus.failed,
            phase="failed",
            error=str(exc),
        )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=VERSION)


@app.post("/v1/boardroom", response_model=BoardroomCreateResponse, status_code=202)
def create_boardroom(
    body: BoardroomRequest, background_tasks: BackgroundTasks
) -> BoardroomCreateResponse:
    job = store.create(body.model_dump())
    # Use a thread so long runs don't block the event loop / BackgroundTasks lifetime quirks
    threading.Thread(
        target=_run_boardroom, args=(job.job_id, body), daemon=True
    ).start()
    return BoardroomCreateResponse(
        job_id=job.job_id,
        status=JobStatus.queued,
        poll_url=f"/v1/boardroom/{job.job_id}",
    )


@app.get("/v1/boardroom/{job_id}", response_model=BoardroomJobResponse)
def get_boardroom(job_id: str) -> BoardroomJobResponse:
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_response(job)


def cli() -> None:
    uvicorn.run(
        "polygnosis_api.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    cli()
