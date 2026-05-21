"""Scaling primitives for multi-instance safety (P1.2).

This package provides instance identity management, distributed locking,
and state guards that prevent split-brain conditions when multiple AGENT-33
instances share the same backing services.

The single-instance deployment guardrail is NOT removed by this package.
These primitives prepare the runtime for safe horizontal scaling in P1.3+.
"""

from agent33.scaling.distributed_lock import DistributedLock, InProcessLock, RedisDistributedLock
from agent33.scaling.instance_registry import InstanceInfo, InstanceRegistry
from agent33.scaling.state_guards import (
    InstanceConflictError,
    SchedulerOwnershipGuard,
    SingleInstanceGuard,
)

__all__ = [
    "DistributedLock",
    "InProcessLock",
    "InstanceConflictError",
    "InstanceInfo",
    "InstanceRegistry",
    "RedisDistributedLock",
    "SchedulerOwnershipGuard",
    "SingleInstanceGuard",
]
