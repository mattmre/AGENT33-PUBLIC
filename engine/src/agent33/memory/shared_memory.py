"""Shared conversation-memory namespace layer (P2.4).

Provides a Redis-backed key-value namespace that multiple agents can use to
share working memory within a session, an agent's private scope, or a
tenant-global scope.  All keys are prefixed with ``{tenant_id}/{namespace}/``
to enforce hard tenant isolation.

Write operations acquire a :class:`~agent33.scaling.distributed_lock.DistributedLock`
to guarantee cross-instance safety.
"""

from __future__ import annotations

import logging
from typing import Any

from agent33.scaling.distributed_lock import RedisDistributedLock
from agent33.security.redaction import redact_secrets

logger = logging.getLogger(__name__)

# Lock TTL for write operations (seconds)
_WRITE_LOCK_TTL_SECONDS = 10

# Redis key prefix for shared-memory data
_SHARED_MEMORY_PREFIX = "agent33:sharedmem:"

# Lock key prefix (follows P1.2 convention)
_LOCK_PREFIX = "memory"


class SharedMemoryNamespace:
    """A tenant-scoped, namespaced key-value store backed by Redis.

    Parameters
    ----------
    redis:
        An async Redis client (``redis.asyncio.Redis``).
    tenant_id:
        Hard isolation key.  Always the first path component.
    namespace:
        Logical scope such as ``session/{session_id}/shared``,
        ``agent/{agent_id}``, or ``global``.
    """

    def __init__(
        self,
        redis: Any,
        tenant_id: str,
        namespace: str,
        *,
        redact_enabled: bool = True,
    ) -> None:
        self._redis: Any = redis
        self._tenant_id = tenant_id
        self._namespace = namespace
        self._redact_enabled = redact_enabled

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    def full_key(self, key: str) -> str:
        """Return the fully-qualified Redis key for *key*.

        Format: ``agent33:sharedmem:{tenant_id}/{namespace}/{key}``
        """
        return f"{_SHARED_MEMORY_PREFIX}{self._tenant_id}/{self._namespace}/{key}"

    def _lock_name(self, key: str) -> str:
        """Return the distributed-lock name for *key*.

        Format: ``memory:{tenant_id}/{namespace}/{key}``
        """
        return f"{_LOCK_PREFIX}:{self._tenant_id}/{self._namespace}/{key}"

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    async def read(self, key: str) -> str | None:
        """Read a value from the namespace.

        Returns ``None`` when the key does not exist.
        """
        raw: bytes | None = await self._redis.get(self.full_key(key))
        if raw is None:
            return None
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    async def write(
        self,
        key: str,
        value: str,
        ttl_seconds: int | None = None,
    ) -> None:
        """Write *value* under *key*, guarded by a distributed lock.

        Parameters
        ----------
        key:
            The namespace-relative key.
        value:
            The string value to store.
        ttl_seconds:
            Optional Redis TTL.  When ``None`` the key does not expire.
        """
        # Redact secrets from string values before persistence (Phase 52).
        safe_value = redact_secrets(value, enabled=self._redact_enabled)

        lock = RedisDistributedLock(
            redis=self._redis,
            name=self._lock_name(key),
            ttl_seconds=_WRITE_LOCK_TTL_SECONDS,
        )
        acquired = await lock.acquire(timeout_seconds=5)
        if not acquired:
            msg = (
                f"Failed to acquire write lock for key={key!r} "
                f"namespace={self._namespace!r} tenant={self._tenant_id!r}"
            )
            raise RuntimeError(msg)

        try:
            fk = self.full_key(key)
            if ttl_seconds is not None:
                await self._redis.set(fk, safe_value, ex=ttl_seconds)
            else:
                await self._redis.set(fk, safe_value)
            logger.debug(
                "shared_memory_write tenant=%s ns=%s key=%s ttl=%s",
                self._tenant_id,
                self._namespace,
                key,
                ttl_seconds,
            )
        finally:
            await lock.release()

    async def delete(self, key: str) -> None:
        """Delete *key* from the namespace."""
        await self._redis.delete(self.full_key(key))
        logger.debug(
            "shared_memory_delete tenant=%s ns=%s key=%s",
            self._tenant_id,
            self._namespace,
            key,
        )

    async def list_keys(self, prefix: str = "") -> list[str]:
        """List all keys in this namespace, optionally filtered by *prefix*.

        Uses Redis SCAN (production-safe, non-blocking) rather than KEYS.

        Returns namespace-relative key names (i.e. the portion after
        ``{tenant_id}/{namespace}/``).
        """
        scan_pattern = f"{_SHARED_MEMORY_PREFIX}{self._tenant_id}/{self._namespace}/{prefix}*"
        # Length of the constant prefix that we strip from returned keys
        strip_len = len(f"{_SHARED_MEMORY_PREFIX}{self._tenant_id}/{self._namespace}/")
        keys: list[str] = []
        cursor: int | str = 0
        while True:
            cursor, batch = await self._redis.scan(cursor=cursor, match=scan_pattern, count=100)
            for raw_key in batch:
                decoded = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
                keys.append(decoded[strip_len:])
            if cursor == 0:
                break
        return keys

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def tenant_id(self) -> str:
        """The tenant isolation key."""
        return self._tenant_id

    @property
    def namespace(self) -> str:
        """The logical namespace string."""
        return self._namespace
