"""Tests for SQLite long-term memory adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agent33.memory.sqlite_long_term import SQLiteLongTermMemory

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
async def mem() -> AsyncGenerator[SQLiteLongTermMemory, None]:
    m = SQLiteLongTermMemory(db_path=":memory:")
    await m.initialize()
    yield m
    await m.close()


async def test_store_and_retrieve(mem: SQLiteLongTermMemory) -> None:
    memory_id = await mem.store("Hello world", {"source": "test"})
    assert memory_id
    result = await mem.get(memory_id)
    assert result is not None
    assert result["content"] == "Hello world"
    assert result["metadata"]["source"] == "test"


async def test_store_returns_unique_ids(mem: SQLiteLongTermMemory) -> None:
    id1 = await mem.store("First", {})
    id2 = await mem.store("Second", {})
    assert id1 != id2


async def test_search_finds_content(mem: SQLiteLongTermMemory) -> None:
    await mem.store("Python is great for AI", {"tag": "python"})
    await mem.store("Java is verbose", {"tag": "java"})
    results = await mem.search("Python")
    assert len(results) >= 1
    assert any("Python" in r["content"] for r in results)


async def test_search_no_results(mem: SQLiteLongTermMemory) -> None:
    await mem.store("Unrelated content", {})
    results = await mem.search("zzzyyyxxx_nomatch")
    assert results == []


async def test_search_limit(mem: SQLiteLongTermMemory) -> None:
    for i in range(10):
        await mem.store(f"memory item number {i}", {})
    results = await mem.search("memory", limit=3)
    assert len(results) <= 3


async def test_delete_existing(mem: SQLiteLongTermMemory) -> None:
    memory_id = await mem.store("To be deleted", {})
    deleted = await mem.delete(memory_id)
    assert deleted is True
    result = await mem.get(memory_id)
    assert result is None


async def test_delete_nonexistent(mem: SQLiteLongTermMemory) -> None:
    deleted = await mem.delete("nonexistent-id-12345")
    assert deleted is False


async def test_get_nonexistent(mem: SQLiteLongTermMemory) -> None:
    result = await mem.get("nonexistent-id-12345")
    assert result is None


async def test_tenant_isolation(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "test.db"  # type: ignore[operator]
    m1 = SQLiteLongTermMemory(db_path=db_path, tenant_id="tenant_a")
    m2 = SQLiteLongTermMemory(db_path=db_path, tenant_id="tenant_b")
    await m1.initialize()
    await m2.initialize()

    await m1.store("tenant A memory", {})
    results_b = await m2.search("tenant A")
    assert len(results_b) == 0  # tenant_b cannot see tenant_a's memories

    await m1.close()
    await m2.close()


async def test_close_idempotent(mem: SQLiteLongTermMemory) -> None:
    await mem.close()
    await mem.close()  # should not raise


async def test_persistent_storage(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "persistent.db"  # type: ignore[operator]
    m = SQLiteLongTermMemory(db_path=db_path)
    await m.initialize()
    memory_id = await m.store("Persistent memory", {"key": "value"})
    await m.close()

    m2 = SQLiteLongTermMemory(db_path=db_path)
    await m2.initialize()
    result = await m2.get(memory_id)
    assert result is not None
    assert result["content"] == "Persistent memory"
    await m2.close()


async def test_protocol_compliance() -> None:
    from agent33.memory.protocols import LongTermMemoryProtocol

    m = SQLiteLongTermMemory()
    assert isinstance(m, LongTermMemoryProtocol)


async def test_metadata_round_trip(mem: SQLiteLongTermMemory) -> None:
    """Metadata (arbitrary JSON) is stored and retrieved faithfully."""
    metadata = {"tags": ["ai", "memory"], "priority": 5, "active": True}
    memory_id = await mem.store("metadata test", metadata)
    result = await mem.get(memory_id)
    assert result is not None
    assert result["metadata"] == metadata


async def test_created_at_is_iso8601(mem: SQLiteLongTermMemory) -> None:
    """created_at field is a valid ISO 8601 timestamp string."""
    from datetime import datetime

    memory_id = await mem.store("timestamp test", {})
    result = await mem.get(memory_id)
    assert result is not None
    # Should parse without error
    dt = datetime.fromisoformat(result["created_at"])
    assert dt is not None
