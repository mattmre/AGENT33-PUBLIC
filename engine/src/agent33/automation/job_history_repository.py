"""Repository abstraction for job run history.

Provides a protocol-based repository pattern that supports both in-memory
and database-backed implementations for multi-replica safety.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agent33.automation.cron_models import JobRunRecord


@runtime_checkable
class JobHistoryRepository(Protocol):
    """Protocol for job run history storage."""

    def record(self, run: JobRunRecord) -> None:
        """Store a job run record."""
        ...

    def query(
        self,
        job_id: str,
        limit: int = 50,
        status: str | None = None,
    ) -> list[JobRunRecord]:
        """Return run records for a job, optionally filtered by status.

        Results are returned most-recent-first.
        """
        ...

    def all_job_ids(self) -> list[str]:
        """Return all job IDs that have run history."""
        ...


class InMemoryJobHistoryRepository:
    """In-memory implementation wrapping the existing JobHistoryStore logic.

    Preserves the per-job retention limit and most-recent-first query ordering
    from the original ``JobHistoryStore`` in ``cron_models.py``.
    """

    def __init__(self, max_records_per_job: int = 100) -> None:
        self._max_records = max_records_per_job
        self._records: dict[str, list[JobRunRecord]] = defaultdict(list)

    def record(self, run: JobRunRecord) -> None:
        """Store a run record, evicting the oldest when the limit is exceeded."""
        records = self._records[run.job_id]
        records.append(run)
        if len(records) > self._max_records:
            self._records[run.job_id] = records[-self._max_records :]

    def query(
        self,
        job_id: str,
        limit: int = 50,
        status: str | None = None,
    ) -> list[JobRunRecord]:
        """Return run records for a job, optionally filtered by status.

        Results are returned most-recent-first.
        """
        records = self._records.get(job_id, [])
        if status is not None:
            records = [r for r in records if r.status == status]
        # Most recent first
        return list(reversed(records))[:limit]

    def all_job_ids(self) -> list[str]:
        """Return all job IDs that have run history."""
        return list(self._records.keys())


_repository: JobHistoryRepository | None = None


def get_job_history_repository() -> JobHistoryRepository:
    """Get the current job history repository. Creates in-memory default if not set."""
    global _repository  # noqa: PLW0603
    if _repository is None:
        _repository = InMemoryJobHistoryRepository()
    return _repository


def set_job_history_repository(repo: JobHistoryRepository) -> None:
    """Set the job history repository. Called during app lifespan."""
    global _repository  # noqa: PLW0603
    _repository = repo
