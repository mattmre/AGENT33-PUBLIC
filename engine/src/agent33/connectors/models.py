"""Shared connector boundary models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


@dataclass(slots=True)
class ConnectorRequest:
    """Envelope passed through connector middleware chains."""

    connector: str
    operation: str
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Pydantic response models for the connector monitoring API
# ---------------------------------------------------------------------------


class CircuitBreakerSnapshot(BaseModel):
    """Serializable snapshot of a circuit breaker's state."""

    state: str
    consecutive_failures: int = 0
    total_trips: int = 0
    last_trip_at: float | None = None
    failure_threshold: int = 3
    recovery_timeout_seconds: float = 30.0
    half_open_success_threshold: int = 2
    max_recovery_timeout_seconds: float = 300.0
    effective_recovery_timeout_seconds: float = 30.0
    cooldown_remaining_seconds: float = 0.0


class ConnectorMetricsSummary(BaseModel):
    """Aggregated call metrics for a single connector."""

    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    error_rate: float = 0.0


class ConnectorStatus(BaseModel):
    """Combined status for a single connector in the fleet."""

    connector_id: str
    name: str = ""
    connector_type: str = "boundary"
    state: str = "unknown"
    circuit: CircuitBreakerSnapshot | None = None
    metrics: ConnectorMetricsSummary | None = None


class ConnectorHealthSummary(BaseModel):
    """Fleet-level health counts."""

    total: int = 0
    healthy: int = 0
    degraded: int = 0
    open_circuit: int = 0
    stopped: int = 0


class CircuitEvent(BaseModel):
    """A single circuit breaker state-change event."""

    connector_id: str
    old_state: str
    new_state: str
    timestamp: float
