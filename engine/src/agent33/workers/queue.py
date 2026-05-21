"""In-memory worker queue with leases and retry/dead-letter state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class WorkerJobStatus(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


class WorkerJob(BaseModel):
    job_id: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: WorkerJobStatus = WorkerJobStatus.QUEUED
    attempts: int = 0
    max_attempts: int = 3
    owner: str = ""
    leased_until: datetime | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class WorkerQueue:
    def __init__(self) -> None:
        self._jobs: dict[str, WorkerJob] = {}

    def enqueue(self, job: WorkerJob) -> WorkerJob:
        self._jobs[job.job_id] = job
        return job

    def lease(self, *, owner: str, ttl_seconds: int = 60) -> WorkerJob | None:
        now = datetime.now(UTC)
        for job in self._jobs.values():
            if job.status not in {WorkerJobStatus.QUEUED, WorkerJobStatus.LEASED}:
                continue
            if (
                job.status == WorkerJobStatus.LEASED
                and job.leased_until
                and job.leased_until > now
            ):
                continue
            job.status = WorkerJobStatus.LEASED
            job.owner = owner
            job.attempts += 1
            job.leased_until = now + timedelta(seconds=max(1, ttl_seconds))
            return job
        return None

    def complete(self, job_id: str, result: dict[str, Any] | None = None) -> WorkerJob | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        job.status = WorkerJobStatus.COMPLETED
        job.result = result or {}
        return job

    def fail(self, job_id: str, error: str) -> WorkerJob | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        job.error = error
        job.status = (
            WorkerJobStatus.DEAD_LETTER
            if job.attempts >= job.max_attempts
            else WorkerJobStatus.QUEUED
        )
        return job

    def cancel(self, job_id: str) -> WorkerJob | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        job.status = WorkerJobStatus.CANCELLED
        return job

    def list_jobs(self) -> list[WorkerJob]:
        return list(self._jobs.values())
