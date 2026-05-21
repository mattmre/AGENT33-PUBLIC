"""Distributed lock abstraction for multi-instance coordination.

Provides a Redis-based distributed lock using SETNX with TTL expiry and an
in-process fallback using asyncio.Lock for single-node deployments.

Both implementations share the same ``DistributedLock`` protocol so callers
do not need to know which backend is active.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# Default lock TTL in seconds
_DEFAULT_LOCK_TTL_SECONDS = 30
# Redis key prefix for distributed locks
_REDIS_LOCK_PREFIX = "agent33:lock:"


class DistributedLock(Protocol):
    """Protocol for distributed lock implementations."""

    async def acquire(self, timeout_seconds: float = 0) -> bool:
        """Attempt to acquire the lock.

        Parameters
        ----------
        timeout_seconds:
            Maximum time to wait for lock acquisition. If 0, attempt once
            and return immediately.

        Returns
        -------
        bool:
            True if the lock was acquired, False otherwise.
        """
        ...

    async def release(self) -> bool:
        """Release the lock.

        Returns
        -------
        bool:
            True if the lock was released, False if it was not held.
        """
        ...

    @property
    def is_held(self) -> bool:
        """Whether this lock instance currently holds the lock."""
        ...

    @property
    def lock_name(self) -> str:
        """The name/key of the lock."""
        ...


class RedisDistributedLock:
    """Distributed lock using Redis SETNX with TTL expiry.

    Uses the standard Redis single-key lock pattern:
    - SETNX to atomically set a key only if it does not exist
    - SET with EX to apply a TTL so dead holders auto-release
    - Value is a unique token so only the holder can release

    Parameters
    ----------
    redis:
        An async Redis client (``redis.asyncio.Redis``).
    name:
        Lock name (used as the Redis key suffix).
    ttl_seconds:
        Automatic expiry for the lock key. Prevents deadlocks if the
        holder crashes without releasing.
    """

    def __init__(
        self,
        redis: Any,
        name: str,
        ttl_seconds: int = _DEFAULT_LOCK_TTL_SECONDS,
    ) -> None:
        self._redis = redis
        self._name = name
        self._ttl = ttl_seconds
        self._token: str | None = None
        self._key = f"{_REDIS_LOCK_PREFIX}{name}"

    @property
    def lock_name(self) -> str:
        return self._name

    @property
    def is_held(self) -> bool:
        return self._token is not None

    async def acquire(self, timeout_seconds: float = 0) -> bool:
        """Attempt to acquire the lock via Redis SETNX.

        If ``timeout_seconds`` is 0, attempts once. Otherwise retries with
        exponential backoff (50ms base) until the timeout expires.
        """
        token = uuid.uuid4().hex
        deadline = time.monotonic() + timeout_seconds
        backoff = 0.05  # 50ms initial backoff

        while True:
            try:
                acquired = await self._redis.set(self._key, token, nx=True, ex=self._ttl)
                if acquired:
                    self._token = token
                    logger.debug("lock_acquired name=%s token=%s", self._name, token[:8])
                    return True
            except Exception:
                logger.warning("lock_acquire_redis_error name=%s", self._name, exc_info=True)
                return False

            if time.monotonic() >= deadline:
                return False

            await asyncio.sleep(min(backoff, deadline - time.monotonic()))
            backoff = min(backoff * 2, 1.0)  # Cap at 1 second

    async def release(self) -> bool:
        """Release the lock using a Lua script for atomicity.

        Only releases if the stored token matches the one used during
        acquisition, preventing accidental release of another holder's lock.
        """
        if self._token is None:
            return False

        # Lua script: delete key only if value matches our token
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        try:
            result = await self._redis.eval(lua_script, 1, self._key, self._token)
            released = bool(result)
            if released:
                logger.debug("lock_released name=%s token=%s", self._name, self._token[:8])
            else:
                logger.warning(
                    "lock_release_token_mismatch name=%s",
                    self._name,
                )
            self._token = None
            return released
        except Exception:
            logger.warning("lock_release_redis_error name=%s", self._name, exc_info=True)
            self._token = None
            return False

    async def extend(self, additional_seconds: int | None = None) -> bool:
        """Extend the lock TTL without releasing.

        Only extends if the stored token matches the one used during
        acquisition.

        Parameters
        ----------
        additional_seconds:
            New TTL from now. Defaults to the original TTL.
        """
        if self._token is None:
            return False

        ttl = additional_seconds or self._ttl

        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("expire", KEYS[1], ARGV[2])
        else
            return 0
        end
        """
        try:
            result = await self._redis.eval(lua_script, 1, self._key, self._token, str(ttl))
            return bool(result)
        except Exception:
            logger.warning("lock_extend_redis_error name=%s", self._name, exc_info=True)
            return False


class InProcessLock:
    """In-process lock fallback using asyncio.Lock.

    Used when Redis is unavailable. Provides the same interface as
    ``RedisDistributedLock`` but only coordinates within a single process.
    This is safe for single-instance deployments.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._lock = asyncio.Lock()
        self._held = False

    @property
    def lock_name(self) -> str:
        return self._name

    @property
    def is_held(self) -> bool:
        return self._held

    async def acquire(self, timeout_seconds: float = 0) -> bool:
        """Acquire the in-process lock.

        If ``timeout_seconds`` is 0, attempts once without waiting.
        Otherwise waits up to the specified timeout.
        """
        if timeout_seconds <= 0:
            acquired = self._lock.locked() is False
            if acquired:
                try:
                    await asyncio.wait_for(self._lock.acquire(), timeout=0.01)
                    self._held = True
                    return True
                except (TimeoutError, Exception):
                    return False
            return False

        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=timeout_seconds)
            self._held = True
            return True
        except TimeoutError:
            return False

    async def release(self) -> bool:
        """Release the in-process lock."""
        if not self._held:
            return False
        try:
            self._lock.release()
            self._held = False
            return True
        except RuntimeError:
            # Lock was not acquired
            self._held = False
            return False


def create_lock(
    name: str,
    redis: Any | None = None,
    ttl_seconds: int = _DEFAULT_LOCK_TTL_SECONDS,
) -> RedisDistributedLock | InProcessLock:
    """Factory: create a distributed lock with Redis or in-process fallback.

    Parameters
    ----------
    name:
        Lock name / key.
    redis:
        Optional async Redis client. If None, creates an InProcessLock.
    ttl_seconds:
        TTL for Redis-based locks.

    Returns
    -------
    A lock instance implementing the DistributedLock protocol.
    """
    if redis is not None:
        return RedisDistributedLock(redis=redis, name=name, ttl_seconds=ttl_seconds)
    return InProcessLock(name=name)
