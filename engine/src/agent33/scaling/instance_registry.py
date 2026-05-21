"""Instance identity management for multi-instance awareness.

Each AGENT-33 process gets a unique instance ID (UUID) at startup. When Redis
is available, the instance registers itself with a TTL-based heartbeat key so
that other instances can detect live peers. When Redis is unavailable, the
registry falls back to in-process tracking only.
"""

from __future__ import annotations

import logging
import platform
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Redis key prefix for instance registration
_REDIS_KEY_PREFIX = "agent33:instance:"
# Default TTL for instance heartbeat keys (seconds)
_DEFAULT_TTL_SECONDS = 60


@dataclass(frozen=True, slots=True)
class InstanceInfo:
    """Identity and metadata for a running AGENT-33 instance."""

    instance_id: str
    hostname: str
    pid: int
    started_at: float
    metadata: dict[str, Any] = field(default_factory=dict)


class InstanceRegistry:
    """Manages instance identity registration and peer discovery.

    When constructed with a Redis connection, instances are registered as
    Redis keys with a TTL-based heartbeat. When Redis is unavailable, the
    registry tracks only the local instance in memory.

    Parameters
    ----------
    redis:
        An async Redis client (``redis.asyncio.Redis``). Pass ``None`` for
        in-process-only mode.
    ttl_seconds:
        TTL for Redis heartbeat keys. Each call to :meth:`register`
        or :meth:`heartbeat` resets this TTL.
    """

    def __init__(
        self,
        redis: Any | None = None,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self._redis = redis
        self._ttl = ttl_seconds
        self._local_instance: InstanceInfo | None = None

    @property
    def instance_id(self) -> str | None:
        """Return the current instance ID, or None if not registered."""
        if self._local_instance is not None:
            return self._local_instance.instance_id
        return None

    @property
    def instance_info(self) -> InstanceInfo | None:
        """Return the full instance info, or None if not registered."""
        return self._local_instance

    async def register(self, metadata: dict[str, Any] | None = None) -> InstanceInfo:
        """Register this instance and return its identity.

        Generates a unique instance ID, stores it locally, and if Redis is
        available, writes a heartbeat key with the configured TTL.
        """
        import json
        import os

        info = InstanceInfo(
            instance_id=uuid.uuid4().hex,
            hostname=platform.node(),
            pid=os.getpid(),
            started_at=time.time(),
            metadata=metadata or {},
        )
        self._local_instance = info

        if self._redis is not None:
            try:
                key = f"{_REDIS_KEY_PREFIX}{info.instance_id}"
                value = json.dumps(
                    {
                        "instance_id": info.instance_id,
                        "hostname": info.hostname,
                        "pid": info.pid,
                        "started_at": info.started_at,
                        "metadata": info.metadata,
                    }
                )
                await self._redis.set(key, value, ex=self._ttl)
                logger.info(
                    "instance_registered_redis instance_id=%s hostname=%s ttl=%d",
                    info.instance_id,
                    info.hostname,
                    self._ttl,
                )
            except Exception:
                logger.warning(
                    "instance_register_redis_failed instance_id=%s",
                    info.instance_id,
                    exc_info=True,
                )
        else:
            logger.info(
                "instance_registered_local instance_id=%s hostname=%s",
                info.instance_id,
                info.hostname,
            )

        return info

    async def deregister(self) -> None:
        """Remove this instance from the registry.

        Clears the local instance info and, if Redis is available, deletes
        the heartbeat key.
        """
        if self._local_instance is None:
            return

        instance_id = self._local_instance.instance_id

        if self._redis is not None:
            try:
                key = f"{_REDIS_KEY_PREFIX}{instance_id}"
                await self._redis.delete(key)
                logger.info("instance_deregistered_redis instance_id=%s", instance_id)
            except Exception:
                logger.warning(
                    "instance_deregister_redis_failed instance_id=%s",
                    instance_id,
                    exc_info=True,
                )

        self._local_instance = None
        logger.info("instance_deregistered instance_id=%s", instance_id)

    async def heartbeat(self) -> bool:
        """Refresh the TTL on the Redis heartbeat key.

        Returns True if the heartbeat was successfully refreshed, False
        if Redis is unavailable or the refresh failed.
        """
        if self._local_instance is None:
            return False

        if self._redis is None:
            return True  # In-process mode: always alive

        try:
            key = f"{_REDIS_KEY_PREFIX}{self._local_instance.instance_id}"
            result = await self._redis.expire(key, self._ttl)
            return bool(result)
        except Exception:
            logger.warning(
                "instance_heartbeat_failed instance_id=%s",
                self._local_instance.instance_id,
                exc_info=True,
            )
            return False

    async def list_live_instances(self) -> list[InstanceInfo]:
        """Return all currently registered instances from Redis.

        In in-process mode, returns only the local instance (if registered).
        """
        import json

        if self._local_instance is None:
            return []

        if self._redis is None:
            return [self._local_instance]

        try:
            pattern = f"{_REDIS_KEY_PREFIX}*"
            keys: list[bytes | str] = []
            async for key in self._redis.scan_iter(match=pattern):
                keys.append(key)

            instances: list[InstanceInfo] = []
            for key in keys:
                raw = await self._redis.get(key)
                if raw is None:
                    continue
                try:
                    data = json.loads(raw)
                    instances.append(
                        InstanceInfo(
                            instance_id=data["instance_id"],
                            hostname=data.get("hostname", ""),
                            pid=data.get("pid", 0),
                            started_at=data.get("started_at", 0.0),
                            metadata=data.get("metadata", {}),
                        )
                    )
                except (json.JSONDecodeError, KeyError):
                    logger.warning("instance_registry_corrupt_entry key=%s", str(key))
            return instances
        except Exception:
            logger.warning("instance_list_failed", exc_info=True)
            # Fallback to local only
            return [self._local_instance]

    async def count_live_instances(self) -> int:
        """Return the number of currently registered instances.

        This is a lightweight check used by state guards to detect conflicts.
        """
        instances = await self.list_live_instances()
        return len(instances)
