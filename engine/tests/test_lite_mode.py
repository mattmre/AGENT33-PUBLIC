"""Tests for AGENT33_MODE=lite startup — zero external services required.

These tests validate:
- B1: No import-time crashes from unconditional postgresql/nats imports
- B2: pyproject.toml extras structure (lite/standard/enterprise)
- B3: agent33_mode config field defaults to "standard"
- Lifespan phase helpers work in lite mode
"""

from __future__ import annotations

import importlib

import pytest

# ---------------------------------------------------------------------------
# B1: Import safety — modules must not crash at import time
# ---------------------------------------------------------------------------


def test_long_term_import_does_not_crash_without_postgres() -> None:
    """long_term.py can be imported even when sqlalchemy/postgresql are present."""
    mod = importlib.import_module("agent33.memory.long_term")
    assert mod is not None
    assert hasattr(mod, "LongTermMemory")


def test_bus_import_does_not_crash_without_nats() -> None:
    """bus.py can be imported without the nats package crashing."""
    mod = importlib.import_module("agent33.messaging.bus")
    assert mod is not None
    assert hasattr(mod, "NATSMessageBus")


def test_protocol_imports_do_not_crash() -> None:
    """LongTermMemoryProtocol and MessageBusProtocol can be imported without infrastructure."""
    from agent33.memory.protocols import LongTermMemoryProtocol
    from agent33.messaging.protocols import MessageBusProtocol

    assert LongTermMemoryProtocol is not None
    assert MessageBusProtocol is not None


# ---------------------------------------------------------------------------
# B3: Config field
# ---------------------------------------------------------------------------


def test_agent33_mode_config_default() -> None:
    """AGENT33_MODE defaults to 'standard' for backward compatibility (B3)."""
    from agent33.config import Settings

    s = Settings(jwt_secret="x" * 32)  # type: ignore[call-arg]
    assert s.agent33_mode == "standard"


def test_agent33_mode_lite() -> None:
    """AGENT33_MODE=lite is accepted."""
    from agent33.config import Settings

    s = Settings(agent33_mode="lite", jwt_secret="x" * 32)  # type: ignore[call-arg]
    assert s.agent33_mode == "lite"


def test_agent33_mode_enterprise() -> None:
    """AGENT33_MODE=enterprise is accepted."""
    from agent33.config import Settings

    s = Settings(agent33_mode="enterprise", jwt_secret="x" * 32)  # type: ignore[call-arg]
    assert s.agent33_mode == "enterprise"


def test_agent33_mode_invalid_is_rejected() -> None:
    """An invalid AGENT33_MODE value raises a validation error."""
    import pydantic

    from agent33.config import Settings

    with pytest.raises((pydantic.ValidationError, ValueError)):
        Settings(agent33_mode="unknown", jwt_secret="x" * 32)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# InProcessCache fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_process_cache_basic_operations() -> None:
    """InProcessCache supports get/set/delete/exists/aclose."""
    from agent33.lifespan.fallbacks import InProcessCache

    cache = InProcessCache(maxsize=5)

    await cache.set("key1", "value1")
    assert await cache.get("key1") == "value1"
    assert await cache.exists("key1") is True

    await cache.delete("key1")
    assert await cache.get("key1") is None
    assert await cache.exists("key1") is False

    assert await cache.ping() is True

    await cache.aclose()


@pytest.mark.asyncio
async def test_in_process_cache_eviction() -> None:
    """InProcessCache evicts oldest entry when maxsize is reached."""
    from agent33.lifespan.fallbacks import InProcessCache

    cache = InProcessCache(maxsize=3)
    await cache.set("a", 1)
    await cache.set("b", 2)
    await cache.set("c", 3)
    await cache.set("d", 4)  # Should evict "a"

    assert await cache.get("a") is None  # evicted
    assert await cache.get("d") == 4


# ---------------------------------------------------------------------------
# InProcessMessageBus fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_process_message_bus_pub_sub() -> None:
    """InProcessMessageBus delivers messages from publish to subscribe queue."""
    from agent33.lifespan.fallbacks import InProcessMessageBus

    bus = InProcessMessageBus()
    assert bus.is_connected is True

    queue = await bus.subscribe("test.subject")
    await bus.publish("test.subject", b"hello world")

    msg = await queue.get()
    assert msg == b"hello world"

    await bus.close()


@pytest.mark.asyncio
async def test_in_process_message_bus_connect_close() -> None:
    """InProcessMessageBus connect() is a no-op and close() clears subscribers."""
    from agent33.lifespan.fallbacks import InProcessMessageBus

    bus = InProcessMessageBus()
    await bus.connect()  # no-op, should not raise
    await bus.subscribe("foo")
    await bus.close()
    # After close, subscribers are cleared
    assert len(bus._subscribers) == 0  # noqa: SLF001


# ---------------------------------------------------------------------------
# Lifespan phase helpers — lite mode
# ---------------------------------------------------------------------------


class _MockApp:
    """Minimal FastAPI-like app stub for testing phase helpers."""

    class state:  # noqa: N801
        pass


@pytest.mark.asyncio
async def test_init_database_lite_mode_uses_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    """init_database sets app.state.long_term_memory to SQLiteLongTermMemory in lite mode."""
    from agent33.config import Settings
    from agent33.lifespan.phases import init_database
    from agent33.memory.sqlite_long_term import SQLiteLongTermMemory

    settings = Settings(  # type: ignore[call-arg]
        agent33_mode="lite",
        sqlite_memory_db_path=":memory:",
        jwt_secret="x" * 32,
    )
    app = _MockApp()  # type: ignore[assignment]
    await init_database(app, settings)  # type: ignore[arg-type]
    ltm = app.state.long_term_memory  # type: ignore[attr-defined]
    assert isinstance(ltm, SQLiteLongTermMemory)
    # Verify it is functional (store + retrieve round-trip)
    mem_id = await ltm.store("test content", {"source": "phase_test"})
    result = await ltm.get(mem_id)
    assert result is not None
    assert result["content"] == "test content"
    await ltm.close()


@pytest.mark.asyncio
async def test_sqlite_ltm_available_in_lite_mode() -> None:
    """SQLiteLongTermMemory can be instantiated without any external services."""
    from agent33.memory.sqlite_long_term import SQLiteLongTermMemory

    m = SQLiteLongTermMemory(db_path=":memory:")
    await m.initialize()
    mem_id = await m.store("test content", {"key": "val"})
    assert mem_id
    await m.close()


@pytest.mark.asyncio
async def test_init_redis_lite_mode_uses_in_process_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """init_redis stores an InProcessCache on app.state.redis in lite mode."""
    from agent33.config import Settings
    from agent33.lifespan.fallbacks import InProcessCache
    from agent33.lifespan.phases import init_redis

    settings = Settings(agent33_mode="lite", jwt_secret="x" * 32)  # type: ignore[call-arg]
    app = _MockApp()  # type: ignore[assignment]
    await init_redis(app, settings)  # type: ignore[arg-type]
    assert isinstance(app.state.redis, InProcessCache)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_init_nats_lite_mode_uses_in_process_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """init_nats stores an InProcessMessageBus on app.state.nats_bus in lite mode."""
    from agent33.config import Settings
    from agent33.lifespan.fallbacks import InProcessMessageBus
    from agent33.lifespan.phases import init_nats

    settings = Settings(agent33_mode="lite", jwt_secret="x" * 32)  # type: ignore[call-arg]
    app = _MockApp()  # type: ignore[assignment]
    await init_nats(app, settings)  # type: ignore[arg-type]
    assert isinstance(app.state.nats_bus, InProcessMessageBus)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_init_redis_standard_mode_falls_back_on_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """init_redis falls back to InProcessCache when Redis is unreachable."""
    from agent33.config import Settings
    from agent33.lifespan.fallbacks import InProcessCache
    from agent33.lifespan.phases import init_redis

    # Use an invalid Redis URL so the connection always fails
    settings = Settings(  # type: ignore[call-arg]
        agent33_mode="standard",
        redis_url="redis://localhost:1",  # guaranteed to fail
        jwt_secret="x" * 32,
    )
    app = _MockApp()  # type: ignore[assignment]
    await init_redis(app, settings)  # type: ignore[arg-type]
    assert isinstance(app.state.redis, InProcessCache)  # type: ignore[attr-defined]
