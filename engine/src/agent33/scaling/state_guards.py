"""State guards that enforce single-instance safety boundaries.

These guards prevent a second AGENT-33 instance from claiming ownership of
state surfaces that are not yet safe for multi-replica operation. They are
designed to raise clear, actionable errors rather than silently allowing
split-brain conditions.

The single-instance deployment guardrail from
``docs/operators/horizontal-scaling-architecture.md`` is still active. These
guards add runtime enforcement as a defense-in-depth layer.
"""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agent33.scaling.distributed_lock import InProcessLock, RedisDistributedLock
    from agent33.scaling.instance_registry import InstanceRegistry

logger = logging.getLogger(__name__)


class InstanceConflictError(RuntimeError):
    """Raised when a second instance attempts to own single-replica state.

    This error indicates that the current AGENT-33 deployment is running
    more instances than the architecture currently supports. The operator
    must either scale back to one instance or complete the P1.3+ migration
    to shared backends.
    """

    def __init__(self, surface: str, instance_count: int, details: str = "") -> None:
        self.surface = surface
        self.instance_count = instance_count
        self.details = details
        message = (
            f"Instance conflict on '{surface}': {instance_count} instances detected. "
            f"This state surface requires single-instance ownership. "
            f"Scale back to replicas=1 or complete the P1.3+ shared-backend migration."
        )
        if details:
            message += f" Details: {details}"
        super().__init__(message)


class SingleInstanceGuard:
    """Checks that only one instance is registered before allowing an operation.

    Used to protect state surfaces that are not yet safe for multi-replica
    operation. If more than one instance is detected in the registry, the
    guard raises ``InstanceConflictError``.

    Parameters
    ----------
    registry:
        The instance registry to check for peer instances.
    surface_name:
        Human-readable name of the protected state surface (e.g.
        ``"cron_scheduler"``), used in error messages.
    """

    def __init__(self, registry: InstanceRegistry, surface_name: str) -> None:
        self._registry = registry
        self._surface_name = surface_name

    async def check(self) -> None:
        """Raise InstanceConflictError if multiple instances are detected."""
        count = await self._registry.count_live_instances()
        if count > 1:
            raise InstanceConflictError(
                surface=self._surface_name,
                instance_count=count,
            )

    async def check_or_warn(self) -> bool:
        """Check for conflicts, logging a warning instead of raising.

        Returns True if no conflict, False if a conflict was detected.
        """
        count = await self._registry.count_live_instances()
        if count > 1:
            logger.warning(
                "instance_conflict_detected surface=%s count=%d",
                self._surface_name,
                count,
            )
            return False
        return True


class SchedulerOwnershipGuard:
    """Wraps scheduled job execution with distributed lock protection.

    Before a scheduled job (cron, interval, evaluation gate) executes, this
    guard acquires a distributed lock keyed by the job identity. If the lock
    is already held by another instance, the execution is skipped with a
    warning log.

    Parameters
    ----------
    lock:
        A distributed lock instance for the protected scheduler surface.
    registry:
        The instance registry for conflict detection.
    surface_name:
        Name of the scheduler surface (used in logs and errors).
    """

    def __init__(
        self,
        lock: RedisDistributedLock | InProcessLock,
        registry: InstanceRegistry,
        surface_name: str = "scheduler",
    ) -> None:
        self._lock = lock
        self._registry = registry
        self._surface_name = surface_name

    def wrap_job(
        self,
        job_fn: Callable[..., Awaitable[Any]],
    ) -> Callable[..., Awaitable[Any]]:
        """Return a wrapper that acquires the lock before executing the job.

        If the lock cannot be acquired, the job is skipped and a warning
        is logged. This prevents duplicate execution across instances.
        """
        lock = self._lock
        surface = self._surface_name

        @functools.wraps(job_fn)
        async def _guarded(*args: Any, **kwargs: Any) -> Any:
            acquired = await lock.acquire(timeout_seconds=0)
            if not acquired:
                logger.warning(
                    "scheduler_job_skipped_lock_held surface=%s lock=%s",
                    surface,
                    lock.lock_name,
                )
                return None
            try:
                return await job_fn(*args, **kwargs)
            finally:
                await lock.release()

        return _guarded

    async def acquire_ownership(self) -> bool:
        """Attempt to acquire scheduler ownership for this instance.

        Returns True if ownership was acquired. This is called at startup
        to determine whether this instance should start its schedulers.
        """
        acquired = await self._lock.acquire(timeout_seconds=0)
        if acquired:
            logger.info(
                "scheduler_ownership_acquired surface=%s instance=%s",
                self._surface_name,
                self._registry.instance_id or "unknown",
            )
        else:
            logger.warning(
                "scheduler_ownership_denied surface=%s instance=%s",
                self._surface_name,
                self._registry.instance_id or "unknown",
            )
        return acquired

    async def release_ownership(self) -> None:
        """Release scheduler ownership on shutdown."""
        released = await self._lock.release()
        if released:
            logger.info(
                "scheduler_ownership_released surface=%s instance=%s",
                self._surface_name,
                self._registry.instance_id or "unknown",
            )
