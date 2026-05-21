"""Data models for continuous improvement, research intake, and lessons learned."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ResearchType(StrEnum):
    """Research intake classification type."""

    EXTERNAL = "external"
    INTERNAL = "internal"
    COMPETITIVE = "competitive"
    USER = "user"
    TECHNICAL = "technical"


class ResearchUrgency(StrEnum):
    """Urgency level for research intake."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IntakeStatus(StrEnum):
    """Research intake lifecycle status."""

    SUBMITTED = "submitted"
    TRIAGED = "triaged"
    ANALYZING = "analyzing"
    ACCEPTED = "accepted"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    TRACKED = "tracked"


class LessonEventType(StrEnum):
    """What kind of event triggered the lesson."""

    SUCCESS = "success"
    FAILURE = "failure"
    OBSERVATION = "observation"


class LessonActionStatus(StrEnum):
    """Status of a lesson-learned action item."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    WONT_FIX = "wont_fix"


class MetricTrend(StrEnum):
    """Direction of a metric over time."""

    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"


class ChecklistPeriod(StrEnum):
    """Which periodic checklist this belongs to."""

    PER_RELEASE = "per_release"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class RefreshScope(StrEnum):
    """Roadmap refresh scope."""

    MICRO = "micro"
    MINOR = "minor"
    MAJOR = "major"
    AD_HOC = "ad_hoc"


# ---------------------------------------------------------------------------
# Learning signals
# ---------------------------------------------------------------------------


class LearningSignalType(StrEnum):
    """Continuous learning signal classification."""

    BUG = "bug"
    INCIDENT = "incident"
    FEEDBACK = "feedback"
    PERFORMANCE = "performance"
    SECURITY = "security"
    PROCESS = "process"


class LearningSignalSeverity(StrEnum):
    """Impact/severity level for a learning signal."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class LearningSignal(BaseModel):
    """A continuous-learning signal record (LS-*)."""

    signal_id: str = Field(default_factory=lambda: _new_id("LS"))
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    signal_type: LearningSignalType = LearningSignalType.FEEDBACK
    severity: LearningSignalSeverity = LearningSignalSeverity.MEDIUM
    tenant_id: str = "default"
    summary: str
    details: str = ""
    source: str = ""
    context: dict[str, str] = Field(default_factory=dict)
    quality_score: float = 0.0
    quality_label: str = "low"
    quality_reasons: list[str] = Field(default_factory=list)
    enrichment: dict[str, str] = Field(default_factory=dict)
    occurrence_count: int = 1
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    intake_generated: bool = False
    related_intake_id: str | None = None


class LearningSummary(BaseModel):
    """Aggregated snapshot of recent learning signals."""

    total_signals: int = 0
    counts_by_type: dict[str, int] = Field(default_factory=dict)
    counts_by_severity: dict[str, int] = Field(default_factory=dict)
    counts_by_tenant: dict[str, int] = Field(default_factory=dict)
    latest_recorded_at: datetime | None = None
    average_quality_score: float = 0.0
    high_quality_signals: int = 0
    tenant_id: str | None = None
    window_days: int | None = None
    window_start_at: datetime | None = None
    previous_window_total: int | None = None
    trend_delta: int | None = None
    trend_direction: str = "stable"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LearningTrendDimension(StrEnum):
    """Grouping dimension for learning trend reporting."""

    SIGNAL_TYPE = "signal_type"
    SEVERITY = "severity"


class LearningTrendDirection(StrEnum):
    """Direction values for learning trend deltas."""

    UP = "up"
    DOWN = "down"
    STABLE = "stable"


class LearningTrendCategory(BaseModel):
    """Current vs previous-window trend snapshot for one category key."""

    key: str
    current_signals: int = 0
    previous_signals: int = 0
    signal_delta: int = 0
    current_occurrences: int = 0
    previous_occurrences: int = 0
    occurrence_delta: int = 0
    direction: LearningTrendDirection = LearningTrendDirection.STABLE


class LearningTrendReport(BaseModel):
    """Dedup-aware trend report for learning signals."""

    tenant_id: str | None = None
    window_days: int = 7
    dimension: LearningTrendDimension = LearningTrendDimension.SIGNAL_TYPE
    window_start_at: datetime
    previous_window_start_at: datetime
    total_current_signals: int = 0
    total_previous_signals: int = 0
    total_current_occurrences: int = 0
    total_previous_occurrences: int = 0
    categories: list[LearningTrendCategory] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LearningThresholdCalibration(BaseModel):
    """Calibration report for retention and auto-intake tuning."""

    tenant_id: str | None = None
    window_days: int = 30
    target_auto_intakes_per_window: int = 3
    sample_signals: int = 0
    sample_occurrences: int = 0
    observed_daily_occurrence_rate: float = 0.0
    observed_average_quality_score: float = 0.0
    observed_quality_p75: float = 0.0
    observed_quality_p90: float = 0.0
    observed_high_or_critical_ratio: float = 0.0
    recommended_auto_intake_min_quality: float = 0.0
    recommended_auto_intake_min_severity: str = "high"
    recommended_auto_intake_max_items: int = 0
    recommended_retention_days: int = 180
    policy_snapshot: dict[str, float | int | str | None] = Field(default_factory=dict)
    rationale: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Research Intake models
# ---------------------------------------------------------------------------


class IntakeClassification(BaseModel):
    """Classification section of a research intake."""

    research_type: ResearchType = ResearchType.EXTERNAL
    category: str = ""
    urgency: ResearchUrgency = ResearchUrgency.MEDIUM


class IntakeContent(BaseModel):
    """Content section of a research intake."""

    title: str
    summary: str = ""
    source: str = ""
    source_date: str = ""


class IntakeRelevance(BaseModel):
    """Relevance section of a research intake."""

    impact_areas: list[str] = Field(default_factory=list)
    affected_phases: list[int] = Field(default_factory=list)
    affected_agents: list[str] = Field(default_factory=list)
    priority_score: int = 5  # 1-10


class IntakeAnalysis(BaseModel):
    """Analysis section of a research intake."""

    key_findings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)


class IntakeDisposition(BaseModel):
    """Disposition section of a research intake."""

    status: IntakeStatus = IntakeStatus.SUBMITTED
    decision_date: datetime | None = None
    decision_by: str = ""
    rationale: str = ""
    action_items: list[str] = Field(default_factory=list)


class IntakeTracking(BaseModel):
    """Tracking section of a research intake."""

    backlog_refs: list[str] = Field(default_factory=list)
    roadmap_impact: str = "tbd"  # yes | no | tbd
    implementation_target: str = ""


class ResearchIntake(BaseModel):
    """A research intake record (RI-*)."""

    intake_id: str = Field(default_factory=lambda: _new_id("RI"))
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    submitted_by: str = ""
    tenant_id: str = "default"
    generated_from_signal_id: str | None = None
    automated_quality_score: float | None = None
    automated_quality_label: str | None = None

    classification: IntakeClassification = Field(
        default_factory=IntakeClassification,
    )
    content: IntakeContent = Field(
        default_factory=lambda: IntakeContent(title="Untitled"),
    )
    relevance: IntakeRelevance = Field(default_factory=IntakeRelevance)
    analysis: IntakeAnalysis = Field(default_factory=IntakeAnalysis)
    disposition: IntakeDisposition = Field(default_factory=IntakeDisposition)
    tracking: IntakeTracking = Field(default_factory=IntakeTracking)


# ---------------------------------------------------------------------------
# Lessons Learned models
# ---------------------------------------------------------------------------


class LessonAction(BaseModel):
    """An action item attached to a lesson learned."""

    description: str
    status: LessonActionStatus = LessonActionStatus.PENDING
    owner: str = ""
    target_date: str = ""


class LessonLearned(BaseModel):
    """A lesson-learned record (LL-*)."""

    lesson_id: str = Field(default_factory=lambda: _new_id("LL"))
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    recorded_by: str = ""

    # Context
    phase: str = ""
    release: str = ""
    event_type: LessonEventType = LessonEventType.OBSERVATION

    # Description
    what_happened: str = ""
    root_cause: str = ""
    impact: str = ""

    # Learning
    insight: str = ""
    recommendation: str = ""
    applies_to: list[str] = Field(default_factory=list)

    # Actions
    actions: list[LessonAction] = Field(default_factory=list)

    # Verification
    implemented: bool = False
    verified_at: datetime | None = None
    evidence: str = ""


# ---------------------------------------------------------------------------
# Improvement Metrics
# ---------------------------------------------------------------------------


class ImprovementMetric(BaseModel):
    """A single improvement metric value (IM-01..IM-05)."""

    metric_id: str
    name: str
    baseline: float = 0.0
    current: float = 0.0
    target: float = 0.0
    unit: str = ""
    trend: MetricTrend = MetricTrend.STABLE


class MetricsSnapshot(BaseModel):
    """A point-in-time snapshot of all improvement metrics."""

    snapshot_id: str = Field(default_factory=lambda: _new_id("MSN"))
    period: str = ""  # e.g. "2026-Q1"
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metrics: list[ImprovementMetric] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Improvement Checklists
# ---------------------------------------------------------------------------


class ChecklistItem(BaseModel):
    """A single improvement checklist item (CI-01..CI-15)."""

    check_id: str
    name: str
    completed: bool = False
    notes: str = ""


class ImprovementChecklist(BaseModel):
    """A periodic improvement checklist."""

    checklist_id: str = Field(default_factory=lambda: _new_id("CKL"))
    period: ChecklistPeriod
    reference: str = ""  # e.g. release version or "2026-01"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    items: list[ChecklistItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Roadmap Refresh
# ---------------------------------------------------------------------------


class RoadmapRefresh(BaseModel):
    """A roadmap refresh event record."""

    refresh_id: str = Field(default_factory=lambda: _new_id("RMR"))
    scope: RefreshScope = RefreshScope.MICRO
    scheduled_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    participants: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)
    outcome: str = ""
    changes_made: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Analytics Dashboard models
# ---------------------------------------------------------------------------


class IntakeFunnelStep(BaseModel):
    """A single step in the intake funnel."""

    step: str
    count: int
    conversion_rate: float


class IntakeFunnelReport(BaseModel):
    """Intake funnel breakdown showing counts and conversion rates at each stage."""

    tenant_id: str | None = None
    total_submitted: int
    steps: list[IntakeFunnelStep] = Field(default_factory=list)
    terminal_counts: dict[str, int] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LessonActionCompletionReport(BaseModel):
    """Aggregate lesson-action completion metrics."""

    total_lessons: int
    total_actions: int
    completed_actions: int
    pending_actions: int
    in_progress_actions: int
    wont_fix_actions: int
    completion_rate: float
    by_event_type: dict[str, dict[str, int]] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChecklistCompletionReport(BaseModel):
    """Aggregate checklist item completion metrics."""

    period: str | None = None
    total_checklists: int
    total_items: int
    completed_items: int
    completion_rate: float
    by_period: dict[str, dict[str, int]] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SignalToIntakeReport(BaseModel):
    """Signal-to-intake conversion metrics."""

    total_signals: int
    signals_with_intake: int
    conversion_rate: float
    by_signal_type: dict[str, dict[str, int]] = Field(default_factory=dict)
    by_severity: dict[str, dict[str, int]] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class QualityBucket(BaseModel):
    """A single histogram bucket for quality score distribution."""

    range_start: float
    range_end: float
    count: int


class QualityDistribution(BaseModel):
    """Histogram and statistics for quality score distribution."""

    bucket_size: float
    buckets: list[QualityBucket] = Field(default_factory=list)
    total_signals: int
    mean: float
    median: float
    p75: float
    p90: float
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MetricsTimeSeriesPoint(BaseModel):
    """A single data point in a metrics time series."""

    captured_at: datetime
    period: str
    value: float


class MetricsTimeSeries(BaseModel):
    """Chart-ready time series for one improvement metric."""

    metric_id: str
    metric_name: str
    unit: str
    points: list[MetricsTimeSeriesPoint] = Field(default_factory=list)
    trend: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RefreshCadenceReport(BaseModel):
    """Roadmap refresh cadence analytics."""

    total_refreshes: int
    completed_refreshes: int
    by_scope: dict[str, int] = Field(default_factory=dict)
    average_days_between: float | None = None
    last_refresh_at: datetime | None = None
    days_since_last_refresh: float | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DashboardSummary(BaseModel):
    """Composite analytics dashboard summary."""

    intake_funnel: IntakeFunnelReport
    lesson_actions: LessonActionCompletionReport
    checklist_completion: ChecklistCompletionReport
    signal_to_intake: SignalToIntakeReport
    quality_distribution: QualityDistribution
    refresh_cadence: RefreshCadenceReport
    metrics_overview: list[MetricsTimeSeries] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
