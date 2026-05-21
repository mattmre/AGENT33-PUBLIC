"""Connector metrics collection for monitoring and UX endpoints."""

from __future__ import annotations

import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass(slots=True)
class _ConnectorStats:
    """Per-connector accumulated metrics."""

    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    latency_samples: deque[float] = field(default_factory=lambda: deque(maxlen=500))


class ConnectorMetricsCollector:
    """Tracks per-connector call metrics and circuit state-change events.

    Thread-safe within a single asyncio event loop (no locking needed).
    """

    def __init__(self, max_events: int = 100) -> None:
        self._stats: dict[str, _ConnectorStats] = {}
        self._circuit_events: dict[str, deque[dict[str, Any]]] = {}
        self._max_events = max_events

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_call(self, connector_id: str, *, success: bool, latency_ms: float) -> None:
        """Record a call outcome for a connector."""
        stats = self._stats.get(connector_id)
        if stats is None:
            stats = _ConnectorStats()
            self._stats[connector_id] = stats
        stats.total_calls += 1
        if success:
            stats.successes += 1
        else:
            stats.failures += 1
        stats.latency_samples.append(latency_ms)

    def record_circuit_event(
        self,
        connector_id: str,
        old_state: str,
        new_state: str,
    ) -> None:
        """Record a circuit breaker state transition."""
        ring = self._circuit_events.get(connector_id)
        if ring is None:
            ring = deque(maxlen=self._max_events)
            self._circuit_events[connector_id] = ring
        ring.append(
            {
                "connector_id": connector_id,
                "old_state": old_state,
                "new_state": new_state,
                "timestamp": time.monotonic(),
            }
        )
        # Ensure the connector shows up in _stats as well
        if connector_id not in self._stats:
            self._stats[connector_id] = _ConnectorStats()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_connector_metrics(self, connector_id: str) -> dict[str, Any]:
        """Return aggregated metrics for a single connector.

        Returns a dict compatible with ``ConnectorMetricsSummary``.
        """
        stats = self._stats.get(connector_id)
        if stats is None:
            return {
                "total_calls": 0,
                "successes": 0,
                "failures": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
                "error_rate": 0.0,
            }
        total = stats.total_calls or 1  # avoid div-by-zero
        samples = list(stats.latency_samples)
        avg_lat = statistics.mean(samples) if samples else 0.0
        p95_lat = _percentile(samples, 95) if samples else 0.0
        return {
            "total_calls": stats.total_calls,
            "successes": stats.successes,
            "failures": stats.failures,
            "success_rate": round(stats.successes / total, 4),
            "avg_latency_ms": round(avg_lat, 2),
            "p95_latency_ms": round(p95_lat, 2),
            "error_rate": round(stats.failures / total, 4),
        }

    def get_all_metrics(self) -> dict[str, dict[str, Any]]:
        """Return aggregated metrics for every known connector."""
        return {cid: self.get_connector_metrics(cid) for cid in self._stats}

    def get_circuit_events(self, connector_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent circuit breaker events for a connector (newest first)."""
        ring = self._circuit_events.get(connector_id)
        if ring is None:
            return []
        items = list(ring)
        items.reverse()
        return items[:limit]

    def list_known_connectors(self) -> list[str]:
        """Return all connector IDs that have recorded metrics or events."""
        return sorted(self._stats.keys())


def _percentile(data: list[float], pct: float) -> float:
    """Compute a percentile from a sorted copy of *data*."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (pct / 100.0) * (len(sorted_data) - 1)
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[-1]
    d = k - f
    return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])
