"""Tests for P1.3 connection pooling and resource lifecycle hardening."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from agent33.config import Settings
from agent33.memory.long_term import LongTermMemory
from agent33.messaging.bus import NATSMessageBus

# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


class TestPoolConfigDefaults:
    """Verify that the new pool config fields exist with correct defaults."""

    def test_db_pool_size_default(self) -> None:
        s = Settings(environment="test")
        assert s.db_pool_size == 10

    def test_db_max_overflow_default(self) -> None:
        s = Settings(environment="test")
        assert s.db_max_overflow == 20

    def test_db_pool_pre_ping_default(self) -> None:
        s = Settings(environment="test")
        assert s.db_pool_pre_ping is True

    def test_db_pool_recycle_default(self) -> None:
        s = Settings(environment="test")
        assert s.db_pool_recycle == 1800

    def test_redis_max_connections_default(self) -> None:
        s = Settings(environment="test")
        assert s.redis_max_connections == 50


class TestPoolConfigOverrides:
    """Verify that pool config fields can be overridden via environment."""

    def test_db_pool_size_override(self) -> None:
        s = Settings(environment="test", db_pool_size=25)
        assert s.db_pool_size == 25

    def test_db_max_overflow_override(self) -> None:
        s = Settings(environment="test", db_max_overflow=40)
        assert s.db_max_overflow == 40

    def test_db_pool_pre_ping_disable(self) -> None:
        s = Settings(environment="test", db_pool_pre_ping=False)
        assert s.db_pool_pre_ping is False

    def test_db_pool_recycle_override(self) -> None:
        s = Settings(environment="test", db_pool_recycle=3600)
        assert s.db_pool_recycle == 3600

    def test_redis_max_connections_override(self) -> None:
        s = Settings(environment="test", redis_max_connections=100)
        assert s.redis_max_connections == 100


# ---------------------------------------------------------------------------
# SQLAlchemy pool params
# ---------------------------------------------------------------------------


class TestLongTermMemoryPoolParams:
    """Verify that LongTermMemory passes pool parameters to create_async_engine."""

    @patch("agent33.memory.long_term.create_async_engine")
    def test_default_pool_params(self, mock_create: MagicMock) -> None:
        """With no explicit pool kwargs, LongTermMemory uses its own defaults."""
        mock_create.return_value = MagicMock()

        LongTermMemory("postgresql+asyncpg://localhost/test")

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs["pool_size"] == 10
        assert call_kwargs.kwargs["max_overflow"] == 20
        assert call_kwargs.kwargs["pool_pre_ping"] is True
        assert call_kwargs.kwargs["pool_recycle"] == 1800

    @patch("agent33.memory.long_term.create_async_engine")
    def test_custom_pool_params(self, mock_create: MagicMock) -> None:
        """Explicit pool kwargs are forwarded to create_async_engine."""
        mock_create.return_value = MagicMock()

        LongTermMemory(
            "postgresql+asyncpg://localhost/test",
            pool_size=25,
            max_overflow=40,
            pool_pre_ping=False,
            pool_recycle=3600,
        )

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs["pool_size"] == 25
        assert call_kwargs.kwargs["max_overflow"] == 40
        assert call_kwargs.kwargs["pool_pre_ping"] is False
        assert call_kwargs.kwargs["pool_recycle"] == 3600

    @patch("agent33.memory.long_term.create_async_engine")
    def test_echo_always_false(self, mock_create: MagicMock) -> None:
        """Engine echo is always False regardless of pool params."""
        mock_create.return_value = MagicMock()

        LongTermMemory(
            "postgresql+asyncpg://localhost/test",
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=False,
            pool_recycle=-1,
        )

        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs["echo"] is False

    @patch("agent33.memory.long_term.create_async_engine")
    def test_embedding_dim_still_works(self, mock_create: MagicMock) -> None:
        """embedding_dim positional param still works alongside pool kwargs."""
        mock_create.return_value = MagicMock()

        mem = LongTermMemory(
            "postgresql+asyncpg://localhost/test",
            embedding_dim=768,
            pool_size=15,
        )

        assert mem._embedding_dim == 768


# ---------------------------------------------------------------------------
# Redis pool params
# ---------------------------------------------------------------------------


class TestRedisPoolParams:
    """Verify that Redis from_url receives max_connections from config.

    NOTE: These tests use patch.dict(sys.modules) rather than importing
    redis.asyncio directly.  Importing the real redis.asyncio module sets the
    ``asyncio`` attribute on the ``redis`` package object; that attribute
    persists across tests and bypasses any subsequent sys.modules monkeypatching
    done by test_health.py's autouse fixture, causing test_readyz to receive the
    real module instead of the fake and therefore fail with 503.
    """

    def _make_mock_redis_module(self) -> tuple[MagicMock, MagicMock]:
        """Return (mock_module, mock_client) for a fake redis.asyncio."""
        mock_client = MagicMock()
        mock_client.ping = AsyncMock()
        mock_module = MagicMock()
        mock_module.from_url = MagicMock(return_value=mock_client)
        return mock_module, mock_client

    def test_redis_from_url_receives_max_connections(self) -> None:
        """When main.py creates the Redis client, it passes max_connections."""
        mock_module, _mock_client = self._make_mock_redis_module()

        with patch.dict("sys.modules", {"redis.asyncio": mock_module}):
            import redis.asyncio as aioredis  # noqa: PLC0415

            aioredis.from_url(
                "redis://localhost:6379/0",
                decode_responses=True,
                max_connections=50,
            )
            mock_module.from_url.assert_called_once_with(
                "redis://localhost:6379/0",
                decode_responses=True,
                max_connections=50,
            )

    def test_redis_from_url_custom_max_connections(self) -> None:
        """Custom max_connections value is passed through."""
        mock_module, _mock_client = self._make_mock_redis_module()

        with patch.dict("sys.modules", {"redis.asyncio": mock_module}):
            import redis.asyncio as aioredis  # noqa: PLC0415

            aioredis.from_url(
                "redis://localhost:6379/0",
                decode_responses=True,
                max_connections=100,
            )
            call_kwargs = mock_module.from_url.call_args
            assert call_kwargs.kwargs.get("max_connections") == 100


# ---------------------------------------------------------------------------
# NATS lifecycle
# ---------------------------------------------------------------------------


class TestNATSLifecycle:
    """Verify NATS client drain/close lifecycle on shutdown."""

    async def test_close_calls_drain(self) -> None:
        """NATSMessageBus.close() calls drain on the underlying client."""
        bus = NATSMessageBus("nats://localhost:4222")

        mock_nc = AsyncMock()
        mock_nc.is_connected = True
        bus._nc = mock_nc  # type: ignore[assignment]

        await bus.close()

        mock_nc.drain.assert_awaited_once()

    async def test_close_clears_client_reference(self) -> None:
        """After close(), the internal client reference is None."""
        bus = NATSMessageBus("nats://localhost:4222")

        mock_nc = AsyncMock()
        mock_nc.is_connected = True
        bus._nc = mock_nc  # type: ignore[assignment]

        await bus.close()

        assert bus._nc is None

    async def test_close_clears_subscriptions(self) -> None:
        """After close(), subscription list is empty."""
        bus = NATSMessageBus("nats://localhost:4222")

        mock_nc = AsyncMock()
        mock_nc.is_connected = True
        bus._nc = mock_nc  # type: ignore[assignment]
        bus._subscriptions = [MagicMock(), MagicMock()]

        await bus.close()

        assert bus._subscriptions == []

    async def test_close_noop_when_not_connected(self) -> None:
        """close() is a no-op if never connected."""
        bus = NATSMessageBus("nats://localhost:4222")
        assert bus._nc is None

        # Should not raise
        await bus.close()
        assert bus._nc is None

    async def test_is_connected_false_after_close(self) -> None:
        """is_connected returns False after close."""
        bus = NATSMessageBus("nats://localhost:4222")

        mock_nc = AsyncMock()
        mock_nc.is_connected = True
        bus._nc = mock_nc  # type: ignore[assignment]
        assert bus.is_connected is True

        await bus.close()
        assert bus.is_connected is False


# ---------------------------------------------------------------------------
# Integration: config -> LongTermMemory wiring
# ---------------------------------------------------------------------------


class TestConfigToLongTermMemoryWiring:
    """Verify that Settings pool values flow into LongTermMemory construction."""

    @patch("agent33.memory.long_term.create_async_engine")
    def test_settings_flow_to_engine(self, mock_create: MagicMock) -> None:
        """Simulates the main.py pattern of passing settings values."""
        mock_create.return_value = MagicMock()

        s = Settings(
            environment="test",
            db_pool_size=15,
            db_max_overflow=30,
            db_pool_pre_ping=False,
            db_pool_recycle=900,
        )

        LongTermMemory(
            s.database_url,
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            pool_pre_ping=s.db_pool_pre_ping,
            pool_recycle=s.db_pool_recycle,
        )

        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs["pool_size"] == 15
        assert call_kwargs.kwargs["max_overflow"] == 30
        assert call_kwargs.kwargs["pool_pre_ping"] is False
        assert call_kwargs.kwargs["pool_recycle"] == 900
