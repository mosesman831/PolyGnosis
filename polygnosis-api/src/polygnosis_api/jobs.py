"""In-memory async job store for long-running boardroom runs."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from polygnosis_api.schemas import JobStatus


@dataclass
class Job:
    job_id: str
    status: JobStatus
    created_at: str
    updated_at: str
    phase: str | None = None
    detail: str | None = None
    error: str | None = None
    request: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, request: dict[str, Any]) -> Job:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        job = Job(
            job_id=str(uuid.uuid4()),
            status=JobStatus.queued,
            created_at=now,
            updated_at=now,
            request=request,
        )
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        phase: str | None = None,
        detail: str | None = None,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if status is not None:
                job.status = status
            if phase is not None:
                job.phase = phase
            if detail is not None:
                job.detail = detail
            if error is not None:
                job.error = error
            if result is not None:
                job.result = result
            job.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return job
