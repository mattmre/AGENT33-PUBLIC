"""Tests for InMemorySchedulerJobRepository CRUD operations."""

from __future__ import annotations

from agent33.automation.scheduler import ScheduledJob
from agent33.automation.scheduler_repository import (
    InMemorySchedulerJobRepository,
    SchedulerJobRepository,
)


def _make_job(job_id: str = "j-1", workflow_name: str = "wf-a") -> ScheduledJob:
    """Create a ScheduledJob for testing."""
    return ScheduledJob(
        job_id=job_id,
        workflow_name=workflow_name,
        schedule_type="cron",
        schedule_expr="0 12 * * *",
        inputs={"key": "value"},
    )


class TestInMemorySchedulerJobRepository:
    """Verify CRUD behaviour of the in-memory scheduler job repository."""

    def test_protocol_conformance(self) -> None:
        """InMemorySchedulerJobRepository satisfies the SchedulerJobRepository protocol."""
        repo = InMemorySchedulerJobRepository()
        assert isinstance(repo, SchedulerJobRepository)

    def test_add_and_get_job(self) -> None:
        """Adding a job then retrieving it by ID returns the same object."""
        repo = InMemorySchedulerJobRepository()
        job = _make_job("j-1")
        repo.add_job(job)

        retrieved = repo.get_job("j-1")
        assert retrieved is not None
        assert retrieved.job_id == "j-1"
        assert retrieved.workflow_name == "wf-a"
        assert retrieved.schedule_type == "cron"
        assert retrieved.schedule_expr == "0 12 * * *"
        assert retrieved.inputs == {"key": "value"}

    def test_get_nonexistent_job_returns_none(self) -> None:
        """Getting a job that was never added returns None."""
        repo = InMemorySchedulerJobRepository()
        assert repo.get_job("does-not-exist") is None

    def test_list_jobs_empty(self) -> None:
        """Listing jobs on a fresh repository returns an empty list."""
        repo = InMemorySchedulerJobRepository()
        assert repo.list_jobs() == []

    def test_list_jobs_returns_all(self) -> None:
        """Listing jobs returns every added job."""
        repo = InMemorySchedulerJobRepository()
        j1 = _make_job("j-1", "wf-a")
        j2 = _make_job("j-2", "wf-b")
        repo.add_job(j1)
        repo.add_job(j2)

        jobs = repo.list_jobs()
        assert len(jobs) == 2
        ids = {j.job_id for j in jobs}
        assert ids == {"j-1", "j-2"}

    def test_add_overwrites_same_id(self) -> None:
        """Adding a job with a duplicate ID replaces the previous entry."""
        repo = InMemorySchedulerJobRepository()
        j1 = _make_job("j-1", "wf-old")
        j2 = _make_job("j-1", "wf-new")
        repo.add_job(j1)
        repo.add_job(j2)

        retrieved = repo.get_job("j-1")
        assert retrieved is not None
        assert retrieved.workflow_name == "wf-new"
        assert len(repo.list_jobs()) == 1

    def test_remove_existing_job_returns_true(self) -> None:
        """Removing an existing job returns True and the job is gone."""
        repo = InMemorySchedulerJobRepository()
        repo.add_job(_make_job("j-1"))

        assert repo.remove_job("j-1") is True
        assert repo.get_job("j-1") is None
        assert repo.list_jobs() == []

    def test_remove_nonexistent_job_returns_false(self) -> None:
        """Removing a job that does not exist returns False."""
        repo = InMemorySchedulerJobRepository()
        assert repo.remove_job("does-not-exist") is False

    def test_remove_does_not_affect_other_jobs(self) -> None:
        """Removing one job does not disturb other jobs."""
        repo = InMemorySchedulerJobRepository()
        repo.add_job(_make_job("j-1", "wf-a"))
        repo.add_job(_make_job("j-2", "wf-b"))

        repo.remove_job("j-1")
        assert repo.get_job("j-1") is None
        remaining = repo.get_job("j-2")
        assert remaining is not None
        assert remaining.workflow_name == "wf-b"
