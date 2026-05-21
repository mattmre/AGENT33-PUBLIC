"""Tests for P2.4 shared conversation-memory namespace layer.

All Redis and DistributedLock interactions are mocked -- no running Redis
instance is required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent33.memory.shared_memory import (
    _SHARED_MEMORY_PREFIX,
    _WRITE_LOCK_TTL_SECONDS,
    SharedMemoryNamespace,
)
from agent33.memory.shared_memory_service import SharedMemoryService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_redis() -> AsyncMock:
    """Return a fully mocked async Redis client."""
    redis = AsyncMock()
    # Default scan returns empty on first call
    redis.scan.return_value = (0, [])
    redis.get.return_value = None
    redis.set.return_value = True
    redis.delete.return_value = 1
    return redis


@pytest.fixture()
def namespace(mock_redis: AsyncMock) -> SharedMemoryNamespace:
    """A session-shared namespace for tenant ``t1``."""
    return SharedMemoryNamespace(
        redis=mock_redis,
        tenant_id="t1",
        namespace="session/sess-abc/shared",
    )


# ===========================================================================
# SharedMemoryNamespace -- full_key
# ===========================================================================


class TestFullKey:
    def test_full_key_includes_tenant_namespace_and_key(
        self, namespace: SharedMemoryNamespace
    ) -> None:
        result = namespace.full_key("plan")
        assert result == f"{_SHARED_MEMORY_PREFIX}t1/session/sess-abc/shared/plan"

    def test_full_key_different_tenant_produces_different_key(self, mock_redis: AsyncMock) -> None:
        ns1 = SharedMemoryNamespace(redis=mock_redis, tenant_id="t1", namespace="global")
        ns2 = SharedMemoryNamespace(redis=mock_redis, tenant_id="t2", namespace="global")
        assert ns1.full_key("x") != ns2.full_key("x")
        assert "t1" in ns1.full_key("x")
        assert "t2" in ns2.full_key("x")

    def test_full_key_different_namespace_produces_different_key(
        self, mock_redis: AsyncMock
    ) -> None:
        ns1 = SharedMemoryNamespace(
            redis=mock_redis, tenant_id="t1", namespace="session/s1/shared"
        )
        ns2 = SharedMemoryNamespace(
            redis=mock_redis, tenant_id="t1", namespace="agent/code-worker"
        )
        assert ns1.full_key("k") != ns2.full_key("k")

    def test_full_key_with_slashes_in_key(self, namespace: SharedMemoryNamespace) -> None:
        """Keys may contain slashes (e.g. hierarchical sub-keys)."""
        result = namespace.full_key("step/1/output")
        assert result.endswith("step/1/output")


# ===========================================================================
# SharedMemoryNamespace -- read
# ===========================================================================


class TestRead:
    async def test_read_calls_redis_get_with_full_key(
        self, namespace: SharedMemoryNamespace, mock_redis: AsyncMock
    ) -> None:
        mock_redis.get.return_value = b"hello"
        result = await namespace.read("greeting")
        mock_redis.get.assert_awaited_once_with(namespace.full_key("greeting"))
        assert result == "hello"

    async def test_read_returns_none_when_key_missing(
        self, namespace: SharedMemoryNamespace, mock_redis: AsyncMock
    ) -> None:
        mock_redis.get.return_value = None
        result = await namespace.read("no-such-key")
        assert result is None

    async def test_read_decodes_bytes_to_str(
        self, namespace: SharedMemoryNamespace, mock_redis: AsyncMock
    ) -> None:
        mock_redis.get.return_value = b"\xc3\xa9l\xc3\xa8ve"  # "eleve" with accents
        result = await namespace.read("utf8-val")
        assert isinstance(result, str)

    async def test_read_handles_non_bytes_return(
        self, namespace: SharedMemoryNamespace, mock_redis: AsyncMock
    ) -> None:
        """Some Redis configs return str directly."""
        mock_redis.get.return_value = "already-a-string"
        result = await namespace.read("str-val")
        assert result == "already-a-string"


# ===========================================================================
# SharedMemoryNamespace -- write
# ===========================================================================


class TestWrite:
    async def test_write_acquires_lock_and_sets_value(
        self, namespace: SharedMemoryNamespace, mock_redis: AsyncMock
    ) -> None:
        # Mock the lock acquire and release
        mock_redis.set.return_value = True  # lock SETNX + data SET
        mock_redis.eval.return_value = 1  # lock release Lua script

        await namespace.write("plan", "do the thing")

        # The SET calls include the lock SETNX and the data write.
        # Verify the data write happened with correct key and value.
        data_key = namespace.full_key("plan")
        data_set_found = False
        for call in mock_redis.set.await_args_list:
            args, kwargs = call
            if args[0] == data_key and args[1] == "do the thing":
                data_set_found = True
                # No TTL means no 'ex' kwarg
                assert "ex" not in kwargs or kwargs.get("ex") is None
                break
        assert data_set_found, f"Expected SET on {data_key} not found in calls"

    async def test_write_with_ttl_passes_ex_to_redis(
        self, namespace: SharedMemoryNamespace, mock_redis: AsyncMock
    ) -> None:
        mock_redis.set.return_value = True
        mock_redis.eval.return_value = 1

        await namespace.write("ephemeral", "temp", ttl_seconds=60)

        data_key = namespace.full_key("ephemeral")
        ttl_found = False
        for call in mock_redis.set.await_args_list:
            args, kwargs = call
            if args[0] == data_key:
                assert kwargs.get("ex") == 60
                ttl_found = True
                break
        assert ttl_found, "Expected SET with ex=60 not found"

    async def test_write_without_ttl_omits_ex(
        self, namespace: SharedMemoryNamespace, mock_redis: AsyncMock
    ) -> None:
        mock_redis.set.return_value = True
        mock_redis.eval.return_value = 1

        await namespace.write("persistent", "stays forever")

        data_key = namespace.full_key("persistent")
        for call in mock_redis.set.await_args_list:
            args, kwargs = call
            if args[0] == data_key:
                # Should have been called without ex kwarg
                assert "ex" not in kwargs
                return
        pytest.fail(f"No SET call found for {data_key}")

    async def test_write_raises_when_lock_not_acquired(
        self, namespace: SharedMemoryNamespace, mock_redis: AsyncMock
    ) -> None:
        """If the distributed lock cannot be acquired, raise RuntimeError."""
        mock_redis.set.return_value = False  # SETNX fails (lock held by another)

        with pytest.raises(RuntimeError, match="Failed to acquire write lock"):
            await namespace.write("contested", "value")

    async def test_write_releases_lock_even_on_error(
        self, namespace: SharedMemoryNamespace, mock_redis: AsyncMock
    ) -> None:
        """Lock is released in a finally block even if the SET raises."""
        call_count = 0

        async def set_side_effect(*args: object, **kwargs: object) -> bool:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call is the lock SETNX -- succeed
                return True
            # Second call is the data SET -- explode
            raise ConnectionError("Redis went away")

        mock_redis.set.side_effect = set_side_effect
        mock_redis.eval.return_value = 1  # lock release succeeds

        with pytest.raises(ConnectionError, match="Redis went away"):
            await namespace.write("bad-key", "val")

        # Lock release (eval) should still have been called
        mock_redis.eval.assert_awaited()

    async def test_write_uses_correct_lock_ttl(self, mock_redis: AsyncMock) -> None:
        """The distributed lock must use the module-level _WRITE_LOCK_TTL_SECONDS."""
        ns = SharedMemoryNamespace(redis=mock_redis, tenant_id="t1", namespace="global")
        mock_redis.set.return_value = True
        mock_redis.eval.return_value = 1

        with patch(
            "agent33.memory.shared_memory.RedisDistributedLock",
            wraps=MagicMock,
        ) as mock_lock_cls:
            lock_instance = AsyncMock()
            lock_instance.acquire.return_value = True
            lock_instance.release.return_value = True
            mock_lock_cls.return_value = lock_instance

            await ns.write("k", "v")

            mock_lock_cls.assert_called_once()
            _, kwargs = mock_lock_cls.call_args
            assert kwargs["ttl_seconds"] == _WRITE_LOCK_TTL_SECONDS


# ===========================================================================
# SharedMemoryNamespace -- delete
# ===========================================================================


class TestDelete:
    async def test_delete_calls_redis_delete(
        self, namespace: SharedMemoryNamespace, mock_redis: AsyncMock
    ) -> None:
        await namespace.delete("old-key")
        mock_redis.delete.assert_awaited_once_with(namespace.full_key("old-key"))


# ===========================================================================
# SharedMemoryNamespace -- list_keys
# ===========================================================================


class TestListKeys:
    async def test_list_keys_returns_relative_keys(
        self, namespace: SharedMemoryNamespace, mock_redis: AsyncMock
    ) -> None:
        prefix = f"{_SHARED_MEMORY_PREFIX}t1/session/sess-abc/shared/"
        mock_redis.scan.return_value = (
            0,
            [
                f"{prefix}plan".encode(),
                f"{prefix}findings".encode(),
            ],
        )
        result = await namespace.list_keys()
        assert sorted(result) == ["findings", "plan"]

    async def test_list_keys_with_prefix_filter(
        self, namespace: SharedMemoryNamespace, mock_redis: AsyncMock
    ) -> None:
        prefix = f"{_SHARED_MEMORY_PREFIX}t1/session/sess-abc/shared/"
        mock_redis.scan.return_value = (
            0,
            [f"{prefix}step/1".encode(), f"{prefix}step/2".encode()],
        )
        result = await namespace.list_keys(prefix="step/")
        # Verify the SCAN pattern includes the prefix
        call_args = mock_redis.scan.await_args
        assert call_args is not None
        _, kwargs = call_args
        assert "step/" in kwargs["match"]
        assert len(result) == 2

    async def test_list_keys_handles_multiple_scan_pages(
        self, namespace: SharedMemoryNamespace, mock_redis: AsyncMock
    ) -> None:
        prefix = f"{_SHARED_MEMORY_PREFIX}t1/session/sess-abc/shared/"
        # First page returns cursor=42, second page returns cursor=0 (done)
        mock_redis.scan.side_effect = [
            (42, [f"{prefix}a".encode()]),
            (0, [f"{prefix}b".encode()]),
        ]
        result = await namespace.list_keys()
        assert sorted(result) == ["a", "b"]
        assert mock_redis.scan.await_count == 2

    async def test_list_keys_empty_namespace(
        self, namespace: SharedMemoryNamespace, mock_redis: AsyncMock
    ) -> None:
        mock_redis.scan.return_value = (0, [])
        result = await namespace.list_keys()
        assert result == []


# ===========================================================================
# SharedMemoryNamespace -- properties
# ===========================================================================


class TestProperties:
    def test_tenant_id_property(self, namespace: SharedMemoryNamespace) -> None:
        assert namespace.tenant_id == "t1"

    def test_namespace_property(self, namespace: SharedMemoryNamespace) -> None:
        assert namespace.namespace == "session/sess-abc/shared"


# ===========================================================================
# Key isolation
# ===========================================================================


class TestKeyIsolation:
    def test_different_tenants_produce_different_full_keys(self, mock_redis: AsyncMock) -> None:
        ns_a = SharedMemoryNamespace(
            redis=mock_redis, tenant_id="tenant-alpha", namespace="global"
        )
        ns_b = SharedMemoryNamespace(redis=mock_redis, tenant_id="tenant-beta", namespace="global")
        assert ns_a.full_key("same-key") != ns_b.full_key("same-key")
        assert "tenant-alpha" in ns_a.full_key("same-key")
        assert "tenant-beta" in ns_b.full_key("same-key")

    def test_different_namespaces_produce_different_full_keys(self, mock_redis: AsyncMock) -> None:
        ns_session = SharedMemoryNamespace(
            redis=mock_redis, tenant_id="t1", namespace="session/s1/shared"
        )
        ns_agent = SharedMemoryNamespace(
            redis=mock_redis, tenant_id="t1", namespace="agent/code-worker"
        )
        ns_global = SharedMemoryNamespace(redis=mock_redis, tenant_id="t1", namespace="global")
        key = "status"
        keys = {
            ns_session.full_key(key),
            ns_agent.full_key(key),
            ns_global.full_key(key),
        }
        assert len(keys) == 3, "Each namespace must produce a unique full key"

    def test_same_tenant_same_namespace_same_key_produces_identical_full_key(
        self, mock_redis: AsyncMock
    ) -> None:
        ns1 = SharedMemoryNamespace(redis=mock_redis, tenant_id="t1", namespace="global")
        ns2 = SharedMemoryNamespace(redis=mock_redis, tenant_id="t1", namespace="global")
        assert ns1.full_key("k") == ns2.full_key("k")


# ===========================================================================
# SharedMemoryService
# ===========================================================================


class TestSharedMemoryService:
    async def test_get_session_namespace_returns_correct_pattern(self) -> None:
        svc = SharedMemoryService(redis_url="redis://localhost:6379/0")
        mock_redis = AsyncMock()
        svc._redis = mock_redis  # inject mock

        ns = await svc.get_session_namespace("t1", "sess-xyz")
        assert ns.tenant_id == "t1"
        assert ns.namespace == "session/sess-xyz/shared"

    async def test_get_agent_namespace_returns_correct_pattern(self) -> None:
        svc = SharedMemoryService(redis_url="redis://localhost:6379/0")
        svc._redis = AsyncMock()

        ns = await svc.get_agent_namespace("t1", "code-worker-01")
        assert ns.tenant_id == "t1"
        assert ns.namespace == "agent/code-worker-01"

    async def test_get_global_namespace_returns_correct_pattern(self) -> None:
        svc = SharedMemoryService(redis_url="redis://localhost:6379/0")
        svc._redis = AsyncMock()

        ns = await svc.get_global_namespace("t1")
        assert ns.tenant_id == "t1"
        assert ns.namespace == "global"

    async def test_get_namespace_raises_when_redis_not_initialised(self) -> None:
        svc = SharedMemoryService(redis_url="redis://localhost:6379/0")
        with pytest.raises(RuntimeError, match="Redis client not initialised"):
            svc.get_namespace("t1", "global")

    async def test_get_namespace_returns_namespace_when_redis_available(self) -> None:
        svc = SharedMemoryService(redis_url="redis://localhost:6379/0")
        svc._redis = AsyncMock()

        ns = svc.get_namespace("t1", "session/s1/shared")
        assert ns.tenant_id == "t1"
        assert ns.namespace == "session/s1/shared"

    async def test_close_calls_redis_aclose(self) -> None:
        svc = SharedMemoryService(redis_url="redis://localhost:6379/0")
        mock_redis = AsyncMock()
        svc._redis = mock_redis

        await svc.close()
        mock_redis.aclose.assert_awaited_once()
        assert svc._redis is None

    async def test_close_is_safe_when_redis_not_initialised(self) -> None:
        svc = SharedMemoryService(redis_url="redis://localhost:6379/0")
        # Should not raise
        await svc.close()

    async def test_ensure_redis_lazy_init(self) -> None:
        """_ensure_redis returns the same client on repeated calls."""
        svc = SharedMemoryService(redis_url="redis://localhost:6379/0")
        fake_client = AsyncMock()
        # Patch the from_url at the module level that _ensure_redis calls
        with patch("redis.asyncio.from_url", return_value=fake_client) as mock_from_url:
            client1 = await svc._ensure_redis()
            client2 = await svc._ensure_redis()

        # from_url should have been called exactly once (lazy init)
        mock_from_url.assert_called_once_with("redis://localhost:6379/0", decode_responses=False)
        assert client1 is client2 is fake_client

    async def test_session_namespace_redis_is_same_client(self) -> None:
        """All namespace handles share the same Redis client."""
        svc = SharedMemoryService(redis_url="redis://localhost:6379/0")
        mock_redis = AsyncMock()
        svc._redis = mock_redis

        ns1 = await svc.get_session_namespace("t1", "s1")
        ns2 = await svc.get_agent_namespace("t1", "agent-1")
        ns3 = await svc.get_global_namespace("t1")

        assert ns1._redis is ns2._redis is ns3._redis is mock_redis
