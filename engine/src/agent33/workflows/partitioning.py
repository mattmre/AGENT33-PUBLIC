"""CA-024: Runtime Partitioning for workflow execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@dataclass
class PartitionDefinition:
    """Definition of how work should be partitioned.

    Either supply a static list of keys or a discovery callable.
    """

    static_keys: list[str] = field(default_factory=list)
    discover: Callable[[], Awaitable[list[str]]] | None = None


@dataclass
class PartitionResult:
    """Result from executing a single partition."""

    key: str
    outputs: dict[str, Any] = field(default_factory=dict)
    status: str = "success"
    error: str | None = None


class PartitionExecutor:
    """Fans out workflow execution across partition keys.

    Each partition runs independently and in parallel.  Supports both
    static partition lists and dynamic partition discovery via an async
    callable.
    """

    def __init__(
        self,
        partition: PartitionDefinition,
        max_concurrency: int = 8,
    ) -> None:
        self._partition = partition
        self._max_concurrency = max_concurrency

    async def _resolve_keys(self) -> list[str]:
        """Resolve partition keys from static list or discovery function."""
        if self._partition.discover is not None:
            return await self._partition.discover()
        return list(self._partition.static_keys)

    async def execute(
        self,
        run_fn: Callable[[str], Awaitable[dict[str, Any]]],
    ) -> list[PartitionResult]:
        """Execute ``run_fn`` for every partition key.

        Parameters
        ----------
        run_fn:
            Async callable that receives a partition key and returns outputs.

        Returns
        -------
        list[PartitionResult]
            One result per partition key.
        """
        keys = await self._resolve_keys()
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _run(key: str) -> PartitionResult:
            async with semaphore:
                try:
                    outputs = await run_fn(key)
                    return PartitionResult(key=key, outputs=outputs, status="success")
                except Exception as exc:
                    return PartitionResult(key=key, status="failed", error=str(exc))

        tasks = [_run(k) for k in keys]
        return list(await asyncio.gather(*tasks))
