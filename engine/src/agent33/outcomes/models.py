"""Domain models for outcomes events, trends, and dashboard views."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class OutcomeMetricType(StrEnum):
    """Supported metric families for outcome events."""

    SUCCESS_RATE = "success_rate"
    QUALITY_SCORE = "quality_score"
    LATENCY_MS = "latency_ms"
    COST_USD = "cost_usd"
    FAILURE_CLASS = "failure_class"


class TrendDirection(StrEnum):
    """Direction values for trends."""

    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"


class OutcomeEventCreate(BaseModel):
    """Request payload used to record an outcome event."""

    domain: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    metric_type: OutcomeMetricType
    value: float
    occurred_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OutcomeEvent(BaseModel):
    """Tenant-scoped event record for outcome metrics."""

    id: str = Field(default_factory=lambda: _new_id("outcome"))
    tenant_id: str = ""
    domain: str
    event_type: str
    metric_type: OutcomeMetricType
    value: float
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class OutcomeTrend(BaseModel):
    """Trend contract for a single metric + domain window query."""

    metric_type: OutcomeMetricType
    domain: str = "all"
    window: int = Field(default=20, ge=1)
    direction: TrendDirection = TrendDirection.STABLE
    sample_size: int = 0
    values: list[float] = Field(default_factory=list)
    previous_avg: float = 0.0
    current_avg: float = 0.0


class OutcomeSummary(BaseModel):
    """Summary payload used by dashboard responses."""

    total_events: int = 0
    domains: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    metric_counts: dict[str, int] = Field(default_factory=dict)


class WeekOverWeekStat(BaseModel):
    """Compare a metric's current-week average against the previous week."""

    metric_type: OutcomeMetricType
    current_week_avg: float
    previous_week_avg: float
    pct_change: float  # (current - previous) / previous * 100; 0 if previous == 0


class FailureModeStat(BaseModel):
    """Aggregated count for a specific failure classification."""

    failure_class: str
    count: int


class ROIRequest(BaseModel):
    """Payload for the ROI estimator endpoint."""

    domain: str = Field(min_length=1)
    hours_saved_per_success: float = Field(ge=0)
    cost_per_hour_usd: float = Field(ge=0)
    window_days: int = Field(default=30, ge=1)


class ROIResponse(BaseModel):
    """Result of the ROI estimation."""

    total_invocations: int
    success_count: int
    failure_count: int
    estimated_hours_saved: float
    estimated_value_usd: float
    success_rate: float
    avg_latency_ms: float


class PackImpactEntry(BaseModel):
    """Impact statistics for a single pack."""

    pack_name: str
    sessions_applied: int
    success_rate_with_pack: float
    success_rate_without_pack: float
    delta: float


class PackImpactResponse(BaseModel):
    """Pack impact response for the dashboard."""

    packs: list[PackImpactEntry] = Field(default_factory=list)


class OutcomeDashboard(BaseModel):
    """Dashboard contract with trend snapshots and recent events."""

    trends: list[OutcomeTrend] = Field(default_factory=list)
    recent_events: list[OutcomeEvent] = Field(default_factory=list)
    summary: OutcomeSummary = Field(default_factory=OutcomeSummary)
    week_over_week: list[WeekOverWeekStat] = Field(default_factory=list)
    top_failure_modes: list[FailureModeStat] = Field(default_factory=list)
