"""Data models for the evaluation and regression gate framework.

Implements the spec from ``core/arch/REGRESSION_GATES.md`` and
``core/arch/evaluation-harness.md``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class GateType(StrEnum):
    """Regression gate types (§ Gate Types)."""

    G_PR = "G-PR"
    G_MRG = "G-MRG"
    G_REL = "G-REL"
    G_MON = "G-MON"


class GateAction(StrEnum):
    """Action taken when a threshold is breached."""

    BLOCK = "block"
    WARN = "warn"
    ALERT = "alert"


class GateResult(StrEnum):
    """Outcome of a gate check."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


class MetricId(StrEnum):
    """Evaluation metrics (§ Metrics Definitions)."""

    M_01 = "M-01"  # Success Rate
    M_02 = "M-02"  # Time-to-Green
    M_03 = "M-03"  # Rework Rate
    M_04 = "M-04"  # Diff Size
    M_05 = "M-05"  # Scope Adherence


class GoldenTag(StrEnum):
    """Golden task gating tags (§ Golden Task Gating Tags)."""

    GT_CRITICAL = "GT-CRITICAL"
    GT_RELEASE = "GT-RELEASE"
    GT_SMOKE = "GT-SMOKE"
    GT_REGRESSION = "GT-REGRESSION"
    GT_OPTIONAL = "GT-OPTIONAL"


class TaskResult(StrEnum):
    """Result of a single golden task / case execution."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"


class RegressionIndicator(StrEnum):
    """Regression indicators (§ Regression Detection)."""

    RI_01 = "RI-01"  # Previously passing task now fails
    RI_02 = "RI-02"  # Metric drops below threshold
    RI_03 = "RI-03"  # New failure category appears
    RI_04 = "RI-04"  # Time-to-green increases significantly
    RI_05 = "RI-05"  # Flaky test becomes consistent failure


class RegressionSeverity(StrEnum):
    """Severity levels for regressions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TriageStatus(StrEnum):
    """Triage status for regression records."""

    NEW = "new"
    INVESTIGATING = "investigating"
    IDENTIFIED = "identified"
    FIXING = "fixing"
    RESOLVED = "resolved"
    WONTFIX = "wontfix"


class ThresholdOperator(StrEnum):
    """Comparison operators for thresholds."""

    GTE = "gte"
    LTE = "lte"
    EQ = "eq"
    GT = "gt"
    LT = "lt"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class GoldenTaskDef(BaseModel):
    """Definition of a golden task (GT-01 .. GT-07)."""

    task_id: str
    name: str
    description: str = ""
    tags: list[GoldenTag] = Field(default_factory=list)
    owner: str = ""
    checks: list[str] = Field(default_factory=list)


class GoldenCaseDef(BaseModel):
    """Definition of a golden PR/issue case (GC-01 .. GC-04)."""

    case_id: str
    name: str
    description: str = ""
    tags: list[GoldenTag] = Field(default_factory=list)
    owner: str = ""
    checks: list[str] = Field(default_factory=list)


class TaskRunResult(BaseModel):
    """Result of executing a single golden task or case."""

    item_id: str  # GT-XX or GC-XX
    result: TaskResult = TaskResult.PASS
    checks_passed: int = 0
    checks_total: int = 0
    duration_ms: int = 0
    notes: str = ""


class MetricValue(BaseModel):
    """A computed metric value."""

    metric_id: MetricId
    value: float = 0.0
    unit: str = "%"


class GateThreshold(BaseModel):
    """A single threshold rule for a gate."""

    metric_id: MetricId
    gate: GateType
    operator: ThresholdOperator
    value: float
    action: GateAction = GateAction.BLOCK
    bypass_allowed: bool = False


class GateCheckResult(BaseModel):
    """Result of checking a single threshold."""

    threshold: GateThreshold
    actual_value: float
    passed: bool
    action_taken: GateAction = GateAction.BLOCK


class GateReport(BaseModel):
    """Full report of a gate evaluation."""

    gate: GateType
    overall: GateResult = GateResult.PASS
    check_results: list[GateCheckResult] = Field(default_factory=list)
    golden_task_results: list[TaskRunResult] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BaselineSnapshot(BaseModel):
    """A baseline metrics snapshot for comparison."""

    baseline_id: str = Field(default_factory=lambda: _new_id("BSL"))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    commit_hash: str = ""
    branch: str = ""
    metrics: list[MetricValue] = Field(default_factory=list)
    task_results: list[TaskRunResult] = Field(default_factory=list)


class RegressionRecord(BaseModel):
    """A detected regression (§ Regression Record Schema)."""

    regression_id: str = Field(default_factory=lambda: _new_id("REG"))
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    detected_by: str = ""

    indicator: RegressionIndicator = RegressionIndicator.RI_01
    description: str = ""

    metric_id: MetricId | None = None
    previous_value: float = 0.0
    current_value: float = 0.0
    threshold_value: float = 0.0

    affected_tasks: list[str] = Field(default_factory=list)

    severity: RegressionSeverity = RegressionSeverity.MEDIUM
    failure_category: str = ""
    root_cause: str = "unknown"

    triage_status: TriageStatus = TriageStatus.NEW
    assignee: str = ""

    resolved_at: datetime | None = None
    resolved_by: str = ""
    fix_commit: str = ""


class EvaluationRun(BaseModel):
    """A complete evaluation run combining tasks, metrics, and gate checks."""

    run_id: str = Field(default_factory=lambda: _new_id("EVAL"))
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    gate: GateType = GateType.G_PR
    commit_hash: str = ""
    branch: str = ""

    task_results: list[TaskRunResult] = Field(default_factory=list)
    metrics: list[MetricValue] = Field(default_factory=list)
    gate_report: GateReport | None = None
    regressions: list[RegressionRecord] = Field(default_factory=list)

    def complete(self) -> None:
        self.completed_at = datetime.now(UTC)
