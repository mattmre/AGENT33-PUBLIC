"""Repository abstraction for scheduled workflow jobs.

Provides a protocol-based repository pattern that supports both in-memory
and database-backed implementations for multi-replica safety.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agent33.automation.scheduler import ScheduledJob


@runtime_checkable
class SchedulerJobRepository(Protocol):
    """Protocol for scheduled job storage."""

    def get_job(self, job_id: str) -> ScheduledJob | None:
        """Get a scheduled job by ID."""
        ...

    def list_jobs(self) -> list[ScheduledJob]:
        """List all scheduled jobs."""
        ...

    def add_job(self, job: ScheduledJob) -> None:
        """Store a scheduled job."""
        ...

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job by ID. Returns True if found and removed."""
        ...


class InMemorySchedulerJobRepository:
    """In-memory implementation preserving current behavior.

    Exposes ``_jobs`` dict directly for backwards compatibility with
    existing tests that may manipulate it.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, ScheduledJob] = {}

    def get_job(self, job_id: str) -> ScheduledJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[ScheduledJob]:
        return list(self._jobs.values())

    def add_job(self, job: ScheduledJob) -> None:
        self._jobs[job.job_id] = job

    def remove_job(self, job_id: str) -> bool:
        return self._jobs.pop(job_id, None) is not None


_repository: SchedulerJobRepository | None = None


def get_scheduler_job_repository() -> SchedulerJobRepository:
    """Get the current scheduler job repository. Creates in-memory default if not set."""
    global _repository  # noqa: PLW0603
    if _repository is None:
        _repository = InMemorySchedulerJobRepository()
    return _repository


def set_scheduler_job_repository(repo: SchedulerJobRepository) -> None:
    """Set the scheduler job repository. Called during app lifespan."""
    global _repository  # noqa: PLW0603
    _repository = repo
