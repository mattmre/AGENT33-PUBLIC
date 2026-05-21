"""Models for the P-PACK v3 A/B harness."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from agent33.outcomes.models import OutcomeMetricType  # noqa: TC001


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class PPackABVariant(StrEnum):
    CONTROL = "control"
    TREATMENT = "treatment"


class PPackABAssignment(BaseModel):
    assignment_id: str = Field(default_factory=lambda: _new_id("abassign"))
    experiment_key: str = "ppack_v3"
    tenant_id: str
    session_id: str
    variant: PPackABVariant
    assignment_hash: str
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PPackABMetricComparison(BaseModel):
    metric_type: OutcomeMetricType
    lower_is_better: bool = False
    control_mean: float = 0.0
    control_count: int = 0
    treatment_mean: float = 0.0
    treatment_count: int = 0
    delta: float = 0.0
    directional_delta_pct: float = 0.0
    p_value: float = 1.0
    alpha: float = 0.05
    minimum_sample_size: int = 30
    sample_size_ready: bool = False
    statistically_significant: bool = False
    regression_detected: bool = False


class PPackABReport(BaseModel):
    report_id: str = Field(default_factory=lambda: _new_id("abreport"))
    experiment_key: str = "ppack_v3"
    tenant_id: str
    domain: str = "all"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    since: datetime | None = None
    until: datetime | None = None
    assignment_counts: dict[str, int] = Field(default_factory=dict)
    total_assignments: int = 0
    total_events_considered: int = 0
    comparisons: list[PPackABMetricComparison] = Field(default_factory=list)
    overall_regression: bool = False
    markdown: str = ""


class GitHubIssuePublishResult(BaseModel):
    attempted: bool = False
    created: bool = False
    issue_number: int | None = None
    issue_url: str = ""
    reason: str = ""
