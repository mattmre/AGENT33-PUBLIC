"""Fallback implementations for infrastructure services.

These are used in lite mode when PostgreSQL / Redis / NATS are not available.
They are intentionally simple: correct enough for local development and testing,
not suitable for production deployments.
"""

from __future__ import annotations

import asyncio
from typing import Any


class InProcessCache:
    """Simple LRU-style in-process cache as a Redis fallback for lite mode.

    Not thread-safe; suitable for single-process async applications only.
    """

    def __init__(self, maxsize: int = 1000) -> None:
        self._store: dict[str, Any] = {}
        self._maxsize = maxsize

    async def get(self, key: str) -> Any:
        return self._store.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> None:  # noqa: A002
        if len(self._store) >= self._maxsize:
            # Evict the oldest entry (insertion-order dict in Python 3.7+)
            oldest = next(iter(self._store))
            del self._store[oldest]
        self._store[key] = value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self._store

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self._store.clear()


class InProcessMessageBus:
    """asyncio.Queue-based in-process pub/sub as a NATS fallback for lite mode.

    Supports simple publish/subscribe but NOT request-reply or queue groups.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[bytes]]] = {}

    @property
    def is_connected(self) -> bool:
        return True

    async def connect(self) -> None:
        pass

    async def publish(self, subject: str, data: bytes) -> None:
        queues = self._subscribers.get(subject, [])
        for q in queues:
            await q.put(data)

    async def subscribe(self, subject: str) -> asyncio.Queue[bytes]:
        q: asyncio.Queue[bytes] = asyncio.Queue()
        self._subscribers.setdefault(subject, []).append(q)
        return q

    async def close(self) -> None:
        self._subscribers.clear()
