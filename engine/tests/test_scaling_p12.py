"""Tests for P1.2 scaling primitives: instance registry, distributed locks, state guards."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import patch

import pytest

from agent33.scaling.distributed_lock import (
    InProcessLock,
    RedisDistributedLock,
    create_lock,
)
from agent33.scaling.instance_registry import (
    _REDIS_KEY_PREFIX,
    InstanceRegistry,
)
from agent33.scaling.state_guards import (
    InstanceConflictError,
    SchedulerOwnershipGuard,
    SingleInstanceGuard,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeRedis:
    """Minimal async Redis mock that simulates SETNX, GET, DEL, EXPIRE, EVAL."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}
        # Track calls for assertion
        self.set_calls: list[dict[str, Any]] = []
        self.del_calls: list[str] = []
        self.eval_calls: list[tuple[str, int, Any]] = []

    async def set(
        self,
        key: str,
        value: str,
        nx: bool = False,
        ex: int | None = None,
        **kwargs: Any,
    ) -> bool | None:
        self.set_calls.append({"key": key, "value": value, "nx": nx, "ex": ex})
        if nx and key in self._store:
            return None  # Key already exists
        self._store[key] = (value, ex)
        return True

    async def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        return entry[0]

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            self.del_calls.append(key)
            if key in self._store:
                del self._store[key]
                removed += 1
        return removed

    async def expire(self, key: str, ttl: int) -> bool:
        if key in self._store:
            value, _ = self._store[key]
            self._store[key] = (value, ttl)
            return True
        return False

    async def eval(
        self,
        script: str,
        numkeys: int,
        *args: Any,
    ) -> int:
        self.eval_calls.append((script, numkeys, args))
        # Simplified Lua eval for delete-if-match pattern
        if numkeys == 1 and len(args) >= 2:
            key = args[0]
            expected_token = args[1]
            entry = self._store.get(key)
            if entry is not None and entry[0] == expected_token:
                del self._store[key]
                return 1
            # extend pattern (expire-if-match): check for 3rd arg (ttl)
            if entry is not None and entry[0] == expected_token and len(args) >= 3:
                ttl = int(args[2])
                self._store[key] = (entry[0], ttl)
                return 1
        return 0

    async def scan_iter(self, match: str = "*") -> Any:
        """Async generator simulating SCAN."""
        prefix = match.rstrip("*")
        for key in list(self._store.keys()):
            if key.startswith(prefix):
                yield key

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Instance Registry Tests
# ---------------------------------------------------------------------------


class TestInstanceRegistryInProcess:
    """Instance registry without Redis (in-process fallback)."""

    async def test_register_creates_unique_id(self) -> None:
        registry = InstanceRegistry(redis=None)
        info = await registry.register()
        assert info.instance_id
        assert len(info.instance_id) == 32  # UUID hex
        assert info.hostname  # platform.node() should return something
        assert info.pid > 0
        assert info.started_at > 0

    async def test_register_stores_instance_info(self) -> None:
        registry = InstanceRegistry(redis=None)
        info = await registry.register()
        assert registry.instance_id == info.instance_id
        assert registry.instance_info is info

    async def test_deregister_clears_state(self) -> None:
        registry = InstanceRegistry(redis=None)
        await registry.register()
        assert registry.instance_id is not None
        await registry.deregister()
        assert registry.instance_id is None
        assert registry.instance_info is None

    async def test_deregister_when_not_registered_is_noop(self) -> None:
        registry = InstanceRegistry(redis=None)
        await registry.deregister()  # Should not raise

    async def test_heartbeat_returns_true_inprocess(self) -> None:
        registry = InstanceRegistry(redis=None)
        await registry.register()
        result = await registry.heartbeat()
        assert result is True

    async def test_heartbeat_returns_false_when_not_registered(self) -> None:
        registry = InstanceRegistry(redis=None)
        result = await registry.heartbeat()
        assert result is False

    async def test_list_live_instances_returns_self(self) -> None:
        registry = InstanceRegistry(redis=None)
        info = await registry.register()
        instances = await registry.list_live_instances()
        assert len(instances) == 1
        assert instances[0].instance_id == info.instance_id

    async def test_list_live_instances_empty_when_not_registered(self) -> None:
        registry = InstanceRegistry(redis=None)
        instances = await registry.list_live_instances()
        assert instances == []

    async def test_count_live_instances(self) -> None:
        registry = InstanceRegistry(redis=None)
        assert await registry.count_live_instances() == 0
        await registry.register()
        assert await registry.count_live_instances() == 1
        await registry.deregister()
        assert await registry.count_live_instances() == 0

    async def test_register_with_metadata(self) -> None:
        registry = InstanceRegistry(redis=None)
        info = await registry.register(metadata={"role": "primary"})
        assert info.metadata == {"role": "primary"}


class TestInstanceRegistryRedis:
    """Instance registry with mocked Redis."""

    async def test_register_writes_redis_key(self) -> None:
        fake_redis = FakeRedis()
        registry = InstanceRegistry(redis=fake_redis, ttl_seconds=30)
        info = await registry.register()

        # Verify Redis key was written
        key = f"{_REDIS_KEY_PREFIX}{info.instance_id}"
        raw = await fake_redis.get(key)
        assert raw is not None
        data = json.loads(raw)
        assert data["instance_id"] == info.instance_id
        assert data["hostname"] == info.hostname
        assert data["pid"] == info.pid

    async def test_register_sets_ttl(self) -> None:
        fake_redis = FakeRedis()
        registry = InstanceRegistry(redis=fake_redis, ttl_seconds=45)
        await registry.register()

        # Check the SET call had ex=45
        assert len(fake_redis.set_calls) == 1
        assert fake_redis.set_calls[0]["ex"] == 45

    async def test_deregister_removes_redis_key(self) -> None:
        fake_redis = FakeRedis()
        registry = InstanceRegistry(redis=fake_redis)
        info = await registry.register()
        key = f"{_REDIS_KEY_PREFIX}{info.instance_id}"
        assert await fake_redis.get(key) is not None

        await registry.deregister()
        assert await fake_redis.get(key) is None

    async def test_heartbeat_refreshes_ttl(self) -> None:
        fake_redis = FakeRedis()
        registry = InstanceRegistry(redis=fake_redis, ttl_seconds=60)
        await registry.register()
        result = await registry.heartbeat()
        assert result is True

    async def test_list_live_instances_from_redis(self) -> None:
        fake_redis = FakeRedis()

        # Simulate two instances
        await fake_redis.set(
            f"{_REDIS_KEY_PREFIX}aaa",
            json.dumps(
                {
                    "instance_id": "aaa",
                    "hostname": "host1",
                    "pid": 100,
                    "started_at": 1.0,
                }
            ),
        )
        await fake_redis.set(
            f"{_REDIS_KEY_PREFIX}bbb",
            json.dumps(
                {
                    "instance_id": "bbb",
                    "hostname": "host2",
                    "pid": 200,
                    "started_at": 2.0,
                }
            ),
        )

        registry = InstanceRegistry(redis=fake_redis)
        await registry.register()  # adds a third instance
        instances = await registry.list_live_instances()
        assert len(instances) == 3

        ids = {i.instance_id for i in instances}
        assert "aaa" in ids
        assert "bbb" in ids


# ---------------------------------------------------------------------------
# Distributed Lock Tests
# ---------------------------------------------------------------------------


class TestInProcessLock:
    """InProcessLock acquire/release semantics."""

    async def test_acquire_returns_true_when_free(self) -> None:
        lock = InProcessLock("test-lock")
        acquired = await lock.acquire(timeout_seconds=1)
        assert acquired is True
        assert lock.is_held is True
        assert lock.lock_name == "test-lock"

    async def test_acquire_returns_false_when_held(self) -> None:
        lock = InProcessLock("test-lock")
        await lock.acquire(timeout_seconds=1)
        # Second acquire on the same lock object should fail
        # (the underlying asyncio.Lock is already held)
        acquired = await lock.acquire(timeout_seconds=0)
        assert acquired is False

    async def test_release_returns_true_when_held(self) -> None:
        lock = InProcessLock("test-lock")
        await lock.acquire(timeout_seconds=1)
        released = await lock.release()
        assert released is True
        assert lock.is_held is False

    async def test_release_returns_false_when_not_held(self) -> None:
        lock = InProcessLock("test-lock")
        released = await lock.release()
        assert released is False

    async def test_acquire_after_release(self) -> None:
        lock = InProcessLock("test-lock")
        await lock.acquire(timeout_seconds=1)
        await lock.release()
        # Should be able to acquire again
        acquired = await lock.acquire(timeout_seconds=1)
        assert acquired is True

    async def test_competing_acquire_blocks_within_timeout(self) -> None:
        """Two tasks compete for the same lock: one wins, one blocks then gets it."""
        lock = InProcessLock("contended")

        results: list[str] = []

        async def task_a() -> None:
            acquired = await lock.acquire(timeout_seconds=1)
            assert acquired
            results.append("a_acquired")
            await asyncio.sleep(0.1)
            await lock.release()
            results.append("a_released")

        async def task_b() -> None:
            await asyncio.sleep(0.02)  # Let A acquire first
            acquired = await lock.acquire(timeout_seconds=2)
            assert acquired
            results.append("b_acquired")
            await lock.release()

        await asyncio.gather(task_a(), task_b())
        assert "a_acquired" in results
        assert "a_released" in results
        assert "b_acquired" in results
        # B must acquire after A releases
        assert results.index("a_released") < results.index("b_acquired")


class TestRedisDistributedLock:
    """RedisDistributedLock acquire/release semantics with FakeRedis."""

    async def test_acquire_returns_true_when_free(self) -> None:
        fake_redis = FakeRedis()
        lock = RedisDistributedLock(redis=fake_redis, name="test-lock", ttl_seconds=10)
        acquired = await lock.acquire()
        assert acquired is True
        assert lock.is_held is True
        assert lock.lock_name == "test-lock"

    async def test_competing_acquire_returns_false(self) -> None:
        """Two lock instances with the same name: first wins, second fails."""
        fake_redis = FakeRedis()
        lock_a = RedisDistributedLock(redis=fake_redis, name="shared-lock", ttl_seconds=10)
        lock_b = RedisDistributedLock(redis=fake_redis, name="shared-lock", ttl_seconds=10)

        assert await lock_a.acquire() is True
        assert await lock_b.acquire() is False
        assert lock_a.is_held is True
        assert lock_b.is_held is False

    async def test_release_clears_redis_key(self) -> None:
        fake_redis = FakeRedis()
        lock = RedisDistributedLock(redis=fake_redis, name="test-lock", ttl_seconds=10)
        await lock.acquire()
        assert "agent33:lock:test-lock" in fake_redis._store

        released = await lock.release()
        assert released is True
        assert lock.is_held is False
        assert "agent33:lock:test-lock" not in fake_redis._store

    async def test_release_returns_false_when_not_held(self) -> None:
        fake_redis = FakeRedis()
        lock = RedisDistributedLock(redis=fake_redis, name="test-lock", ttl_seconds=10)
        released = await lock.release()
        assert released is False

    async def test_acquire_after_release(self) -> None:
        fake_redis = FakeRedis()
        lock_a = RedisDistributedLock(redis=fake_redis, name="shared-lock", ttl_seconds=10)
        lock_b = RedisDistributedLock(redis=fake_redis, name="shared-lock", ttl_seconds=10)

        await lock_a.acquire()
        await lock_a.release()
        # Now lock_b should be able to acquire
        acquired = await lock_b.acquire()
        assert acquired is True

    async def test_lock_sets_ttl(self) -> None:
        fake_redis = FakeRedis()
        lock = RedisDistributedLock(redis=fake_redis, name="ttl-lock", ttl_seconds=42)
        await lock.acquire()

        assert len(fake_redis.set_calls) == 1
        assert fake_redis.set_calls[0]["ex"] == 42
        assert fake_redis.set_calls[0]["nx"] is True

    async def test_different_names_dont_conflict(self) -> None:
        fake_redis = FakeRedis()
        lock_a = RedisDistributedLock(redis=fake_redis, name="lock-a", ttl_seconds=10)
        lock_b = RedisDistributedLock(redis=fake_redis, name="lock-b", ttl_seconds=10)

        assert await lock_a.acquire() is True
        assert await lock_b.acquire() is True  # Different name, no conflict

    async def test_release_only_releases_own_token(self) -> None:
        """Lock B should not release Lock A's key when names are the same."""
        fake_redis = FakeRedis()
        lock_a = RedisDistributedLock(redis=fake_redis, name="shared", ttl_seconds=10)
        lock_b = RedisDistributedLock(redis=fake_redis, name="shared", ttl_seconds=10)

        await lock_a.acquire()
        # Lock B did not acquire, so release should return False
        released = await lock_b.release()
        assert released is False
        # Lock A should still be held in Redis
        assert "agent33:lock:shared" in fake_redis._store


class TestCreateLockFactory:
    """create_lock factory function."""

    def test_creates_redis_lock_with_redis(self) -> None:
        fake_redis = FakeRedis()
        lock = create_lock("test", redis=fake_redis, ttl_seconds=15)
        assert isinstance(lock, RedisDistributedLock)
        assert lock.lock_name == "test"

    def test_creates_inprocess_lock_without_redis(self) -> None:
        lock = create_lock("test", redis=None)
        assert isinstance(lock, InProcessLock)
        assert lock.lock_name == "test"


# ---------------------------------------------------------------------------
# State Guard Tests
# ---------------------------------------------------------------------------


class TestSingleInstanceGuard:
    """SingleInstanceGuard raises on conflict."""

    async def test_check_passes_with_one_instance(self) -> None:
        registry = InstanceRegistry(redis=None)
        await registry.register()
        guard = SingleInstanceGuard(registry, "test-surface")
        await guard.check()  # Should not raise

    async def test_check_raises_with_multiple_instances(self) -> None:
        """Simulate multiple instances detected by mocking count_live_instances."""
        registry = InstanceRegistry(redis=None)
        await registry.register()
        guard = SingleInstanceGuard(registry, "cron_scheduler")

        # Patch to simulate 2 instances
        with patch.object(registry, "count_live_instances", return_value=2):
            with pytest.raises(InstanceConflictError) as exc_info:
                await guard.check()

            error = exc_info.value
            assert error.surface == "cron_scheduler"
            assert error.instance_count == 2
            assert "single-instance ownership" in str(error)
            assert "P1.3+" in str(error)

    async def test_check_or_warn_returns_false_on_conflict(self) -> None:
        registry = InstanceRegistry(redis=None)
        await registry.register()
        guard = SingleInstanceGuard(registry, "test-surface")

        with patch.object(registry, "count_live_instances", return_value=3):
            result = await guard.check_or_warn()
            assert result is False

    async def test_check_or_warn_returns_true_no_conflict(self) -> None:
        registry = InstanceRegistry(redis=None)
        await registry.register()
        guard = SingleInstanceGuard(registry, "test-surface")
        result = await guard.check_or_warn()
        assert result is True


class TestInstanceConflictError:
    """InstanceConflictError formatting."""

    def test_error_message_includes_surface(self) -> None:
        error = InstanceConflictError(surface="auth_users", instance_count=2)
        assert "auth_users" in str(error)
        assert "2 instances" in str(error)

    def test_error_message_includes_details(self) -> None:
        error = InstanceConflictError(
            surface="webhook_delivery", instance_count=3, details="Redis key collision"
        )
        assert "webhook_delivery" in str(error)
        assert "3 instances" in str(error)
        assert "Redis key collision" in str(error)

    def test_error_attributes_preserved(self) -> None:
        error = InstanceConflictError(surface="scheduler", instance_count=5)
        assert error.surface == "scheduler"
        assert error.instance_count == 5
        assert error.details == ""


class TestSchedulerOwnershipGuard:
    """SchedulerOwnershipGuard prevents duplicate job execution."""

    async def test_acquire_ownership_succeeds_when_free(self) -> None:
        fake_redis = FakeRedis()
        lock = RedisDistributedLock(redis=fake_redis, name="sched", ttl_seconds=10)
        registry = InstanceRegistry(redis=None)
        await registry.register()
        guard = SchedulerOwnershipGuard(lock=lock, registry=registry, surface_name="scheduler")

        result = await guard.acquire_ownership()
        assert result is True

    async def test_acquire_ownership_fails_when_held(self) -> None:
        fake_redis = FakeRedis()
        lock_holder = RedisDistributedLock(redis=fake_redis, name="sched", ttl_seconds=10)
        lock_contender = RedisDistributedLock(redis=fake_redis, name="sched", ttl_seconds=10)

        # First instance acquires
        await lock_holder.acquire()

        registry = InstanceRegistry(redis=None)
        await registry.register()
        guard = SchedulerOwnershipGuard(
            lock=lock_contender, registry=registry, surface_name="scheduler"
        )

        result = await guard.acquire_ownership()
        assert result is False

    async def test_release_ownership(self) -> None:
        fake_redis = FakeRedis()
        lock = RedisDistributedLock(redis=fake_redis, name="sched", ttl_seconds=10)
        registry = InstanceRegistry(redis=None)
        await registry.register()
        guard = SchedulerOwnershipGuard(lock=lock, registry=registry)

        await guard.acquire_ownership()
        assert lock.is_held is True

        await guard.release_ownership()
        assert lock.is_held is False

    async def test_wrap_job_executes_when_lock_free(self) -> None:
        """Wrapped job should execute normally when the lock is free."""
        fake_redis = FakeRedis()
        lock = RedisDistributedLock(redis=fake_redis, name="job-exec", ttl_seconds=10)
        registry = InstanceRegistry(redis=None)
        await registry.register()
        guard = SchedulerOwnershipGuard(lock=lock, registry=registry)

        call_log: list[str] = []

        async def my_job(job_id: str) -> str:
            call_log.append(f"executed:{job_id}")
            return f"result:{job_id}"

        guarded_job = guard.wrap_job(my_job)
        result = await guarded_job("job-123")
        assert result == "result:job-123"
        assert call_log == ["executed:job-123"]

    async def test_wrap_job_skips_when_lock_held(self) -> None:
        """Wrapped job should be skipped when another holder has the lock."""
        fake_redis = FakeRedis()
        # Pre-acquire the lock to simulate another instance holding it
        holder = RedisDistributedLock(redis=fake_redis, name="job-exec", ttl_seconds=10)
        await holder.acquire()

        lock = RedisDistributedLock(redis=fake_redis, name="job-exec", ttl_seconds=10)
        registry = InstanceRegistry(redis=None)
        await registry.register()
        guard = SchedulerOwnershipGuard(lock=lock, registry=registry)

        call_log: list[str] = []

        async def my_job(job_id: str) -> str:
            call_log.append(f"executed:{job_id}")
            return f"result:{job_id}"

        guarded_job = guard.wrap_job(my_job)
        result = await guarded_job("job-123")
        assert result is None  # Job was skipped
        assert call_log == []  # Job was never called

    async def test_wrap_job_releases_lock_after_execution(self) -> None:
        """Lock should be released after job finishes, even if it raises."""
        fake_redis = FakeRedis()
        lock = RedisDistributedLock(redis=fake_redis, name="job-exec", ttl_seconds=10)
        registry = InstanceRegistry(redis=None)
        await registry.register()
        guard = SchedulerOwnershipGuard(lock=lock, registry=registry)

        async def failing_job() -> None:
            raise ValueError("job failed")

        guarded_job = guard.wrap_job(failing_job)
        with pytest.raises(ValueError, match="job failed"):
            await guarded_job()

        # Lock should be released even after exception
        assert lock.is_held is False

    async def test_wrap_job_releases_lock_after_success(self) -> None:
        """Lock should be released after successful job execution."""
        fake_redis = FakeRedis()
        lock = RedisDistributedLock(redis=fake_redis, name="job-exec", ttl_seconds=10)
        registry = InstanceRegistry(redis=None)
        await registry.register()
        guard = SchedulerOwnershipGuard(lock=lock, registry=registry)

        async def good_job() -> str:
            return "done"

        guarded_job = guard.wrap_job(good_job)
        result = await guarded_job()
        assert result == "done"
        assert lock.is_held is False

    async def test_wrap_preserves_function_name(self) -> None:
        """Wrapped function should preserve the original function name."""
        lock = InProcessLock("test")
        registry = InstanceRegistry(redis=None)
        await registry.register()
        guard = SchedulerOwnershipGuard(lock=lock, registry=registry)

        async def my_specific_job() -> None:
            pass

        wrapped = guard.wrap_job(my_specific_job)
        assert wrapped.__name__ == "my_specific_job"


class TestSchedulerLockPreventsDuplicateRegistration:
    """Integration test: two guards competing for the same scheduler surface."""

    async def test_only_one_guard_acquires(self) -> None:
        fake_redis = FakeRedis()
        registry_a = InstanceRegistry(redis=fake_redis)
        registry_b = InstanceRegistry(redis=fake_redis)
        await registry_a.register()
        await registry_b.register()

        lock_a = RedisDistributedLock(redis=fake_redis, name="scheduler", ttl_seconds=30)
        lock_b = RedisDistributedLock(redis=fake_redis, name="scheduler", ttl_seconds=30)

        guard_a = SchedulerOwnershipGuard(lock=lock_a, registry=registry_a)
        guard_b = SchedulerOwnershipGuard(lock=lock_b, registry=registry_b)

        result_a = await guard_a.acquire_ownership()
        result_b = await guard_b.acquire_ownership()

        assert result_a is True
        assert result_b is False  # Second instance denied

    async def test_second_acquires_after_first_releases(self) -> None:
        fake_redis = FakeRedis()
        registry_a = InstanceRegistry(redis=fake_redis)
        registry_b = InstanceRegistry(redis=fake_redis)
        await registry_a.register()
        await registry_b.register()

        lock_a = RedisDistributedLock(redis=fake_redis, name="scheduler", ttl_seconds=30)
        lock_b = RedisDistributedLock(redis=fake_redis, name="scheduler", ttl_seconds=30)

        guard_a = SchedulerOwnershipGuard(lock=lock_a, registry=registry_a)
        guard_b = SchedulerOwnershipGuard(lock=lock_b, registry=registry_b)

        # A acquires
        assert await guard_a.acquire_ownership() is True
        assert await guard_b.acquire_ownership() is False

        # A releases
        await guard_a.release_ownership()

        # Now B can acquire
        assert await guard_b.acquire_ownership() is True


class TestInProcessLockFallback:
    """Verify InProcessLock works when Redis is unavailable."""

    async def test_distributed_lock_falls_back_to_inprocess(self) -> None:
        lock = create_lock("fallback-test", redis=None)
        assert isinstance(lock, InProcessLock)

        acquired = await lock.acquire(timeout_seconds=1)
        assert acquired is True

        released = await lock.release()
        assert released is True

    async def test_inprocess_lock_with_scheduler_guard(self) -> None:
        """Full flow: InProcessLock + SchedulerOwnershipGuard + job wrapping."""
        lock = InProcessLock("scheduler")
        registry = InstanceRegistry(redis=None)
        await registry.register()
        guard = SchedulerOwnershipGuard(lock=lock, registry=registry)

        assert await guard.acquire_ownership() is True

        call_log: list[str] = []

        async def scheduled_task(task_name: str) -> str:
            call_log.append(task_name)
            return f"completed:{task_name}"

        # Release ownership first so wrap_job can re-acquire per-job
        await guard.release_ownership()

        guarded = guard.wrap_job(scheduled_task)
        result = await guarded("evaluation-gate")
        assert result == "completed:evaluation-gate"
        assert call_log == ["evaluation-gate"]
