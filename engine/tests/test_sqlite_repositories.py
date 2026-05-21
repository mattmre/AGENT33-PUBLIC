"""Tests for SQLite-backed control-plane repositories (P4.5).

Each test uses an in-memory SQLite database (``":memory:"``) to avoid
filesystem side-effects while still exercising the real SQL logic.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agent33.automation.cron_models import JobRunRecord
from agent33.automation.job_history_repository import JobHistoryRepository
from agent33.automation.pg_job_history_repository import SqliteJobHistoryRepository
from agent33.automation.pg_scheduler_repository import SqliteSchedulerJobRepository
from agent33.automation.pg_webhook_repository import SqliteWebhookRepository
from agent33.automation.scheduler import ScheduledJob
from agent33.automation.scheduler_repository import SchedulerJobRepository
from agent33.automation.webhook_repository import WebhookRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(
    job_id: str = "job-1",
    workflow_name: str = "deploy",
    schedule_type: str = "cron",
    schedule_expr: str = "*/5 * * * *",
    inputs: dict[str, object] | None = None,
) -> ScheduledJob:
    return ScheduledJob(
        job_id=job_id,
        workflow_name=workflow_name,
        schedule_type=schedule_type,
        schedule_expr=schedule_expr,
        inputs=inputs or {},
    )


_SENTINEL = object()


def _make_run(
    run_id: str = "run-1",
    job_id: str = "job-1",
    status: str = "completed",
    error: str = "",
    started_at: datetime | None = None,
    ended_at: datetime | None | object = _SENTINEL,
) -> JobRunRecord:
    return JobRunRecord(
        run_id=run_id,
        job_id=job_id,
        started_at=started_at or datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        ended_at=(
            datetime(2026, 1, 1, 12, 0, 5, tzinfo=UTC) if ended_at is _SENTINEL else ended_at  # type: ignore[arg-type]
        ),
        status=status,
        error=error,
    )


# ===========================================================================
# SqliteSchedulerJobRepository
# ===========================================================================


class TestSqliteSchedulerJobRepository:
    """CRUD tests for the scheduler job repository."""

    def test_protocol_conformance(self) -> None:
        repo = SqliteSchedulerJobRepository(":memory:")
        assert isinstance(repo, SchedulerJobRepository)

    def test_add_and_get_job(self) -> None:
        repo = SqliteSchedulerJobRepository(":memory:")
        job = _make_job()
        repo.add_job(job)

        retrieved = repo.get_job("job-1")
        assert retrieved is not None
        assert retrieved.job_id == "job-1"
        assert retrieved.workflow_name == "deploy"
        assert retrieved.schedule_type == "cron"
        assert retrieved.schedule_expr == "*/5 * * * *"
        assert retrieved.inputs == {}

    def test_get_missing_job_returns_none(self) -> None:
        repo = SqliteSchedulerJobRepository(":memory:")
        assert repo.get_job("does-not-exist") is None

    def test_list_jobs_empty(self) -> None:
        repo = SqliteSchedulerJobRepository(":memory:")
        assert repo.list_jobs() == []

    def test_list_jobs_multiple(self) -> None:
        repo = SqliteSchedulerJobRepository(":memory:")
        repo.add_job(_make_job(job_id="a"))
        repo.add_job(_make_job(job_id="b"))
        repo.add_job(_make_job(job_id="c"))

        jobs = repo.list_jobs()
        assert len(jobs) == 3
        ids = {j.job_id for j in jobs}
        assert ids == {"a", "b", "c"}

    def test_add_job_replaces_existing(self) -> None:
        repo = SqliteSchedulerJobRepository(":memory:")
        repo.add_job(_make_job(job_id="j1", workflow_name="old"))
        repo.add_job(_make_job(job_id="j1", workflow_name="new"))

        job = repo.get_job("j1")
        assert job is not None
        assert job.workflow_name == "new"
        assert len(repo.list_jobs()) == 1

    def test_remove_job_returns_true_when_found(self) -> None:
        repo = SqliteSchedulerJobRepository(":memory:")
        repo.add_job(_make_job(job_id="j1"))
        assert repo.remove_job("j1") is True
        assert repo.get_job("j1") is None

    def test_remove_job_returns_false_when_missing(self) -> None:
        repo = SqliteSchedulerJobRepository(":memory:")
        assert repo.remove_job("nope") is False

    def test_inputs_round_trip(self) -> None:
        """Verify complex input dicts survive JSON serialisation."""
        repo = SqliteSchedulerJobRepository(":memory:")
        inputs = {"env": "prod", "count": 42, "tags": ["a", "b"]}
        repo.add_job(_make_job(job_id="j1", inputs=inputs))

        job = repo.get_job("j1")
        assert job is not None
        assert job.inputs == inputs

    def test_close_does_not_raise(self) -> None:
        repo = SqliteSchedulerJobRepository(":memory:")
        repo.close()


# ===========================================================================
# SqliteJobHistoryRepository
# ===========================================================================


class TestSqliteJobHistoryRepository:
    """CRUD and retention tests for the job history repository."""

    def test_protocol_conformance(self) -> None:
        repo = SqliteJobHistoryRepository(":memory:")
        assert isinstance(repo, JobHistoryRepository)

    def test_record_and_query(self) -> None:
        repo = SqliteJobHistoryRepository(":memory:")
        run = _make_run()
        repo.record(run)

        results = repo.query("job-1")
        assert len(results) == 1
        assert results[0].run_id == "run-1"
        assert results[0].job_id == "job-1"
        assert results[0].status == "completed"
        assert results[0].error == ""

    def test_query_empty(self) -> None:
        repo = SqliteJobHistoryRepository(":memory:")
        assert repo.query("no-such-job") == []

    def test_query_most_recent_first(self) -> None:
        repo = SqliteJobHistoryRepository(":memory:")
        repo.record(_make_run(run_id="r1", job_id="j"))
        repo.record(_make_run(run_id="r2", job_id="j"))
        repo.record(_make_run(run_id="r3", job_id="j"))

        results = repo.query("j")
        assert [r.run_id for r in results] == ["r3", "r2", "r1"]

    def test_query_with_limit(self) -> None:
        repo = SqliteJobHistoryRepository(":memory:")
        for i in range(10):
            repo.record(_make_run(run_id=f"r{i}", job_id="j"))

        results = repo.query("j", limit=3)
        assert len(results) == 3
        # Most recent first
        assert results[0].run_id == "r9"

    def test_query_filter_by_status(self) -> None:
        repo = SqliteJobHistoryRepository(":memory:")
        repo.record(_make_run(run_id="r1", job_id="j", status="completed"))
        repo.record(_make_run(run_id="r2", job_id="j", status="failed"))
        repo.record(_make_run(run_id="r3", job_id="j", status="completed"))

        completed = repo.query("j", status="completed")
        assert len(completed) == 2
        assert all(r.status == "completed" for r in completed)

        failed = repo.query("j", status="failed")
        assert len(failed) == 1
        assert failed[0].run_id == "r2"

    def test_retention_limit(self) -> None:
        """When records exceed max_records_per_job, oldest are evicted."""
        repo = SqliteJobHistoryRepository(":memory:", max_records_per_job=5)
        for i in range(10):
            repo.record(_make_run(run_id=f"r{i}", job_id="j"))

        results = repo.query("j", limit=100)
        assert len(results) == 5
        # Only the 5 most recent should survive
        assert [r.run_id for r in results] == ["r9", "r8", "r7", "r6", "r5"]

    def test_retention_per_job_isolation(self) -> None:
        """Retention for job-A must not affect job-B."""
        repo = SqliteJobHistoryRepository(":memory:", max_records_per_job=3)
        for i in range(5):
            repo.record(_make_run(run_id=f"a{i}", job_id="job-a"))
        for i in range(5):
            repo.record(_make_run(run_id=f"b{i}", job_id="job-b"))

        a_results = repo.query("job-a", limit=100)
        b_results = repo.query("job-b", limit=100)
        assert len(a_results) == 3
        assert len(b_results) == 3

    def test_all_job_ids(self) -> None:
        repo = SqliteJobHistoryRepository(":memory:")
        repo.record(_make_run(run_id="r1", job_id="alpha"))
        repo.record(_make_run(run_id="r2", job_id="beta"))
        repo.record(_make_run(run_id="r3", job_id="alpha"))

        ids = repo.all_job_ids()
        assert set(ids) == {"alpha", "beta"}

    def test_all_job_ids_empty(self) -> None:
        repo = SqliteJobHistoryRepository(":memory:")
        assert repo.all_job_ids() == []

    def test_datetime_round_trip(self) -> None:
        """started_at and ended_at survive serialisation with timezone info."""
        repo = SqliteJobHistoryRepository(":memory:")
        start = datetime(2026, 3, 24, 10, 30, 0, tzinfo=UTC)
        end = datetime(2026, 3, 24, 10, 30, 15, tzinfo=UTC)
        repo.record(_make_run(run_id="r1", started_at=start, ended_at=end))

        results = repo.query("job-1")
        assert len(results) == 1
        assert results[0].started_at == start
        assert results[0].ended_at == end

    def test_ended_at_none(self) -> None:
        """A running job may have ended_at=None."""
        repo = SqliteJobHistoryRepository(":memory:")
        repo.record(_make_run(run_id="r1", status="running", ended_at=None))

        results = repo.query("job-1")
        assert len(results) == 1
        assert results[0].ended_at is None

    def test_error_field_preserved(self) -> None:
        repo = SqliteJobHistoryRepository(":memory:")
        repo.record(_make_run(run_id="r1", status="failed", error="connection timeout"))

        results = repo.query("job-1")
        assert results[0].error == "connection timeout"

    def test_close_does_not_raise(self) -> None:
        repo = SqliteJobHistoryRepository(":memory:")
        repo.close()


# ===========================================================================
# SqliteWebhookRepository
# ===========================================================================


class TestSqliteWebhookRepository:
    """CRUD tests for the webhook registration repository."""

    def test_protocol_conformance(self) -> None:
        repo = SqliteWebhookRepository(":memory:")
        assert isinstance(repo, WebhookRepository)

    def test_register_and_get(self) -> None:
        repo = SqliteWebhookRepository(":memory:")
        record = repo.register_webhook("/hooks/deploy", "s3cret", "deploy-wf")

        assert record["path"] == "/hooks/deploy"
        assert record["secret"] == "s3cret"
        assert record["workflow_name"] == "deploy-wf"
        assert "created_at" in record

        fetched = repo.get_webhook("/hooks/deploy")
        assert fetched is not None
        assert fetched["path"] == "/hooks/deploy"
        assert fetched["secret"] == "s3cret"
        assert fetched["workflow_name"] == "deploy-wf"

    def test_get_missing_returns_none(self) -> None:
        repo = SqliteWebhookRepository(":memory:")
        assert repo.get_webhook("/no/such/hook") is None

    def test_register_replaces_existing(self) -> None:
        repo = SqliteWebhookRepository(":memory:")
        repo.register_webhook("/hooks/x", "old-secret", "old-wf")
        repo.register_webhook("/hooks/x", "new-secret", "new-wf")

        fetched = repo.get_webhook("/hooks/x")
        assert fetched is not None
        assert fetched["secret"] == "new-secret"
        assert fetched["workflow_name"] == "new-wf"
        assert len(repo.list_webhooks()) == 1

    def test_unregister_returns_true_when_found(self) -> None:
        repo = SqliteWebhookRepository(":memory:")
        repo.register_webhook("/hooks/y", "s", "wf")
        assert repo.unregister_webhook("/hooks/y") is True
        assert repo.get_webhook("/hooks/y") is None

    def test_unregister_returns_false_when_missing(self) -> None:
        repo = SqliteWebhookRepository(":memory:")
        assert repo.unregister_webhook("/hooks/nope") is False

    def test_list_webhooks_empty(self) -> None:
        repo = SqliteWebhookRepository(":memory:")
        assert repo.list_webhooks() == []

    def test_list_webhooks_multiple(self) -> None:
        repo = SqliteWebhookRepository(":memory:")
        repo.register_webhook("/a", "sa", "wfa")
        repo.register_webhook("/b", "sb", "wfb")
        repo.register_webhook("/c", "sc", "wfc")

        hooks = repo.list_webhooks()
        assert len(hooks) == 3
        paths = {h["path"] for h in hooks}
        assert paths == {"/a", "/b", "/c"}

    def test_close_does_not_raise(self) -> None:
        repo = SqliteWebhookRepository(":memory:")
        repo.close()


# ===========================================================================
# Config validation
# ===========================================================================


class TestControlPlaneConfig:
    """Verify the control_plane_backend config field validates correctly."""

    def test_valid_backends(self) -> None:
        from agent33.config import Settings

        for backend in ("memory", "sqlite"):
            s = Settings(control_plane_backend=backend)
            assert s.control_plane_backend == backend

    def test_invalid_backend_raises(self) -> None:
        import pytest

        from agent33.config import Settings

        with pytest.raises(Exception):  # noqa: B017 — ValidationError
            Settings(control_plane_backend="postgres")

    def test_default_is_sqlite(self) -> None:
        from agent33.config import Settings

        s = Settings()
        assert s.control_plane_backend == "sqlite"

    def test_default_db_path(self) -> None:
        from agent33.config import Settings

        s = Settings()
        assert s.control_plane_db_path == "agent33_control_plane.db"
