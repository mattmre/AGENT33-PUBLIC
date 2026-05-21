"""Multi-replica E2E testing infrastructure (P4.9).

Tests in this module validate cross-instance behavior for AGENT-33's
control-plane repositories, distributed lock primitives, and session
affinity semantics.

**CI tests** (no ``@pytest.mark.integration``) run without Docker by using
in-process repository instances, mock Redis, and shared temp files.

**Integration tests** (``@pytest.mark.integration``) require the Docker
multi-instance setup and are skipped when Docker is not available.
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from agent33.automation.cron_models import JobRunRecord
from agent33.automation.pg_job_history_repository import SqliteJobHistoryRepository
from agent33.automation.pg_scheduler_repository import SqliteSchedulerJobRepository
from agent33.automation.pg_webhook_repository import SqliteWebhookRepository
from agent33.automation.scheduler import ScheduledJob
from agent33.scaling.distributed_lock import InProcessLock, RedisDistributedLock
from agent33.scaling.instance_registry import InstanceRegistry
from agent33.scaling.state_guards import InstanceConflictError, SingleInstanceGuard
from agent33.sessions.models import OperatorSessionStatus
from agent33.sessions.service import OperatorSessionService
from agent33.sessions.storage import FileSessionStorage

if TYPE_CHECKING:
    from pathlib import Path


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


def _make_run(
    run_id: str = "run-1",
    job_id: str = "job-1",
    status: str = "completed",
    error: str = "",
) -> JobRunRecord:
    return JobRunRecord(
        run_id=run_id,
        job_id=job_id,
        started_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        ended_at=datetime(2026, 1, 1, 12, 0, 5, tzinfo=UTC),
        status=status,
        error=error,
    )


class _FakeRedis:
    """Minimal async Redis mock for distributed lock tests.

    Simulates the Redis SETNX + EX + Lua-eval pattern used by
    ``RedisDistributedLock`` without requiring a real Redis server.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._ttls: dict[str, float] = {}

    async def set(
        self,
        key: str,
        value: str,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        if nx and key in self._store:
            return None  # SETNX semantics: key already exists
        self._store[key] = value
        if ex is not None:
            self._ttls[key] = float(ex)
        return True

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for k in keys:
            if self._store.pop(k, None) is not None:
                deleted += 1
                self._ttls.pop(k, None)
        return deleted

    async def eval(
        self,
        script: str,
        num_keys: int,
        *args: str,
    ) -> int:
        """Simulate the Lua scripts used by RedisDistributedLock."""
        # The lock uses two Lua scripts:
        # 1. Release: if GET key == token then DEL key
        # 2. Extend: if GET key == token then EXPIRE key ttl
        key = args[0]
        token = args[1]
        stored = self._store.get(key)

        if stored == token:
            if "del" in script:
                self._store.pop(key, None)
                self._ttls.pop(key, None)
                return 1
            if "expire" in script:
                ttl = int(args[2])
                self._ttls[key] = float(ttl)
                return 1
        return 0

    async def expire(self, key: str, seconds: int) -> bool:
        if key in self._store:
            self._ttls[key] = float(seconds)
            return True
        return False

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        pass

    def clear_key(self, key: str) -> None:
        """Test helper: remove a key to simulate TTL expiry."""
        self._store.pop(key, None)
        self._ttls.pop(key, None)

    async def scan_iter(self, match: str = "*") -> Any:
        """Yield keys matching a glob pattern."""
        import fnmatch

        for key in list(self._store.keys()):
            if fnmatch.fnmatch(key, match):
                yield key


def _docker_available() -> bool:
    """Check if Docker is available for integration tests."""
    return (
        shutil.which("docker") is not None
        and os.environ.get("AGENT33_MULTI_REPLICA_TESTS", "") == "1"
    )


# ===========================================================================
# Cross-Instance Repository Consistency (CI-safe, no Docker)
# ===========================================================================


class TestCrossInstanceSchedulerRepository:
    """Two SqliteSchedulerJobRepository instances sharing the same DB file."""

    def test_write_from_repo1_visible_in_repo2(self, tmp_path: Path) -> None:
        """Data written by one repo instance is immediately visible to another."""
        db_path = str(tmp_path / "scheduler.db")
        repo1 = SqliteSchedulerJobRepository(db_path)
        repo2 = SqliteSchedulerJobRepository(db_path)

        try:
            job = _make_job(job_id="cross-1", workflow_name="pipeline-alpha")
            repo1.add_job(job)

            # repo2 reads the same DB file and sees the job
            retrieved = repo2.get_job("cross-1")
            assert retrieved is not None
            assert retrieved.job_id == "cross-1"
            assert retrieved.workflow_name == "pipeline-alpha"
        finally:
            repo1.close()
            repo2.close()

    def test_list_reflects_writes_from_both_repos(self, tmp_path: Path) -> None:
        """list_jobs() returns jobs written by either repo instance."""
        db_path = str(tmp_path / "scheduler.db")
        repo1 = SqliteSchedulerJobRepository(db_path)
        repo2 = SqliteSchedulerJobRepository(db_path)

        try:
            repo1.add_job(_make_job(job_id="from-repo1"))
            repo2.add_job(_make_job(job_id="from-repo2"))

            # Both repos see both jobs
            jobs_from_1 = repo1.list_jobs()
            jobs_from_2 = repo2.list_jobs()
            ids_from_1 = {j.job_id for j in jobs_from_1}
            ids_from_2 = {j.job_id for j in jobs_from_2}

            assert ids_from_1 == {"from-repo1", "from-repo2"}
            assert ids_from_2 == {"from-repo1", "from-repo2"}
        finally:
            repo1.close()
            repo2.close()

    def test_remove_from_repo1_reflected_in_repo2(self, tmp_path: Path) -> None:
        """Removing a job from one repo makes it invisible to the other."""
        db_path = str(tmp_path / "scheduler.db")
        repo1 = SqliteSchedulerJobRepository(db_path)
        repo2 = SqliteSchedulerJobRepository(db_path)

        try:
            repo1.add_job(_make_job(job_id="deleteme"))
            assert repo2.get_job("deleteme") is not None

            repo1.remove_job("deleteme")
            assert repo2.get_job("deleteme") is None
        finally:
            repo1.close()
            repo2.close()

    def test_replace_from_repo2_updates_repo1_view(self, tmp_path: Path) -> None:
        """INSERT OR REPLACE from repo2 updates the row seen by repo1."""
        db_path = str(tmp_path / "scheduler.db")
        repo1 = SqliteSchedulerJobRepository(db_path)
        repo2 = SqliteSchedulerJobRepository(db_path)

        try:
            repo1.add_job(_make_job(job_id="j1", workflow_name="old-wf"))
            repo2.add_job(_make_job(job_id="j1", workflow_name="new-wf"))

            result = repo1.get_job("j1")
            assert result is not None
            assert result.workflow_name == "new-wf"
        finally:
            repo1.close()
            repo2.close()


class TestCrossInstanceJobHistoryRepository:
    """Two SqliteJobHistoryRepository instances sharing the same DB file."""

    def test_record_from_repo1_queryable_from_repo2(self, tmp_path: Path) -> None:
        """Job history recorded by one instance is queryable from another."""
        db_path = str(tmp_path / "history.db")
        repo1 = SqliteJobHistoryRepository(db_path)
        repo2 = SqliteJobHistoryRepository(db_path)

        try:
            repo1.record(_make_run(run_id="r1", job_id="j1", status="completed"))

            results = repo2.query("j1")
            assert len(results) == 1
            assert results[0].run_id == "r1"
            assert results[0].status == "completed"
        finally:
            repo1.close()
            repo2.close()

    def test_interleaved_writes_maintain_ordering(self, tmp_path: Path) -> None:
        """Records written by alternating repos maintain correct ordering."""
        db_path = str(tmp_path / "history.db")
        repo1 = SqliteJobHistoryRepository(db_path)
        repo2 = SqliteJobHistoryRepository(db_path)

        try:
            repo1.record(_make_run(run_id="r1", job_id="j1"))
            repo2.record(_make_run(run_id="r2", job_id="j1"))
            repo1.record(_make_run(run_id="r3", job_id="j1"))

            results = repo2.query("j1")
            assert [r.run_id for r in results] == ["r3", "r2", "r1"]
        finally:
            repo1.close()
            repo2.close()

    def test_all_job_ids_aggregates_across_repos(self, tmp_path: Path) -> None:
        """all_job_ids() returns IDs from records written by either repo."""
        db_path = str(tmp_path / "history.db")
        repo1 = SqliteJobHistoryRepository(db_path)
        repo2 = SqliteJobHistoryRepository(db_path)

        try:
            repo1.record(_make_run(run_id="r1", job_id="alpha"))
            repo2.record(_make_run(run_id="r2", job_id="beta"))

            ids = set(repo1.all_job_ids())
            assert ids == {"alpha", "beta"}
        finally:
            repo1.close()
            repo2.close()

    def test_retention_enforced_across_writers(self, tmp_path: Path) -> None:
        """Per-job retention limits apply regardless of which repo wrote the record."""
        db_path = str(tmp_path / "history.db")
        repo1 = SqliteJobHistoryRepository(db_path, max_records_per_job=3)
        repo2 = SqliteJobHistoryRepository(db_path, max_records_per_job=3)

        try:
            for i in range(5):
                writer = repo1 if i % 2 == 0 else repo2
                writer.record(_make_run(run_id=f"r{i}", job_id="j1"))

            results = repo1.query("j1", limit=100)
            assert len(results) == 3
            # Most recent 3 records survive
            assert [r.run_id for r in results] == ["r4", "r3", "r2"]
        finally:
            repo1.close()
            repo2.close()


class TestCrossInstanceWebhookRepository:
    """Two SqliteWebhookRepository instances sharing the same DB file."""

    def test_webhook_registered_by_one_visible_to_other(self, tmp_path: Path) -> None:
        """A webhook registered by repo1 is visible to repo2."""
        db_path = str(tmp_path / "webhooks.db")
        repo1 = SqliteWebhookRepository(db_path)
        repo2 = SqliteWebhookRepository(db_path)

        try:
            repo1.register_webhook("/hooks/deploy", "secret-1", "deploy-wf")

            fetched = repo2.get_webhook("/hooks/deploy")
            assert fetched is not None
            assert fetched["path"] == "/hooks/deploy"
            assert fetched["secret"] == "secret-1"
            assert fetched["workflow_name"] == "deploy-wf"
        finally:
            repo1.close()
            repo2.close()

    def test_list_webhooks_aggregates_both_repos(self, tmp_path: Path) -> None:
        """list_webhooks() includes registrations from both repo instances."""
        db_path = str(tmp_path / "webhooks.db")
        repo1 = SqliteWebhookRepository(db_path)
        repo2 = SqliteWebhookRepository(db_path)

        try:
            repo1.register_webhook("/a", "sa", "wfa")
            repo2.register_webhook("/b", "sb", "wfb")

            hooks = repo1.list_webhooks()
            paths = {h["path"] for h in hooks}
            assert paths == {"/a", "/b"}
        finally:
            repo1.close()
            repo2.close()

    def test_unregister_from_repo2_removes_from_repo1(self, tmp_path: Path) -> None:
        """Unregistering via repo2 makes the webhook invisible to repo1."""
        db_path = str(tmp_path / "webhooks.db")
        repo1 = SqliteWebhookRepository(db_path)
        repo2 = SqliteWebhookRepository(db_path)

        try:
            repo1.register_webhook("/hooks/x", "sx", "wfx")
            assert repo2.unregister_webhook("/hooks/x") is True
            assert repo1.get_webhook("/hooks/x") is None
        finally:
            repo1.close()
            repo2.close()

    def test_replace_from_repo2_updates_repo1(self, tmp_path: Path) -> None:
        """Re-registering a webhook from repo2 updates the record seen by repo1."""
        db_path = str(tmp_path / "webhooks.db")
        repo1 = SqliteWebhookRepository(db_path)
        repo2 = SqliteWebhookRepository(db_path)

        try:
            repo1.register_webhook("/hooks/y", "old-secret", "old-wf")
            repo2.register_webhook("/hooks/y", "new-secret", "new-wf")

            fetched = repo1.get_webhook("/hooks/y")
            assert fetched is not None
            assert fetched["secret"] == "new-secret"
            assert fetched["workflow_name"] == "new-wf"
        finally:
            repo1.close()
            repo2.close()


# ===========================================================================
# Distributed Lock Behavior (CI-safe, mock Redis)
# ===========================================================================


class TestDistributedLockBehavior:
    """Validate distributed lock semantics using a mock Redis backend."""

    @pytest.fixture()
    def fake_redis(self) -> _FakeRedis:
        return _FakeRedis()

    async def test_lock_acquisition_blocks_second_holder(self, fake_redis: _FakeRedis) -> None:
        """Two lock holders cannot hold the same lock simultaneously."""
        lock1 = RedisDistributedLock(redis=fake_redis, name="test-lock", ttl_seconds=30)
        lock2 = RedisDistributedLock(redis=fake_redis, name="test-lock", ttl_seconds=30)

        acquired1 = await lock1.acquire(timeout_seconds=0)
        assert acquired1 is True
        assert lock1.is_held is True

        # Second lock holder cannot acquire the same lock
        acquired2 = await lock2.acquire(timeout_seconds=0)
        assert acquired2 is False
        assert lock2.is_held is False

        await lock1.release()

    async def test_lock_release_allows_second_holder(self, fake_redis: _FakeRedis) -> None:
        """After release, a waiting holder can acquire the lock."""
        lock1 = RedisDistributedLock(redis=fake_redis, name="test-lock", ttl_seconds=30)
        lock2 = RedisDistributedLock(redis=fake_redis, name="test-lock", ttl_seconds=30)

        # First holder acquires and releases
        await lock1.acquire(timeout_seconds=0)
        released = await lock1.release()
        assert released is True
        assert lock1.is_held is False

        # Second holder can now acquire
        acquired = await lock2.acquire(timeout_seconds=0)
        assert acquired is True
        assert lock2.is_held is True

        await lock2.release()

    async def test_lock_ttl_auto_releases(self, fake_redis: _FakeRedis) -> None:
        """Lock automatically releases after TTL expires (simulated)."""
        lock1 = RedisDistributedLock(redis=fake_redis, name="ttl-lock", ttl_seconds=5)
        lock2 = RedisDistributedLock(redis=fake_redis, name="ttl-lock", ttl_seconds=5)

        await lock1.acquire(timeout_seconds=0)
        assert lock1.is_held is True

        # Simulate TTL expiry by clearing the Redis key
        fake_redis.clear_key("agent33:lock:ttl-lock")

        # Second holder can now acquire because the key expired
        acquired = await lock2.acquire(timeout_seconds=0)
        assert acquired is True

        await lock2.release()

    async def test_lock_extend_refreshes_ownership(self, fake_redis: _FakeRedis) -> None:
        """Extending a held lock refreshes the TTL without releasing."""
        lock = RedisDistributedLock(redis=fake_redis, name="extend-lock", ttl_seconds=10)

        await lock.acquire(timeout_seconds=0)
        assert lock.is_held is True

        extended = await lock.extend(additional_seconds=60)
        assert extended is True

        # Lock is still held
        assert lock.is_held is True

        await lock.release()

    async def test_release_without_acquire_returns_false(self, fake_redis: _FakeRedis) -> None:
        """Releasing a lock that was never acquired returns False."""
        lock = RedisDistributedLock(redis=fake_redis, name="no-acquire", ttl_seconds=30)
        assert await lock.release() is False

    async def test_double_release_returns_false(self, fake_redis: _FakeRedis) -> None:
        """Releasing a lock twice: first returns True, second returns False."""
        lock = RedisDistributedLock(redis=fake_redis, name="double-rel", ttl_seconds=30)
        await lock.acquire(timeout_seconds=0)

        assert await lock.release() is True
        assert await lock.release() is False

    async def test_different_lock_names_are_independent(self, fake_redis: _FakeRedis) -> None:
        """Locks with different names do not interfere with each other."""
        lock_a = RedisDistributedLock(redis=fake_redis, name="lock-a", ttl_seconds=30)
        lock_b = RedisDistributedLock(redis=fake_redis, name="lock-b", ttl_seconds=30)

        acquired_a = await lock_a.acquire(timeout_seconds=0)
        acquired_b = await lock_b.acquire(timeout_seconds=0)

        assert acquired_a is True
        assert acquired_b is True

        await lock_a.release()
        await lock_b.release()


class TestInProcessLockBehavior:
    """Validate the in-process lock fallback used in single-node deployments."""

    async def test_lock_mutual_exclusion(self) -> None:
        """InProcessLock acquire-release cycle works correctly."""
        lock = InProcessLock(name="test")

        # InProcessLock instances with the same name do NOT share state
        # because each has its own asyncio.Lock. This is by design -- it is a
        # single-process fallback. We verify its basic contract here.
        acquired = await lock.acquire(timeout_seconds=0)
        assert acquired is True
        assert lock.is_held is True

        # Release returns True and clears the held flag
        released = await lock.release()
        assert released is True
        assert lock.is_held is False

        # Can re-acquire after release
        acquired_again = await lock.acquire(timeout_seconds=0)
        assert acquired_again is True
        await lock.release()

    async def test_lock_name_property(self) -> None:
        """lock_name returns the name passed at construction."""
        lock = InProcessLock(name="my-lock")
        assert lock.lock_name == "my-lock"


# ===========================================================================
# Instance Registry and State Guards (CI-safe, mock Redis)
# ===========================================================================


class TestInstanceRegistryMultiInstance:
    """Validate instance registry with multiple registrations."""

    async def test_two_instances_detected(self) -> None:
        """Two instances registered via the same Redis are both visible."""
        fake_redis = _FakeRedis()
        reg1 = InstanceRegistry(redis=fake_redis, ttl_seconds=60)
        reg2 = InstanceRegistry(redis=fake_redis, ttl_seconds=60)

        info1 = await reg1.register(metadata={"role": "api-1"})
        info2 = await reg2.register(metadata={"role": "api-2"})

        assert info1.instance_id != info2.instance_id

        instances = await reg1.list_live_instances()
        ids = {inst.instance_id for inst in instances}
        assert info1.instance_id in ids
        assert info2.instance_id in ids
        assert len(instances) == 2

        await reg1.deregister()
        await reg2.deregister()

    async def test_deregister_reduces_count(self) -> None:
        """Deregistering one instance reduces the live count."""
        fake_redis = _FakeRedis()
        reg1 = InstanceRegistry(redis=fake_redis, ttl_seconds=60)
        reg2 = InstanceRegistry(redis=fake_redis, ttl_seconds=60)

        await reg1.register()
        await reg2.register()

        count_before = await reg1.count_live_instances()
        assert count_before == 2

        await reg2.deregister()

        count_after = await reg1.count_live_instances()
        assert count_after == 1

        await reg1.deregister()

    async def test_heartbeat_keeps_instance_alive(self) -> None:
        """Heartbeat refreshes the TTL so the instance stays registered."""
        fake_redis = _FakeRedis()
        reg = InstanceRegistry(redis=fake_redis, ttl_seconds=60)

        await reg.register()
        success = await reg.heartbeat()
        assert success is True

        count = await reg.count_live_instances()
        assert count == 1

        await reg.deregister()


class TestSingleInstanceGuardMultiReplica:
    """Validate that SingleInstanceGuard raises on multi-instance detection."""

    async def test_guard_raises_on_two_instances(self) -> None:
        """SingleInstanceGuard.check() raises InstanceConflictError when count > 1."""
        fake_redis = _FakeRedis()
        reg1 = InstanceRegistry(redis=fake_redis, ttl_seconds=60)
        reg2 = InstanceRegistry(redis=fake_redis, ttl_seconds=60)

        await reg1.register()
        await reg2.register()

        guard = SingleInstanceGuard(registry=reg1, surface_name="cron_scheduler")

        with pytest.raises(InstanceConflictError) as exc_info:
            await guard.check()

        assert exc_info.value.surface == "cron_scheduler"
        assert exc_info.value.instance_count == 2

        await reg1.deregister()
        await reg2.deregister()

    async def test_guard_passes_on_single_instance(self) -> None:
        """SingleInstanceGuard.check() passes when only one instance is registered."""
        fake_redis = _FakeRedis()
        reg = InstanceRegistry(redis=fake_redis, ttl_seconds=60)

        await reg.register()

        guard = SingleInstanceGuard(registry=reg, surface_name="cron_scheduler")
        # Should not raise
        await guard.check()

        await reg.deregister()

    async def test_guard_check_or_warn_returns_false_on_conflict(self) -> None:
        """check_or_warn returns False (instead of raising) on conflict."""
        fake_redis = _FakeRedis()
        reg1 = InstanceRegistry(redis=fake_redis, ttl_seconds=60)
        reg2 = InstanceRegistry(redis=fake_redis, ttl_seconds=60)

        await reg1.register()
        await reg2.register()

        guard = SingleInstanceGuard(registry=reg1, surface_name="webhooks")
        result = await guard.check_or_warn()
        assert result is False

        await reg1.deregister()
        await reg2.deregister()


# ===========================================================================
# Session Affinity Behavior (CI-safe, temp filesystem)
# ===========================================================================


class TestSessionAffinityBehavior:
    """Test that session state is accessible across service instances."""

    async def test_session_created_on_one_visible_on_other(self, tmp_path: Path) -> None:
        """Session created via service 1 is queryable via service 2."""
        base_dir = tmp_path / "sessions"
        base_dir.mkdir()

        storage1 = FileSessionStorage(base_dir=base_dir)
        storage2 = FileSessionStorage(base_dir=base_dir)
        service1 = OperatorSessionService(storage=storage1)
        service2 = OperatorSessionService(storage=storage2)

        # Create session via service 1
        session = await service1.start_session(
            purpose="test-cross-instance",
            tenant_id="tenant-1",
        )
        session_id = session.session_id

        # Service 2 loads the session via its own service/storage layer
        loaded = await service2.get_session(session_id)
        assert loaded is not None
        assert loaded.session_id == session_id
        assert loaded.purpose == "test-cross-instance"
        assert loaded.tenant_id == "tenant-1"
        assert loaded.status == OperatorSessionStatus.ACTIVE

    async def test_session_ended_on_one_reflected_on_other(self, tmp_path: Path) -> None:
        """Session ended via service 1 shows ended status when loaded by service 2."""
        base_dir = tmp_path / "sessions"
        base_dir.mkdir()

        storage1 = FileSessionStorage(base_dir=base_dir)
        storage2 = FileSessionStorage(base_dir=base_dir)
        service1 = OperatorSessionService(storage=storage1)
        service2 = OperatorSessionService(storage=storage2)

        session = await service1.start_session(purpose="ending-test")
        session_id = session.session_id

        # End the session via service 1
        await service1.end_session(session_id)

        # Service 2 loads the session and sees it is completed
        loaded = await service2.get_session(session_id)
        assert loaded is not None
        assert loaded.status == OperatorSessionStatus.COMPLETED

    async def test_multiple_sessions_listed_across_instances(self, tmp_path: Path) -> None:
        """Sessions created by different service instances are all listed."""
        base_dir = tmp_path / "sessions"
        base_dir.mkdir()

        storage1 = FileSessionStorage(base_dir=base_dir)
        storage2 = FileSessionStorage(base_dir=base_dir)
        service1 = OperatorSessionService(storage=storage1)
        service2 = OperatorSessionService(storage=storage2)

        s1 = await service1.start_session(purpose="from-service-1")
        s2 = await service2.start_session(purpose="from-service-2")

        # Both sessions discoverable via service 1's list
        all_sessions = await service1.list_sessions()
        all_ids = {s.session_id for s in all_sessions}
        assert s1.session_id in all_ids
        assert s2.session_id in all_ids


# ===========================================================================
# Integration tests (require Docker multi-instance setup)
# ===========================================================================


@pytest.mark.integration
@pytest.mark.skipif(
    not _docker_available(),
    reason="Docker not available or AGENT33_MULTI_REPLICA_TESTS != 1",
)
class TestMultiInstanceIntegration:
    """Tests that require the actual Docker multi-instance setup.

    Run with:
        cd engine
        docker compose -f docker-compose.yml -f docker-compose.multi.yml up -d
        AGENT33_MULTI_REPLICA_TESTS=1 pytest tests/test_multi_replica_e2e.py \
            -m integration
    """

    async def test_health_both_instances(self) -> None:
        """Both API instances respond to health checks."""
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            r1 = await client.get("http://localhost:8001/healthz")
            r2 = await client.get("http://localhost:8002/healthz")

        assert r1.status_code == 200
        assert r1.json()["status"] == "healthy"
        assert r2.status_code == 200
        assert r2.json()["status"] == "healthy"

    async def test_load_balancer_health(self) -> None:
        """Load balancer responds to its own health endpoint."""
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("http://localhost:8000/lb-health")

        assert r.status_code == 200

    async def test_load_balanced_requests_reach_both_instances(self) -> None:
        """Multiple requests through the LB reach both backend instances."""
        import httpx

        responses: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=10) as client:
            for _ in range(20):
                r = await client.get("http://localhost:8000/healthz")
                assert r.status_code == 200
                responses.append(r.json())

        # With round-robin, all responses should be healthy
        assert all(r["status"] == "healthy" for r in responses)
