"""Tests for InMemoryJobHistoryRepository record, query, and retention."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agent33.automation.cron_models import JobRunRecord
from agent33.automation.job_history_repository import (
    InMemoryJobHistoryRepository,
    JobHistoryRepository,
)


def _make_run(
    job_id: str = "j-1",
    run_id: str = "r-1",
    status: str = "completed",
    offset_seconds: int = 0,
) -> JobRunRecord:
    """Create a JobRunRecord for testing."""
    base = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=offset_seconds)
    return JobRunRecord(
        run_id=run_id,
        job_id=job_id,
        started_at=base,
        ended_at=base + timedelta(seconds=5),
        status=status,
    )


class TestInMemoryJobHistoryRepository:
    """Verify record/query behaviour of the in-memory job history repository."""

    def test_protocol_conformance(self) -> None:
        """InMemoryJobHistoryRepository satisfies the JobHistoryRepository protocol."""
        repo = InMemoryJobHistoryRepository()
        assert isinstance(repo, JobHistoryRepository)

    def test_record_and_query(self) -> None:
        """Recording a run and querying it returns the same record."""
        repo = InMemoryJobHistoryRepository()
        run = _make_run("j-1", "r-1")
        repo.record(run)

        results = repo.query("j-1")
        assert len(results) == 1
        assert results[0].run_id == "r-1"
        assert results[0].job_id == "j-1"
        assert results[0].status == "completed"

    def test_query_returns_most_recent_first(self) -> None:
        """Records are returned newest-first regardless of insertion order."""
        repo = InMemoryJobHistoryRepository()
        repo.record(_make_run("j-1", "r-1", offset_seconds=0))
        repo.record(_make_run("j-1", "r-2", offset_seconds=10))
        repo.record(_make_run("j-1", "r-3", offset_seconds=20))

        results = repo.query("j-1")
        assert [r.run_id for r in results] == ["r-3", "r-2", "r-1"]

    def test_query_empty_job_returns_empty_list(self) -> None:
        """Querying a job with no history returns an empty list."""
        repo = InMemoryJobHistoryRepository()
        assert repo.query("nonexistent") == []

    def test_query_with_status_filter(self) -> None:
        """Status filter narrows results to only matching records."""
        repo = InMemoryJobHistoryRepository()
        repo.record(_make_run("j-1", "r-1", status="completed"))
        repo.record(_make_run("j-1", "r-2", status="failed"))
        repo.record(_make_run("j-1", "r-3", status="completed"))

        completed = repo.query("j-1", status="completed")
        assert len(completed) == 2
        assert all(r.status == "completed" for r in completed)

        failed = repo.query("j-1", status="failed")
        assert len(failed) == 1
        assert failed[0].run_id == "r-2"

    def test_query_with_status_filter_no_match(self) -> None:
        """Status filter returns empty list when no records match."""
        repo = InMemoryJobHistoryRepository()
        repo.record(_make_run("j-1", "r-1", status="completed"))

        results = repo.query("j-1", status="failed")
        assert results == []

    def test_query_with_limit(self) -> None:
        """Limit caps the number of returned records."""
        repo = InMemoryJobHistoryRepository()
        for i in range(10):
            repo.record(_make_run("j-1", f"r-{i}", offset_seconds=i))

        results = repo.query("j-1", limit=3)
        assert len(results) == 3
        # Should be the 3 most recent (reversed order)
        assert results[0].run_id == "r-9"
        assert results[1].run_id == "r-8"
        assert results[2].run_id == "r-7"

    def test_query_with_limit_and_status_filter(self) -> None:
        """Limit applies after status filtering."""
        repo = InMemoryJobHistoryRepository()
        for i in range(6):
            status = "completed" if i % 2 == 0 else "failed"
            repo.record(_make_run("j-1", f"r-{i}", status=status, offset_seconds=i))

        # 3 completed records (r-0, r-2, r-4), limit to 2
        results = repo.query("j-1", limit=2, status="completed")
        assert len(results) == 2
        assert all(r.status == "completed" for r in results)

    def test_all_job_ids_empty(self) -> None:
        """all_job_ids returns empty list on fresh repository."""
        repo = InMemoryJobHistoryRepository()
        assert repo.all_job_ids() == []

    def test_all_job_ids_returns_distinct_ids(self) -> None:
        """all_job_ids lists every job that has at least one run record."""
        repo = InMemoryJobHistoryRepository()
        repo.record(_make_run("j-1", "r-1"))
        repo.record(_make_run("j-2", "r-2"))
        repo.record(_make_run("j-1", "r-3"))  # duplicate job_id

        ids = repo.all_job_ids()
        assert set(ids) == {"j-1", "j-2"}

    def test_retention_limit_evicts_oldest(self) -> None:
        """When max_records_per_job is exceeded, the oldest records are evicted."""
        repo = InMemoryJobHistoryRepository(max_records_per_job=3)

        for i in range(5):
            repo.record(_make_run("j-1", f"r-{i}", offset_seconds=i))

        results = repo.query("j-1")
        # Only the 3 most recent should remain
        assert len(results) == 3
        assert [r.run_id for r in results] == ["r-4", "r-3", "r-2"]

    def test_retention_limit_per_job(self) -> None:
        """Retention limit is enforced per job, not globally."""
        repo = InMemoryJobHistoryRepository(max_records_per_job=2)

        for i in range(4):
            repo.record(_make_run("j-1", f"r-j1-{i}", offset_seconds=i))
        for i in range(3):
            repo.record(_make_run("j-2", f"r-j2-{i}", offset_seconds=i))

        j1_results = repo.query("j-1")
        assert len(j1_results) == 2

        j2_results = repo.query("j-2")
        assert len(j2_results) == 2

    def test_records_isolation_between_jobs(self) -> None:
        """Records for different jobs do not leak into each other's queries."""
        repo = InMemoryJobHistoryRepository()
        repo.record(_make_run("j-1", "r-1"))
        repo.record(_make_run("j-2", "r-2"))

        j1_results = repo.query("j-1")
        assert len(j1_results) == 1
        assert j1_results[0].run_id == "r-1"

        j2_results = repo.query("j-2")
        assert len(j2_results) == 1
        assert j2_results[0].run_id == "r-2"
