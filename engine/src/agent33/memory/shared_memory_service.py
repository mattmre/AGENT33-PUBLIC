"""Service layer for shared conversation-memory namespaces (P2.4).

Manages the Redis connection and provides factory methods for obtaining
pre-scoped :class:`~agent33.memory.shared_memory.SharedMemoryNamespace`
instances.
"""

from __future__ import annotations

import logging
from typing import Any

from agent33.memory.shared_memory import SharedMemoryNamespace

logger = logging.getLogger(__name__)


class SharedMemoryService:
    """Factory and lifecycle manager for shared-memory namespaces.

    Parameters
    ----------
    redis_url:
        Redis connection URL (e.g. ``redis://localhost:6379/0``).
    """

    def __init__(self, redis_url: str, *, redact_enabled: bool = True) -> None:
        self._redis_url = redis_url
        self._redis: Any = None
        self._redact_enabled = redact_enabled

    async def _ensure_redis(self) -> Any:
        """Lazily initialise the async Redis client on first use."""
        if self._redis is None:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self._redis_url, decode_responses=False)  # type: ignore[no-untyped-call]
        return self._redis

    # ------------------------------------------------------------------
    # Namespace factories
    # ------------------------------------------------------------------

    def get_namespace(self, tenant_id: str, namespace: str) -> SharedMemoryNamespace:
        """Return a namespace handle with an arbitrary namespace string."""
        if self._redis is None:
            msg = (
                "SharedMemoryService Redis client not initialised. "
                "Call await _ensure_redis() or use the async factory methods."
            )
            raise RuntimeError(msg)
        return SharedMemoryNamespace(
            redis=self._redis,
            tenant_id=tenant_id,
            namespace=namespace,
            redact_enabled=self._redact_enabled,
        )

    async def get_session_namespace(
        self, tenant_id: str, session_id: str
    ) -> SharedMemoryNamespace:
        """Return the shared namespace for a workflow session.

        Namespace pattern: ``session/{session_id}/shared``
        """
        redis = await self._ensure_redis()
        return SharedMemoryNamespace(
            redis=redis,
            tenant_id=tenant_id,
            namespace=f"session/{session_id}/shared",
            redact_enabled=self._redact_enabled,
        )

    async def get_agent_namespace(self, tenant_id: str, agent_id: str) -> SharedMemoryNamespace:
        """Return the private namespace for a specific agent.

        Namespace pattern: ``agent/{agent_id}``
        """
        redis = await self._ensure_redis()
        return SharedMemoryNamespace(
            redis=redis,
            tenant_id=tenant_id,
            namespace=f"agent/{agent_id}",
            redact_enabled=self._redact_enabled,
        )

    async def get_global_namespace(self, tenant_id: str) -> SharedMemoryNamespace:
        """Return the tenant-global namespace.

        Namespace pattern: ``global``
        """
        redis = await self._ensure_redis()
        return SharedMemoryNamespace(
            redis=redis,
            tenant_id=tenant_id,
            namespace="global",
            redact_enabled=self._redact_enabled,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the Redis connection, releasing resources."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
            logger.info("shared_memory_service_closed")
