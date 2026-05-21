"""Lightweight query profiling for hot-path DB operations (P1.4).

Provides the :func:`track_query` async context manager that measures
wall-clock duration of data-access operations, logs a WARNING when the
configured threshold is exceeded, and records observations to the
``db_query_duration_seconds`` Prometheus histogram.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from time import perf_counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from agent33.observability.metrics import MetricsCollector

logger = logging.getLogger(__name__)

# Module-level references wired at startup via ``configure_query_profiling``.
_metrics: MetricsCollector | None = None
_threshold_ms: int = 100

_METRIC_NAME = "db_query_duration_seconds"


def configure_query_profiling(
    metrics: MetricsCollector,
    threshold_ms: int = 100,
) -> None:
    """Wire the profiling module to the application's MetricsCollector.

    Called once during lifespan startup so that :func:`track_query` can
    record observations without every call-site needing to pass the
    collector explicitly.
    """
    global _metrics, _threshold_ms  # noqa: PLW0603
    _metrics = metrics
    _threshold_ms = max(1, threshold_ms)


@asynccontextmanager
async def track_query(
    operation: str,
    table: str = "unknown",
    threshold_ms: int | None = None,
) -> AsyncIterator[None]:
    """Measure and record the duration of an async data-access operation.

    Usage::

        async with track_query("memory_search", table="memory_records"):
            results = await ltm.search(embedding, top_k=5)

    Parameters
    ----------
    operation:
        Short identifier for the operation (e.g. ``"memory_search"``).
    table:
        Logical table or data store name for the Prometheus label.
    threshold_ms:
        Override the global slow-query threshold for this single call.
        ``None`` means use the configured default.
    """
    effective_threshold = threshold_ms if threshold_ms is not None else _threshold_ms
    start = perf_counter()
    try:
        yield
    finally:
        elapsed_s = perf_counter() - start
        elapsed_ms = elapsed_s * 1000.0

        labels = {"operation": operation, "table": table}

        # Record to Prometheus histogram
        if _metrics is not None:
            _metrics.observe(_METRIC_NAME, elapsed_s, labels=labels)

        # Slow-query warning
        if elapsed_ms > effective_threshold:
            logger.warning(
                "slow_query operation=%s table=%s duration_ms=%.1f threshold_ms=%d",
                operation,
                table,
                elapsed_ms,
                effective_threshold,
            )
