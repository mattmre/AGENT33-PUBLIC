"""Improvement service — orchestrates research intake, lessons, metrics, and checklists."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agent33.improvement.checklists import ChecklistEvaluator, build_checklist
from agent33.improvement.metrics import MetricsTracker, default_metrics, percentile
from agent33.improvement.models import (
    ChecklistPeriod,
    ImprovementChecklist,
    IntakeClassification,
    IntakeContent,
    IntakeRelevance,
    IntakeStatus,
    LearningSignal,
    LearningSignalSeverity,
    LearningSignalType,
    LearningSummary,
    LearningThresholdCalibration,
    LearningTrendCategory,
    LearningTrendDimension,
    LearningTrendDirection,
    LearningTrendReport,
    LessonActionStatus,
    LessonLearned,
    MetricsSnapshot,
    ResearchIntake,
    RoadmapRefresh,
)
from agent33.improvement.persistence import (
    InMemoryLearningSignalStore,
    LearningPersistenceState,
    LearningSignalStore,
)
from agent33.improvement.quality import QualityScoringConfig, enrich_learning_signal

logger = logging.getLogger(__name__)

_SEVERITY_RANK: dict[LearningSignalSeverity, int] = {
    LearningSignalSeverity.LOW: 1,
    LearningSignalSeverity.MEDIUM: 2,
    LearningSignalSeverity.HIGH: 3,
    LearningSignalSeverity.CRITICAL: 4,
}


# Valid intake status transitions
_INTAKE_TRANSITIONS: dict[IntakeStatus, set[IntakeStatus]] = {
    IntakeStatus.SUBMITTED: {IntakeStatus.TRIAGED},
    IntakeStatus.TRIAGED: {IntakeStatus.ANALYZING},
    IntakeStatus.ANALYZING: {
        IntakeStatus.ACCEPTED,
        IntakeStatus.DEFERRED,
        IntakeStatus.REJECTED,
    },
    IntakeStatus.ACCEPTED: {IntakeStatus.TRACKED},
    IntakeStatus.DEFERRED: {IntakeStatus.TRIAGED},  # can re-triage
    IntakeStatus.REJECTED: set(),
    IntakeStatus.TRACKED: set(),
}


@dataclass(slots=True)
class LearningPersistencePolicy:
    """Persistence and intake quality policy for learning signals."""

    dedupe_window_minutes: int = 0
    retention_days: int | None = None
    max_signals: int | None = None
    max_generated_intakes: int | None = None
    auto_intake_min_quality: float = 0.0
    auto_intake_min_severity: LearningSignalSeverity = LearningSignalSeverity.HIGH
    auto_intake_max_items: int = 3


class ImprovementService:
    """In-memory service for continuous improvement operations."""

    @staticmethod
    def _normalize_auto_intake_min_severity(
        severity: LearningSignalSeverity | str,
    ) -> LearningSignalSeverity:
        if isinstance(severity, str):
            try:
                return LearningSignalSeverity(severity)
            except ValueError as exc:
                raise ValueError(
                    "auto_intake_min_severity must be one of: "
                    f"{', '.join(item.value for item in LearningSignalSeverity)}"
                ) from exc
        return severity

    def __init__(
        self,
        learning_store: LearningSignalStore | None = None,
        *,
        persistence_policy: LearningPersistencePolicy | None = None,
        max_metrics_snapshots: int = 100,
        quality_config: QualityScoringConfig | None = None,
    ) -> None:
        self._intakes: dict[str, ResearchIntake] = {}
        self._lessons: dict[str, LessonLearned] = {}
        self._checklists: dict[str, ImprovementChecklist] = {}
        self._refreshes: dict[str, RoadmapRefresh] = {}
        self._learning_signals: dict[str, LearningSignal] = {}
        self._learning_signal_intake_map: dict[str, str] = {}
        self._learning_store = learning_store or InMemoryLearningSignalStore()
        self._persistence_policy = persistence_policy or LearningPersistencePolicy()
        self._persistence_policy.auto_intake_min_severity = (
            self._normalize_auto_intake_min_severity(
                self._persistence_policy.auto_intake_min_severity
            )
        )
        self._quality_config = quality_config
        self._max_metrics_snapshots = max(1, max_metrics_snapshots)
        if not 0.0 <= self._persistence_policy.auto_intake_min_quality <= 1.0:
            raise ValueError("auto_intake_min_quality must be between 0.0 and 1.0")
        if self._persistence_policy.auto_intake_max_items < 1:
            raise ValueError("auto_intake_max_items must be at least 1")
        self._persisted_metrics_snapshots: list[MetricsSnapshot] = []
        self._load_learning_state()
        self._metrics_tracker = MetricsTracker()
        # Restore any persisted metrics snapshots into the tracker
        self._metrics_tracker._snapshots = list(self._persisted_metrics_snapshots)
        del self._persisted_metrics_snapshots
        self._checklist_evaluator = ChecklistEvaluator()

    # ----- Policy management --------------------------------------------------

    def update_policy(self, policy: LearningPersistencePolicy) -> None:
        """Replace the live persistence policy at runtime.

        Used by the tuning loop to adjust thresholds without reconstructing
        the service.
        """
        min_severity = self._normalize_auto_intake_min_severity(policy.auto_intake_min_severity)
        if not 0.0 <= policy.auto_intake_min_quality <= 1.0:
            raise ValueError("auto_intake_min_quality must be between 0.0 and 1.0")
        if policy.auto_intake_max_items < 1:
            raise ValueError("auto_intake_max_items must be at least 1")
        self._persistence_policy = LearningPersistencePolicy(
            dedupe_window_minutes=policy.dedupe_window_minutes,
            retention_days=policy.retention_days,
            max_signals=policy.max_signals,
            max_generated_intakes=policy.max_generated_intakes,
            auto_intake_min_quality=policy.auto_intake_min_quality,
            auto_intake_min_severity=min_severity,
            auto_intake_max_items=policy.auto_intake_max_items,
        )
        logger.info(
            "persistence_policy_updated",
            extra={
                "retention_days": policy.retention_days,
                "max_signals": policy.max_signals,
                "max_generated_intakes": policy.max_generated_intakes,
                "auto_intake_min_quality": policy.auto_intake_min_quality,
                "auto_intake_min_severity": min_severity.value,
                "auto_intake_max_items": policy.auto_intake_max_items,
            },
        )

    @property
    def persistence_policy(self) -> LearningPersistencePolicy:
        """Return the current live learning policy."""
        return self._persistence_policy

    # ----- Read-only accessors (for analytics) --------------------------------

    def all_intakes(self, tenant_id: str | None = None) -> list[ResearchIntake]:
        """Return copies of all research intakes, optionally filtered by tenant."""
        result = list(self._intakes.values())
        if tenant_id is not None:
            result = [i for i in result if i.tenant_id == tenant_id]
        return [i.model_copy(deep=True) for i in result]

    def all_lessons(self) -> list[LessonLearned]:
        """Return copies of all lessons learned."""
        return [lesson.model_copy(deep=True) for lesson in self._lessons.values()]

    def all_signals(self, tenant_id: str | None = None) -> list[LearningSignal]:
        """Return copies of all learning signals, optionally filtered by tenant."""
        result = list(self._learning_signals.values())
        if tenant_id is not None:
            result = [s for s in result if s.tenant_id == tenant_id]
        return [s.model_copy(deep=True) for s in result]

    def all_refreshes(self) -> list[RoadmapRefresh]:
        """Return copies of all roadmap refreshes."""
        return [r.model_copy(deep=True) for r in self._refreshes.values()]

    def all_metrics_snapshots(self, limit: int | None = None) -> list[MetricsSnapshot]:
        """Return copies of metrics snapshots (newest first)."""
        snapshots = self._metrics_tracker.list_snapshots(
            limit=limit or len(self._metrics_tracker._snapshots) or 1
        )
        return [s.model_copy(deep=True) for s in snapshots]

    # ----- Research Intake -------------------------------------------------

    def submit_intake(self, intake: ResearchIntake) -> ResearchIntake:
        """Submit a new research intake."""
        intake.disposition.status = IntakeStatus.SUBMITTED
        self._intakes[intake.intake_id] = intake
        if intake.generated_from_signal_id is not None:
            self._persist_learning_state()
        logger.info("intake_submitted", extra={"intake_id": intake.intake_id})
        return intake

    def get_intake(self, intake_id: str) -> ResearchIntake | None:
        return self._intakes.get(intake_id)

    def list_intakes(
        self,
        status: IntakeStatus | None = None,
        research_type: str | None = None,
        tenant_id: str | None = None,
    ) -> list[ResearchIntake]:
        result = list(self._intakes.values())
        if status is not None:
            result = [i for i in result if i.disposition.status == status]
        if research_type is not None:
            result = [i for i in result if i.classification.research_type.value == research_type]
        if tenant_id is not None:
            result = [i for i in result if i.tenant_id == tenant_id]
        return result

    def transition_intake(
        self,
        intake_id: str,
        new_status: IntakeStatus,
        *,
        decision_by: str = "",
        rationale: str = "",
        action_items: list[str] | None = None,
    ) -> ResearchIntake:
        """Transition an intake through the lifecycle state machine."""
        intake = self._intakes.get(intake_id)
        if intake is None:
            raise ValueError(f"Intake {intake_id} not found")

        current = intake.disposition.status
        allowed = _INTAKE_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            raise ValueError(f"Cannot transition from {current.value} to {new_status.value}")

        intake.disposition.status = new_status
        if decision_by:
            intake.disposition.decision_by = decision_by
        if rationale:
            intake.disposition.rationale = rationale
        if action_items:
            intake.disposition.action_items = action_items
        if new_status in (
            IntakeStatus.ACCEPTED,
            IntakeStatus.DEFERRED,
            IntakeStatus.REJECTED,
        ):
            intake.disposition.decision_date = datetime.now(UTC)

        logger.info(
            "intake_transitioned",
            extra={
                "intake_id": intake_id,
                "from_status": current.value,
                "to_status": new_status.value,
            },
        )
        if intake.generated_from_signal_id is not None:
            self._persist_learning_state()
        return intake

    # ----- Lessons Learned -------------------------------------------------

    def record_lesson(self, lesson: LessonLearned) -> LessonLearned:
        """Record a new lesson learned."""
        self._lessons[lesson.lesson_id] = lesson
        logger.info("lesson_recorded", extra={"lesson_id": lesson.lesson_id})
        return lesson

    def get_lesson(self, lesson_id: str) -> LessonLearned | None:
        return self._lessons.get(lesson_id)

    def list_lessons(
        self,
        phase: str | None = None,
        event_type: str | None = None,
    ) -> list[LessonLearned]:
        result = list(self._lessons.values())
        if phase is not None:
            result = [lesson for lesson in result if lesson.phase == phase]
        if event_type is not None:
            result = [lesson for lesson in result if lesson.event_type.value == event_type]
        return result

    def complete_lesson_action(
        self,
        lesson_id: str,
        action_index: int,
    ) -> LessonLearned:
        """Mark a specific action item as completed."""
        lesson = self._lessons.get(lesson_id)
        if lesson is None:
            raise ValueError(f"Lesson {lesson_id} not found")
        if action_index < 0 or action_index >= len(lesson.actions):
            raise ValueError(f"Action index {action_index} out of range")
        lesson.actions[action_index].status = LessonActionStatus.COMPLETED
        return lesson

    def verify_lesson(self, lesson_id: str, evidence: str = "") -> LessonLearned:
        """Mark a lesson as implemented and verified."""
        lesson = self._lessons.get(lesson_id)
        if lesson is None:
            raise ValueError(f"Lesson {lesson_id} not found")
        lesson.implemented = True
        lesson.verified_at = datetime.now(UTC)
        if evidence:
            lesson.evidence = evidence
        return lesson

    # ----- Improvement Checklists ------------------------------------------

    def create_checklist(
        self, period: ChecklistPeriod, reference: str = ""
    ) -> ImprovementChecklist:
        """Create a new periodic improvement checklist."""
        checklist = build_checklist(period, reference)
        self._checklists[checklist.checklist_id] = checklist
        return checklist

    def get_checklist(self, checklist_id: str) -> ImprovementChecklist | None:
        return self._checklists.get(checklist_id)

    def list_checklists(self, period: ChecklistPeriod | None = None) -> list[ImprovementChecklist]:
        result = list(self._checklists.values())
        if period is not None:
            result = [c for c in result if c.period == period]
        return result

    def complete_checklist_item(
        self,
        checklist_id: str,
        check_id: str,
        notes: str = "",
    ) -> ImprovementChecklist:
        """Mark a checklist item as completed."""
        checklist = self._checklists.get(checklist_id)
        if checklist is None:
            raise ValueError(f"Checklist {checklist_id} not found")
        item = self._checklist_evaluator.complete_item(checklist, check_id, notes)
        if item is None:
            raise ValueError(f"Check {check_id} not found in checklist")
        return checklist

    def evaluate_checklist(self, checklist_id: str) -> tuple[bool, list[str]]:
        """Evaluate a checklist for completion."""
        checklist = self._checklists.get(checklist_id)
        if checklist is None:
            raise ValueError(f"Checklist {checklist_id} not found")
        return self._checklist_evaluator.evaluate(checklist)

    # ----- Metrics ---------------------------------------------------------

    def save_metrics_snapshot(self, snapshot: MetricsSnapshot) -> MetricsSnapshot:
        """Save a metrics snapshot, enforce cap, and persist."""
        result = self._metrics_tracker.save_snapshot(snapshot)
        # Enforce max snapshots cap
        while len(self._metrics_tracker._snapshots) > self._max_metrics_snapshots:
            self._metrics_tracker._snapshots.pop(0)
        self._persist_learning_state()
        return result

    def latest_metrics(self) -> MetricsSnapshot | None:
        """Return the latest metrics snapshot."""
        return self._metrics_tracker.latest()

    def list_metrics_snapshots(self, limit: int = 10) -> list[MetricsSnapshot]:
        return self._metrics_tracker.list_snapshots(limit)

    def get_metric_trend(self, metric_id: str, periods: int = 4) -> tuple[str, list[float]]:
        """Return (trend, values) for a metric."""
        trend, values = self._metrics_tracker.get_trend(metric_id, periods)
        return trend.value, values

    def create_default_snapshot(self, period: str = "") -> MetricsSnapshot:
        """Create a snapshot with the five canonical metrics at defaults."""
        snapshot = MetricsSnapshot(
            period=period,
            metrics=default_metrics(),
        )
        return self._metrics_tracker.save_snapshot(snapshot)

    # ----- Roadmap Refresh -------------------------------------------------

    def record_refresh(self, refresh: RoadmapRefresh) -> RoadmapRefresh:
        """Record a roadmap refresh event."""
        self._refreshes[refresh.refresh_id] = refresh
        logger.info(
            "roadmap_refresh_recorded",
            extra={
                "refresh_id": refresh.refresh_id,
                "scope": refresh.scope.value,
            },
        )
        return refresh

    def get_refresh(self, refresh_id: str) -> RoadmapRefresh | None:
        return self._refreshes.get(refresh_id)

    def list_refreshes(self, scope: str | None = None) -> list[RoadmapRefresh]:
        result = list(self._refreshes.values())
        if scope is not None:
            result = [r for r in result if r.scope.value == scope]
        return result

    def complete_refresh(
        self,
        refresh_id: str,
        outcome: str = "",
        changes: list[str] | None = None,
    ) -> RoadmapRefresh:
        """Mark a roadmap refresh as completed."""
        refresh = self._refreshes.get(refresh_id)
        if refresh is None:
            raise ValueError(f"Refresh {refresh_id} not found")
        refresh.completed_at = datetime.now(UTC)
        if outcome:
            refresh.outcome = outcome
        if changes:
            refresh.changes_made = changes
        return refresh

    # ----- Learning Signals -------------------------------------------------

    def record_learning_signal(self, signal: LearningSignal) -> LearningSignal:
        """Record a learning signal."""
        enrich_learning_signal(signal, config=self._quality_config)
        signal.first_seen_at = signal.recorded_at
        signal.last_seen_at = signal.recorded_at
        duplicate = self._find_recent_duplicate(signal)
        if duplicate is not None:
            self._merge_duplicate_signal(duplicate, signal)
            self._persist_learning_state()
            logger.info(
                "learning_signal_deduplicated",
                extra={
                    "signal_id": duplicate.signal_id,
                    "occurrence_count": duplicate.occurrence_count,
                },
            )
            return duplicate

        self._learning_signals[signal.signal_id] = signal
        self._persist_learning_state()
        logger.info(
            "learning_signal_recorded",
            extra={
                "signal_id": signal.signal_id,
                "signal_type": signal.signal_type.value,
                "severity": signal.severity.value,
            },
        )
        return signal

    def list_learning_signals(
        self,
        signal_type: LearningSignalType | None = None,
        severity: LearningSignalSeverity | None = None,
        limit: int | None = 50,
        tenant_id: str | None = None,
    ) -> list[LearningSignal]:
        """List learning signals with optional filters."""
        result = list(self._learning_signals.values())
        if signal_type is not None:
            result = [s for s in result if s.signal_type == signal_type]
        if severity is not None:
            result = [s for s in result if s.severity == severity]
        if tenant_id is not None:
            result = [s for s in result if s.tenant_id == tenant_id]
        result.sort(key=lambda s: s.recorded_at, reverse=True)
        if limit is None:
            return result
        return result[: max(0, limit)]

    def summarize_learning_signals(
        self,
        limit: int = 50,
        *,
        tenant_id: str | None = None,
        window_days: int | None = None,
    ) -> LearningSummary:
        """Summarize recent learning signals."""
        now = datetime.now(UTC)
        all_scoped = self.list_learning_signals(limit=None, tenant_id=tenant_id)
        summary_signals = all_scoped
        previous_window_total: int | None = None
        trend_delta: int | None = None
        trend_direction = "stable"
        window_start_at: datetime | None = None

        if window_days is not None and window_days > 0:
            window_start_at = now - timedelta(days=window_days)
            previous_window_start = window_start_at - timedelta(days=window_days)
            summary_signals = [
                signal for signal in all_scoped if signal.recorded_at >= window_start_at
            ]
            previous_window_total = len(
                [
                    signal
                    for signal in all_scoped
                    if previous_window_start <= signal.recorded_at < window_start_at
                ]
            )
            trend_delta = len(summary_signals) - previous_window_total
            if trend_delta > 0:
                trend_direction = "up"
            elif trend_delta < 0:
                trend_direction = "down"

        signals = summary_signals[: max(0, limit)]
        counts_by_type: dict[str, int] = {}
        counts_by_severity: dict[str, int] = {}
        counts_by_tenant: dict[str, int] = {}
        latest_recorded_at = signals[0].recorded_at if signals else None

        quality_total = 0.0
        high_quality_signals = 0
        for signal in signals:
            stype = signal.signal_type.value
            ssev = signal.severity.value
            counts_by_type[stype] = counts_by_type.get(stype, 0) + 1
            counts_by_severity[ssev] = counts_by_severity.get(ssev, 0) + 1
            counts_by_tenant[signal.tenant_id] = counts_by_tenant.get(signal.tenant_id, 0) + 1
            quality_total += signal.quality_score
            if signal.quality_label == "high":
                high_quality_signals += 1

        return LearningSummary(
            total_signals=len(signals),
            counts_by_type=counts_by_type,
            counts_by_severity=counts_by_severity,
            counts_by_tenant=counts_by_tenant,
            latest_recorded_at=latest_recorded_at,
            average_quality_score=(round(quality_total / len(signals), 3) if signals else 0.0),
            high_quality_signals=high_quality_signals,
            tenant_id=tenant_id,
            window_days=window_days,
            window_start_at=window_start_at,
            previous_window_total=previous_window_total,
            trend_delta=trend_delta,
            trend_direction=trend_direction,
        )

    def trend_learning_signals(
        self,
        *,
        window_days: int = 7,
        dimension: LearningTrendDimension = LearningTrendDimension.SIGNAL_TYPE,
        tenant_id: str | None = None,
    ) -> LearningTrendReport:
        """Return dedup-aware trend analytics over current and previous windows."""
        if window_days < 1:
            raise ValueError("window_days must be at least 1")

        now = datetime.now(UTC)
        window_start_at = now - timedelta(days=window_days)
        previous_window_start_at = window_start_at - timedelta(days=window_days)

        current_signals_by_key: dict[str, int] = {}
        previous_signals_by_key: dict[str, int] = {}
        current_occurrences_by_key: dict[str, int] = {}
        previous_occurrences_by_key: dict[str, int] = {}
        total_current_signals = 0
        total_previous_signals = 0
        total_current_occurrences = 0
        total_previous_occurrences = 0

        for signal in self.list_learning_signals(limit=None, tenant_id=tenant_id):
            key = (
                signal.signal_type.value
                if dimension == LearningTrendDimension.SIGNAL_TYPE
                else signal.severity.value
            )
            occurrences = max(1, signal.occurrence_count)
            if signal.recorded_at >= window_start_at:
                current_signals_by_key[key] = current_signals_by_key.get(key, 0) + 1
                current_occurrences_by_key[key] = (
                    current_occurrences_by_key.get(key, 0) + occurrences
                )
                total_current_signals += 1
                total_current_occurrences += occurrences
            elif signal.recorded_at >= previous_window_start_at:
                previous_signals_by_key[key] = previous_signals_by_key.get(key, 0) + 1
                previous_occurrences_by_key[key] = (
                    previous_occurrences_by_key.get(key, 0) + occurrences
                )
                total_previous_signals += 1
                total_previous_occurrences += occurrences

        categories: list[LearningTrendCategory] = []
        for key in sorted(
            set(current_signals_by_key)
            | set(previous_signals_by_key)
            | set(current_occurrences_by_key)
            | set(previous_occurrences_by_key)
        ):
            current_signals = current_signals_by_key.get(key, 0)
            previous_signals = previous_signals_by_key.get(key, 0)
            current_occurrences = current_occurrences_by_key.get(key, 0)
            previous_occurrences = previous_occurrences_by_key.get(key, 0)
            signal_delta = current_signals - previous_signals
            occurrence_delta = current_occurrences - previous_occurrences

            direction = LearningTrendDirection.STABLE
            if occurrence_delta > 0 or (occurrence_delta == 0 and signal_delta > 0):
                direction = LearningTrendDirection.UP
            elif occurrence_delta < 0 or (occurrence_delta == 0 and signal_delta < 0):
                direction = LearningTrendDirection.DOWN

            categories.append(
                LearningTrendCategory(
                    key=key,
                    current_signals=current_signals,
                    previous_signals=previous_signals,
                    signal_delta=signal_delta,
                    current_occurrences=current_occurrences,
                    previous_occurrences=previous_occurrences,
                    occurrence_delta=occurrence_delta,
                    direction=direction,
                )
            )

        return LearningTrendReport(
            tenant_id=tenant_id,
            window_days=window_days,
            dimension=dimension,
            window_start_at=window_start_at,
            previous_window_start_at=previous_window_start_at,
            total_current_signals=total_current_signals,
            total_previous_signals=total_previous_signals,
            total_current_occurrences=total_current_occurrences,
            total_previous_occurrences=total_previous_occurrences,
            categories=categories,
        )

    @staticmethod
    def _percentile(values: list[float], p: float) -> float:
        return percentile(values, p)

    def calibrate_learning_thresholds(
        self,
        *,
        window_days: int = 30,
        target_auto_intakes_per_window: int = 3,
        tenant_id: str | None = None,
    ) -> LearningThresholdCalibration:
        """Calibrate retention and auto-intake thresholds from observed signals."""
        if window_days < 1:
            raise ValueError("window_days must be at least 1")
        if target_auto_intakes_per_window < 1:
            raise ValueError("target_auto_intakes_per_window must be at least 1")

        now = datetime.now(UTC)
        window_start_at = now - timedelta(days=window_days)
        sample = [
            signal
            for signal in self.list_learning_signals(limit=None, tenant_id=tenant_id)
            if signal.recorded_at >= window_start_at
        ]

        qualities = sorted((signal.quality_score for signal in sample), reverse=True)
        sample_signals = len(sample)
        sample_occurrences = sum(max(1, signal.occurrence_count) for signal in sample)
        daily_occurrence_rate = sample_occurrences / float(window_days)
        average_quality = round(sum(qualities) / sample_signals, 3) if sample_signals > 0 else 0.0
        quality_p75 = round(self._percentile(qualities, 0.75), 3)
        quality_p90 = round(self._percentile(qualities, 0.90), 3)
        high_or_critical = sum(
            1
            for signal in sample
            if signal.severity in {LearningSignalSeverity.HIGH, LearningSignalSeverity.CRITICAL}
        )
        high_or_critical_ratio = (
            round(high_or_critical / sample_signals, 3) if sample_signals > 0 else 0.0
        )

        if sample_signals == 0:
            recommended_quality = round(self._persistence_policy.auto_intake_min_quality, 3)
            recommended_max_items = min(target_auto_intakes_per_window, 1)
            recommended_severity = LearningSignalSeverity.HIGH.value
            rationale = [
                "No signals in the selected window; returning conservative defaults.",
            ]
        else:
            target_index = min(target_auto_intakes_per_window, len(qualities)) - 1
            recommended_quality = round(qualities[target_index], 3)
            recommended_max_items = min(target_auto_intakes_per_window, sample_signals)
            recommended_severity = (
                LearningSignalSeverity.HIGH.value
                if high_or_critical_ratio >= 0.4
                else LearningSignalSeverity.MEDIUM.value
            )
            rationale = [
                "Quality threshold targets the top-N signals in the selected window.",
                "Severity threshold adapts to observed high/critical share.",
            ]

        capacity = (
            self._persistence_policy.max_signals
            if self._persistence_policy.max_signals is not None
            and self._persistence_policy.max_signals > 0
            else 5000
        )
        safe_daily_rate = daily_occurrence_rate if daily_occurrence_rate > 0.0 else 1.0
        recommended_retention_days = int(round(capacity / safe_daily_rate))
        recommended_retention_days = max(30, min(365, recommended_retention_days))

        return LearningThresholdCalibration(
            tenant_id=tenant_id,
            window_days=window_days,
            target_auto_intakes_per_window=target_auto_intakes_per_window,
            sample_signals=sample_signals,
            sample_occurrences=sample_occurrences,
            observed_daily_occurrence_rate=round(daily_occurrence_rate, 3),
            observed_average_quality_score=average_quality,
            observed_quality_p75=quality_p75,
            observed_quality_p90=quality_p90,
            observed_high_or_critical_ratio=high_or_critical_ratio,
            recommended_auto_intake_min_quality=recommended_quality,
            recommended_auto_intake_min_severity=recommended_severity,
            recommended_auto_intake_max_items=recommended_max_items,
            recommended_retention_days=recommended_retention_days,
            policy_snapshot={
                "auto_intake_min_quality": round(
                    self._persistence_policy.auto_intake_min_quality, 3
                ),
                "auto_intake_min_severity": (
                    self._persistence_policy.auto_intake_min_severity.value
                ),
                "auto_intake_max_items": self._persistence_policy.auto_intake_max_items,
                "max_signals": self._persistence_policy.max_signals,
                "retention_days": self._persistence_policy.retention_days,
            },
            rationale=rationale,
        )

    def generate_intakes_from_learning_signals(
        self,
        *,
        min_severity: LearningSignalSeverity | None = None,
        max_items: int | None = None,
        tenant_id: str | None = None,
    ) -> list[ResearchIntake]:
        """Generate research intakes from qualifying signals.

        Uses an internal idempotency map so each signal produces at most one intake.
        """
        if min_severity is None:
            min_severity = self._persistence_policy.auto_intake_min_severity
        if max_items is None:
            max_items = self._persistence_policy.auto_intake_max_items
        if max_items <= 0:
            return []

        created: list[ResearchIntake] = []
        candidates = self.list_learning_signals(limit=None, tenant_id=tenant_id)
        candidates.sort(
            key=lambda signal: (
                _SEVERITY_RANK[signal.severity],
                signal.quality_score,
                signal.recorded_at,
            ),
            reverse=True,
        )
        for signal in candidates:
            if _SEVERITY_RANK[signal.severity] < _SEVERITY_RANK[min_severity]:
                continue
            if signal.quality_score < self._persistence_policy.auto_intake_min_quality:
                continue
            if signal.signal_id in self._learning_signal_intake_map:
                continue

            urgency = (
                "high"
                if signal.severity
                in {LearningSignalSeverity.HIGH, LearningSignalSeverity.CRITICAL}
                else "medium"
            )
            priority_score = {
                LearningSignalSeverity.LOW: 3,
                LearningSignalSeverity.MEDIUM: 5,
                LearningSignalSeverity.HIGH: 8,
                LearningSignalSeverity.CRITICAL: 10,
            }[signal.severity]
            priority_score = min(
                10,
                max(1, priority_score + round(signal.quality_score * 2)),
            )

            intake = self.submit_intake(
                ResearchIntake(
                    submitted_by="learning-service",
                    tenant_id=signal.tenant_id,
                    generated_from_signal_id=signal.signal_id,
                    automated_quality_score=signal.quality_score,
                    automated_quality_label=signal.quality_label,
                    classification=IntakeClassification(
                        research_type="internal",
                        category=f"learning:{signal.signal_type.value}",
                        urgency=urgency,
                    ),
                    content=IntakeContent(
                        title=f"Learning signal: {signal.summary}",
                        summary=signal.details or signal.summary,
                        source=signal.source,
                    ),
                    relevance=IntakeRelevance(
                        priority_score=priority_score,
                        impact_areas=[f"quality:{signal.quality_label}"],
                    ),
                )
            )
            self._learning_signal_intake_map[signal.signal_id] = intake.intake_id
            signal.related_intake_id = intake.intake_id
            signal.intake_generated = True
            created.append(intake)
            if len(created) >= max_items:
                break
        if created:
            self._persist_learning_state()
        return created

    def _load_learning_state(self) -> None:
        state = self._learning_store.load()
        for signal in state.signals:
            if signal.first_seen_at is None:
                signal.first_seen_at = signal.recorded_at
            if signal.last_seen_at is None:
                signal.last_seen_at = signal.recorded_at
        self._learning_signals = {signal.signal_id: signal for signal in state.signals}
        self._learning_signal_intake_map = dict(state.signal_intake_map)
        for intake in state.generated_intakes:
            self._intakes[intake.intake_id] = intake
        # Stash persisted metrics snapshots for later restoration into tracker
        if hasattr(self, "_metrics_tracker"):
            self._metrics_tracker._snapshots = list(state.metrics_snapshots)
        else:
            self._persisted_metrics_snapshots = list(state.metrics_snapshots)

    @staticmethod
    def _normalize_signal_field(value: str) -> str:
        return " ".join(value.strip().lower().split())

    def _signal_fingerprint(self, signal: LearningSignal) -> tuple[str, ...]:
        return (
            signal.tenant_id,
            signal.signal_type.value,
            self._normalize_signal_field(signal.summary),
            self._normalize_signal_field(signal.source),
        )

    def _find_recent_duplicate(self, signal: LearningSignal) -> LearningSignal | None:
        window_minutes = self._persistence_policy.dedupe_window_minutes
        if window_minutes <= 0:
            return None
        threshold = signal.recorded_at - timedelta(minutes=window_minutes)
        candidate_fingerprint = self._signal_fingerprint(signal)
        matches = [
            existing
            for existing in self._learning_signals.values()
            if existing.recorded_at >= threshold
            and self._signal_fingerprint(existing) == candidate_fingerprint
        ]
        if not matches:
            return None
        return max(matches, key=lambda existing: existing.recorded_at)

    def _merge_duplicate_signal(self, target: LearningSignal, incoming: LearningSignal) -> None:
        target.occurrence_count += 1
        target.last_seen_at = max(target.last_seen_at or target.recorded_at, incoming.recorded_at)

        if _SEVERITY_RANK[incoming.severity] > _SEVERITY_RANK[target.severity]:
            target.severity = incoming.severity
        if len(incoming.details) > len(target.details):
            target.details = incoming.details
        if incoming.source and not target.source:
            target.source = incoming.source

        # Merge contextual hints without discarding existing keys.
        for key, value in incoming.context.items():
            if key not in target.context:
                target.context[key] = value
        enrich_learning_signal(target, config=self._quality_config)

    def _prune_learning_state(self) -> tuple[list[LearningSignal], list[ResearchIntake]]:
        signals = list(self._learning_signals.values())
        retention_days = self._persistence_policy.retention_days
        if retention_days is not None and retention_days > 0:
            cutoff = datetime.now(UTC) - timedelta(days=retention_days)
            signals = [signal for signal in signals if signal.recorded_at >= cutoff]

        signals.sort(key=lambda signal: (signal.recorded_at, signal.signal_id), reverse=True)
        max_signals = self._persistence_policy.max_signals
        if max_signals is not None and max_signals >= 0:
            signals = signals[:max_signals]
        kept_signal_ids = {signal.signal_id for signal in signals}

        self._learning_signals = {
            signal_id: signal
            for signal_id, signal in self._learning_signals.items()
            if signal_id in kept_signal_ids
        }
        self._learning_signal_intake_map = {
            signal_id: intake_id
            for signal_id, intake_id in self._learning_signal_intake_map.items()
            if signal_id in kept_signal_ids
        }

        generated_intakes = [
            intake
            for intake in self._intakes.values()
            if intake.generated_from_signal_id is not None
            and intake.generated_from_signal_id in kept_signal_ids
        ]
        generated_intakes.sort(
            key=lambda intake: (intake.submitted_at, intake.intake_id),
            reverse=True,
        )
        max_generated_intakes = self._persistence_policy.max_generated_intakes
        if max_generated_intakes is not None and max_generated_intakes >= 0:
            generated_intakes = generated_intakes[:max_generated_intakes]

        kept_intake_ids = {intake.intake_id for intake in generated_intakes}
        self._intakes = {
            intake_id: intake
            for intake_id, intake in self._intakes.items()
            if intake.generated_from_signal_id is None or intake_id in kept_intake_ids
        }
        self._learning_signal_intake_map = {
            signal_id: intake_id
            for signal_id, intake_id in self._learning_signal_intake_map.items()
            if intake_id in kept_intake_ids
        }
        for signal in self._learning_signals.values():
            related = signal.related_intake_id
            if related is not None and related not in kept_intake_ids:
                signal.related_intake_id = None
                signal.intake_generated = False

        return signals, generated_intakes

    def _persist_learning_state(self) -> None:
        signals, generated_intakes = self._prune_learning_state()
        signals.sort(key=lambda signal: signal.signal_id)
        generated_intakes.sort(key=lambda intake: intake.intake_id)
        metrics_snapshots: list[MetricsSnapshot] = []
        if hasattr(self, "_metrics_tracker"):
            metrics_snapshots = list(self._metrics_tracker._snapshots)
        self._learning_store.save(
            LearningPersistenceState(
                signals=signals,
                generated_intakes=generated_intakes,
                signal_intake_map=dict(self._learning_signal_intake_map),
                metrics_snapshots=metrics_snapshots,
            )
        )
