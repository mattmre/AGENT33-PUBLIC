"""REST endpoints for continuous improvement, research intake, and lessons learned."""

from pathlib import Path
from typing import Any, overload

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agent33.api.routes.tenant_access import require_tenant_context
from agent33.config import settings
from agent33.improvement.analytics import AnalyticsService
from agent33.improvement.models import (
    ChecklistPeriod,
    ImprovementMetric,
    IntakeClassification,
    IntakeContent,
    IntakeRelevance,
    IntakeStatus,
    LearningSignal,
    LearningSignalSeverity,
    LearningSignalType,
    LearningTrendDimension,
    LessonAction,
    LessonEventType,
    LessonLearned,
    MetricsSnapshot,
    RefreshScope,
    ResearchIntake,
    RoadmapRefresh,
)
from agent33.improvement.persistence import (
    FileLearningSignalStore,
    InMemoryLearningSignalStore,
    LearningSignalStore,
    SQLiteLearningSignalStore,
    backup_learning_state,
    migrate_file_learning_state_to_db,
    restore_learning_state,
    should_migrate_file_learning_state_to_db,
)
from agent33.improvement.quality import QualityScoringConfig
from agent33.improvement.repo_ingestion import (
    FeatureCandidateInput,
    RepoHarvestRecord,
    build_competitive_intake,
    score_feature_candidate,
)
from agent33.improvement.service import ImprovementService, LearningPersistencePolicy
from agent33.improvement.tuning import TuningLoopService
from agent33.security.permissions import check_permission, require_scope

router = APIRouter(prefix="/v1/improvements", tags=["improvements"])


def _build_improvement_service() -> ImprovementService:
    backend = settings.improvement_learning_persistence_backend.strip().lower()
    store: LearningSignalStore
    if backend == "file":
        store = FileLearningSignalStore(
            path=str(Path(settings.improvement_learning_persistence_path)),
            on_corruption=settings.improvement_learning_file_corruption_behavior,
        )
    elif backend in {"db", "sqlite"}:
        if settings.improvement_learning_persistence_migrate_on_start:
            file_path = str(Path(settings.improvement_learning_persistence_path))
            db_path = str(Path(settings.improvement_learning_persistence_db_path))
            if should_migrate_file_learning_state_to_db(
                file_path=file_path,
                db_path=db_path,
                on_file_corruption=settings.improvement_learning_file_corruption_behavior,
                on_db_corruption=settings.improvement_learning_db_corruption_behavior,
            ):
                migrate_file_learning_state_to_db(
                    file_path=file_path,
                    db_path=db_path,
                    on_file_corruption=(settings.improvement_learning_file_corruption_behavior),
                    backup_path=(
                        str(Path(settings.improvement_learning_persistence_migration_backup_path))
                        if settings.improvement_learning_persistence_migration_backup_on_start
                        else None
                    ),
                )
        store = SQLiteLearningSignalStore(
            path=str(Path(settings.improvement_learning_persistence_db_path)),
            on_corruption=settings.improvement_learning_db_corruption_behavior,
        )
    elif backend == "memory":
        store = InMemoryLearningSignalStore()
    else:
        raise ValueError(
            "Unsupported improvement learning persistence backend: "
            f"{settings.improvement_learning_persistence_backend}"
        )
    quality_cfg = QualityScoringConfig(
        weight_summary=settings.improvement_quality_weight_summary,
        weight_details=settings.improvement_quality_weight_details,
        weight_source=settings.improvement_quality_weight_source,
        weight_context=settings.improvement_quality_weight_context,
        weight_severity=settings.improvement_quality_weight_severity,
        high_threshold=settings.improvement_quality_high_threshold,
        medium_threshold=settings.improvement_quality_medium_threshold,
    )
    return ImprovementService(
        learning_store=store,
        persistence_policy=LearningPersistencePolicy(
            dedupe_window_minutes=settings.improvement_learning_dedupe_window_minutes,
            retention_days=settings.improvement_learning_retention_days,
            max_signals=settings.improvement_learning_max_signals,
            max_generated_intakes=settings.improvement_learning_max_generated_intakes,
            auto_intake_min_quality=settings.improvement_learning_auto_intake_min_quality,
            auto_intake_min_severity=LearningSignalSeverity(
                settings.improvement_learning_auto_intake_min_severity
            ),
            auto_intake_max_items=settings.improvement_learning_auto_intake_max_items,
        ),
        max_metrics_snapshots=settings.improvement_learning_max_metrics_snapshots,
        quality_config=quality_cfg,
    )


_service = _build_improvement_service()


def get_improvement_service() -> ImprovementService:
    """Return the improvement service singleton (for route composition/testing)."""
    return _service


_analytics: AnalyticsService | None = None


def get_analytics_service() -> AnalyticsService:
    """Return (lazily created) analytics service singleton."""
    global _analytics  # noqa: PLW0603
    if _analytics is None:
        _analytics = AnalyticsService(get_improvement_service())
    return _analytics


_tuning: TuningLoopService | None = None


def get_tuning_service() -> TuningLoopService:
    """Return (lazily created) tuning loop service singleton."""
    global _tuning  # noqa: PLW0603
    if _tuning is None:
        _tuning = TuningLoopService(get_improvement_service(), settings=settings)
    return _tuning


def _reset_service() -> None:
    """Reset singleton for testing.

    Re-reads settings, so monkeypatching settings first has effect.
    """
    global _service, _analytics, _tuning  # noqa: PLW0603
    _service = _build_improvement_service()
    _analytics = None
    _tuning = None


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class SubmitIntakeRequest(BaseModel):
    title: str
    summary: str = ""
    source: str = ""
    submitted_by: str = ""
    tenant_id: str = "default"
    research_type: str = "external"
    category: str = ""
    urgency: str = "medium"
    impact_areas: list[str] = Field(default_factory=list)
    affected_phases: list[int] = Field(default_factory=list)
    priority_score: int = 5


class TransitionIntakeRequest(BaseModel):
    new_status: str
    decision_by: str = ""
    rationale: str = ""
    action_items: list[str] = Field(default_factory=list)


class RecordLessonRequest(BaseModel):
    recorded_by: str = ""
    phase: str = ""
    release: str = ""
    event_type: str = "observation"
    what_happened: str = ""
    root_cause: str = ""
    impact: str = ""
    insight: str = ""
    recommendation: str = ""
    applies_to: list[str] = Field(default_factory=list)
    actions: list[dict[str, str]] = Field(default_factory=list)


class CompleteLessonActionRequest(BaseModel):
    action_index: int


class VerifyLessonRequest(BaseModel):
    evidence: str = ""


class CreateChecklistRequest(BaseModel):
    period: str
    reference: str = ""


class CompleteCheckItemRequest(BaseModel):
    check_id: str
    notes: str = ""


class SaveSnapshotRequest(BaseModel):
    period: str = ""
    metrics: list[dict[str, Any]] = Field(default_factory=list)


class RecordRefreshRequest(BaseModel):
    scope: str = "micro"
    participants: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)


class CompleteRefreshRequest(BaseModel):
    outcome: str = ""
    changes: list[str] = Field(default_factory=list)


class RecordLearningSignalRequest(BaseModel):
    signal_type: str | None = None
    type: str | None = None
    severity: str
    summary: str
    details: str = ""
    source: str = ""
    tenant_id: str = "default"
    context: dict[str, str] = Field(default_factory=dict)


class BatchRepoIntakeRequest(BaseModel):
    records: list[RepoHarvestRecord] = Field(min_length=1, max_length=100)
    submitted_by: str = "repo-harvester"
    tenant_id: str = "default"


class ScoreFeatureCandidatesRequest(BaseModel):
    candidates: list[FeatureCandidateInput] = Field(min_length=1, max_length=100)
    top_n: int = Field(default=10, ge=1, le=100)


class BackupLearningStateRequest(BaseModel):
    backup_path: str = ""


class RestoreLearningStateRequest(BaseModel):
    backup_path: str


def _ensure_learning_enabled() -> None:
    if not settings.improvement_learning_enabled:
        raise HTTPException(status_code=404, detail="Not found")


def _request_tenant_context(request: Request) -> tuple[str, list[str]]:
    tenant_id, scopes = require_tenant_context(request)
    return tenant_id, scopes


@overload
def _resolve_tenant_id(
    request: Request,
    requested_tenant_id: str | None,
    *,
    default: str,
) -> str: ...


@overload
def _resolve_tenant_id(
    request: Request,
    requested_tenant_id: str | None,
    *,
    default: str | None = None,
) -> str | None: ...


def _resolve_tenant_id(
    request: Request,
    requested_tenant_id: str | None,
    *,
    default: str | None = None,
) -> str | None:
    tenant_id, scopes = _request_tenant_context(request)
    is_admin = check_permission("admin", scopes) if scopes else False
    normalized_requested = requested_tenant_id or None

    if tenant_id and not is_admin:
        if normalized_requested not in {None, "default", tenant_id}:
            raise HTTPException(
                status_code=403,
                detail="Tenant mismatch for authenticated principal",
            )
        return tenant_id

    if normalized_requested is not None:
        return normalized_requested
    if tenant_id:
        return tenant_id
    return default


def _enforce_intake_access(request: Request, intake: ResearchIntake | None) -> ResearchIntake:
    if intake is None:
        raise HTTPException(status_code=404, detail="Intake not found")

    tenant_id, scopes = _request_tenant_context(request)
    is_admin = check_permission("admin", scopes) if scopes else False
    if tenant_id and not is_admin and intake.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Intake not found")
    return intake


# ---------------------------------------------------------------------------
# Research Intake endpoints
# ---------------------------------------------------------------------------


@router.post("/intakes")
def submit_intake(req: SubmitIntakeRequest, request: Request) -> dict[str, Any]:
    """Submit a new research intake."""
    try:
        intake = ResearchIntake(
            submitted_by=req.submitted_by,
            tenant_id=_resolve_tenant_id(request, req.tenant_id, default="default"),
            classification=IntakeClassification(
                research_type=req.research_type,
                category=req.category,
                urgency=req.urgency,
            ),
            content=IntakeContent(
                title=req.title,
                summary=req.summary,
                source=req.source,
            ),
            relevance=IntakeRelevance(
                impact_areas=req.impact_areas,
                affected_phases=req.affected_phases,
                priority_score=req.priority_score,
            ),
        )
        result = _service.submit_intake(intake)
        return result.model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/intakes/competitive/repos")
def submit_competitive_repo_intakes(
    req: BatchRepoIntakeRequest, request: Request
) -> dict[str, Any]:
    """Submit a batch of competitive intakes derived from repository metadata.

    Body-supplied tenant IDs are accepted only when they match the authenticated
    tenant or the caller is admin.
    """
    tenant_id = _resolve_tenant_id(request, req.tenant_id, default="default")
    try:
        created_intakes = [
            _service.submit_intake(
                build_competitive_intake(
                    record,
                    submitted_by=req.submitted_by,
                    tenant_id=tenant_id,
                )
            ).model_dump(mode="json")
            for record in req.records
        ]
        return {"created_intakes": created_intakes}
    except HTTPException:
        raise
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/feature-candidates/score")
def score_feature_candidates(req: ScoreFeatureCandidatesRequest) -> dict[str, Any]:
    """Score and prioritize feature candidates based on weighted heuristics."""
    try:
        scored = [score_feature_candidate(candidate) for candidate in req.candidates]
        prioritized = sorted(scored, key=lambda c: c.weighted_priority, reverse=True)[: req.top_n]
        return {
            "scored": [candidate.model_dump(mode="json") for candidate in scored],
            "prioritized": [candidate.model_dump(mode="json") for candidate in prioritized],
        }
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/intakes")
def list_intakes(
    request: Request,
    status: str | None = None,
    research_type: str | None = None,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    """List research intakes with optional filters."""
    intake_status = None
    if status is not None:
        try:
            intake_status = IntakeStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}") from None
    resolved_tenant_id = _resolve_tenant_id(request, tenant_id)
    intakes = _service.list_intakes(
        status=intake_status,
        research_type=research_type,
        tenant_id=resolved_tenant_id,
    )
    return [i.model_dump(mode="json") for i in intakes]


@router.get("/intakes/{intake_id}")
def get_intake(intake_id: str, request: Request) -> dict[str, Any]:
    """Get a specific research intake."""
    intake = _enforce_intake_access(request, _service.get_intake(intake_id))
    return intake.model_dump(mode="json")


@router.post("/intakes/{intake_id}/transition")
def transition_intake(
    intake_id: str, req: TransitionIntakeRequest, request: Request
) -> dict[str, Any]:
    """Transition an intake through its lifecycle."""
    try:
        new_status = IntakeStatus(req.new_status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {req.new_status}") from None
    _enforce_intake_access(request, _service.get_intake(intake_id))
    try:
        result = _service.transition_intake(
            intake_id,
            new_status,
            decision_by=req.decision_by,
            rationale=req.rationale,
            action_items=req.action_items if req.action_items else None,
        )
        return result.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


# ---------------------------------------------------------------------------
# Lessons Learned endpoints
# ---------------------------------------------------------------------------


@router.post("/lessons")
def record_lesson(req: RecordLessonRequest) -> dict[str, Any]:
    """Record a new lesson learned."""
    try:
        actions = [
            LessonAction(
                description=a.get("description", ""),
                owner=a.get("owner", ""),
                target_date=a.get("target_date", ""),
            )
            for a in req.actions
        ]
        lesson = LessonLearned(
            recorded_by=req.recorded_by,
            phase=req.phase,
            release=req.release,
            event_type=LessonEventType(req.event_type),
            what_happened=req.what_happened,
            root_cause=req.root_cause,
            impact=req.impact,
            insight=req.insight,
            recommendation=req.recommendation,
            applies_to=req.applies_to,
            actions=actions,
        )
        result = _service.record_lesson(lesson)
        return result.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/lessons")
def list_lessons(
    phase: str | None = None,
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    """List lessons learned with optional filters."""
    return [
        lesson.model_dump(mode="json")
        for lesson in _service.list_lessons(phase=phase, event_type=event_type)
    ]


@router.get("/lessons/{lesson_id}")
def get_lesson(lesson_id: str) -> dict[str, Any]:
    """Get a specific lesson learned."""
    lesson = _service.get_lesson(lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return lesson.model_dump(mode="json")


@router.post("/lessons/{lesson_id}/complete-action")
def complete_lesson_action(lesson_id: str, req: CompleteLessonActionRequest) -> dict[str, Any]:
    """Mark a lesson action item as completed."""
    try:
        result = _service.complete_lesson_action(lesson_id, req.action_index)
        return result.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/lessons/{lesson_id}/verify")
def verify_lesson(lesson_id: str, req: VerifyLessonRequest) -> dict[str, Any]:
    """Mark a lesson as implemented and verified."""
    try:
        result = _service.verify_lesson(lesson_id, evidence=req.evidence)
        return result.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


# ---------------------------------------------------------------------------
# Checklist endpoints
# ---------------------------------------------------------------------------


@router.post("/checklists")
def create_checklist(req: CreateChecklistRequest) -> dict[str, Any]:
    """Create a new periodic improvement checklist."""
    try:
        period = ChecklistPeriod(req.period)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid period: {req.period}") from None
    checklist = _service.create_checklist(period, req.reference)
    return checklist.model_dump(mode="json")


@router.get("/checklists")
def list_checklists(period: str | None = None) -> list[dict[str, Any]]:
    """List improvement checklists."""
    p = None
    if period is not None:
        try:
            p = ChecklistPeriod(period)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid period: {period}") from None
    return [c.model_dump(mode="json") for c in _service.list_checklists(p)]


@router.get("/checklists/{checklist_id}")
def get_checklist(checklist_id: str) -> dict[str, Any]:
    """Get a specific checklist."""
    checklist = _service.get_checklist(checklist_id)
    if checklist is None:
        raise HTTPException(status_code=404, detail="Checklist not found")
    return checklist.model_dump(mode="json")


@router.post("/checklists/{checklist_id}/complete")
def complete_checklist_item(checklist_id: str, req: CompleteCheckItemRequest) -> dict[str, Any]:
    """Complete a checklist item."""
    try:
        result = _service.complete_checklist_item(checklist_id, req.check_id, req.notes)
        return result.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/checklists/{checklist_id}/evaluate")
def evaluate_checklist(checklist_id: str) -> dict[str, Any]:
    """Evaluate a checklist for completion."""
    try:
        all_complete, incomplete = _service.evaluate_checklist(checklist_id)
        return {"complete": all_complete, "incomplete": incomplete}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


# ---------------------------------------------------------------------------
# Metrics endpoints
# ---------------------------------------------------------------------------


@router.get("/metrics")
def get_latest_metrics() -> dict[str, Any]:
    """Get the latest metrics snapshot."""
    snapshot = _service.latest_metrics()
    if snapshot is None:
        return {"snapshot": None}
    return snapshot.model_dump(mode="json")


@router.get("/metrics/history")
def get_metrics_history(limit: int = 10) -> list[dict[str, Any]]:
    """Get metrics snapshot history."""
    return [s.model_dump(mode="json") for s in _service.list_metrics_snapshots(limit)]


@router.post("/metrics/snapshot")
def save_metrics_snapshot(req: SaveSnapshotRequest) -> dict[str, Any]:
    """Save a new metrics snapshot."""
    try:
        metrics = [ImprovementMetric(**m) for m in req.metrics] if req.metrics else []
        snapshot = MetricsSnapshot(period=req.period, metrics=metrics)
        result = _service.save_metrics_snapshot(snapshot)
        return result.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/metrics/default-snapshot")
def create_default_snapshot(period: str = "") -> dict[str, Any]:
    """Create a snapshot with canonical metrics at default values."""
    snapshot = _service.create_default_snapshot(period)
    return snapshot.model_dump(mode="json")


@router.get("/metrics/trend/{metric_id}")
def get_metric_trend(metric_id: str, periods: int = 4) -> dict[str, Any]:
    """Get trend data for a specific metric."""
    trend, values = _service.get_metric_trend(metric_id, periods)
    return {"metric_id": metric_id, "trend": trend, "values": values}


# ---------------------------------------------------------------------------
# Roadmap Refresh endpoints
# ---------------------------------------------------------------------------


@router.post("/refreshes")
def record_refresh(req: RecordRefreshRequest) -> dict[str, Any]:
    """Record a roadmap refresh event."""
    try:
        refresh = RoadmapRefresh(
            scope=RefreshScope(req.scope),
            participants=req.participants,
            activities=req.activities,
        )
        result = _service.record_refresh(refresh)
        return result.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/refreshes")
def list_refreshes(scope: str | None = None) -> list[dict[str, Any]]:
    """List roadmap refresh events."""
    return [r.model_dump(mode="json") for r in _service.list_refreshes(scope=scope)]


@router.get("/refreshes/{refresh_id}")
def get_refresh(refresh_id: str) -> dict[str, Any]:
    """Get a specific roadmap refresh."""
    refresh = _service.get_refresh(refresh_id)
    if refresh is None:
        raise HTTPException(status_code=404, detail="Refresh not found")
    return refresh.model_dump(mode="json")


@router.post("/refreshes/{refresh_id}/complete")
def complete_refresh(refresh_id: str, req: CompleteRefreshRequest) -> dict[str, Any]:
    """Mark a roadmap refresh as completed."""
    try:
        result = _service.complete_refresh(refresh_id, outcome=req.outcome, changes=req.changes)
        return result.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


# ---------------------------------------------------------------------------
# Learning Signal endpoints
# ---------------------------------------------------------------------------


@router.post("/learning/signals")
def record_learning_signal(req: RecordLearningSignalRequest, request: Request) -> dict[str, Any]:
    """Record a continuous-learning signal."""
    _ensure_learning_enabled()
    try:
        signal_type = req.signal_type or req.type
        if signal_type is None:
            raise ValueError("signal_type is required")
        signal = LearningSignal(
            signal_type=LearningSignalType(signal_type),
            severity=LearningSignalSeverity(req.severity),
            tenant_id=_resolve_tenant_id(request, req.tenant_id, default="default"),
            summary=req.summary,
            details=req.details,
            source=req.source,
            context=req.context,
        )
        return _service.record_learning_signal(signal).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/learning/signals")
def list_learning_signals(
    request: Request,
    signal_type: str | None = None,
    signal_type_alias: str | None = Query(default=None, alias="type"),
    severity: str | None = None,
    tenant_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List learning signals with optional filters."""
    _ensure_learning_enabled()
    parsed_type = None
    raw_type = signal_type or signal_type_alias
    if raw_type is not None:
        try:
            parsed_type = LearningSignalType(raw_type)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Invalid signal_type: {raw_type}"
            ) from None
    parsed_severity = None
    if severity is not None:
        try:
            parsed_severity = LearningSignalSeverity(severity)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid severity: {severity}") from None
    resolved_tenant_id = _resolve_tenant_id(request, tenant_id)

    return [
        signal.model_dump(mode="json")
        for signal in _service.list_learning_signals(
            signal_type=parsed_type,
            severity=parsed_severity,
            tenant_id=resolved_tenant_id,
            limit=limit,
        )
    ]


@router.get("/learning/summary")
def get_learning_summary(
    request: Request,
    limit: int | None = None,
    generate_intakes: bool = False,
    tenant_id: str | None = None,
    window_days: int | None = None,
) -> dict[str, Any]:
    """Get learning summary and optionally generate intake records."""
    _ensure_learning_enabled()
    effective_limit = (
        settings.improvement_learning_summary_default_limit if limit is None else limit
    )
    resolved_tenant_id = _resolve_tenant_id(request, tenant_id)
    summary = _service.summarize_learning_signals(
        limit=effective_limit,
        tenant_id=resolved_tenant_id,
        window_days=window_days,
    )

    generated_intakes = []
    if generate_intakes and settings.improvement_learning_auto_intake_enabled:
        generated_intakes = _service.generate_intakes_from_learning_signals(
            tenant_id=resolved_tenant_id,
        )

    return {
        "summary": summary.model_dump(mode="json"),
        "generated_intakes": [i.model_dump(mode="json") for i in generated_intakes],
    }


@router.get("/learning/trends")
def get_learning_trends(
    request: Request,
    window_days: int = 7,
    dimension: str = LearningTrendDimension.SIGNAL_TYPE.value,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Get dedup-aware trend analytics over learning signals."""
    _ensure_learning_enabled()
    try:
        parsed_dimension = LearningTrendDimension(dimension)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid dimension: {dimension}") from None
    try:
        report = _service.trend_learning_signals(
            window_days=window_days,
            dimension=parsed_dimension,
            tenant_id=_resolve_tenant_id(request, tenant_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return report.model_dump(mode="json")


@router.get("/learning/calibration")
def get_learning_calibration(
    request: Request,
    window_days: int = 30,
    target_auto_intakes_per_window: int | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Calibrate retention and auto-intake thresholds from recent learning signals."""
    _ensure_learning_enabled()
    effective_target = (
        _service.persistence_policy.auto_intake_max_items
        if target_auto_intakes_per_window is None
        else target_auto_intakes_per_window
    )
    try:
        report = _service.calibrate_learning_thresholds(
            window_days=window_days,
            target_auto_intakes_per_window=effective_target,
            tenant_id=_resolve_tenant_id(request, tenant_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return report.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Learning State Backup / Restore (operator) endpoints
# ---------------------------------------------------------------------------


@router.post("/learning/backup", dependencies=[require_scope("admin")])
def backup_learning_state_endpoint(req: BackupLearningStateRequest) -> dict[str, Any]:
    """Create a portable JSON backup of current learning state."""
    backup_dest = (
        req.backup_path or settings.improvement_learning_persistence_migration_backup_path
    )
    try:
        result_path = backup_learning_state(_service._learning_store, backup_dest)
        state = _service._learning_store.load()
        return {
            "status": "ok",
            "backup_path": str(result_path),
            "signal_count": len(state.signals),
            "intake_count": len(state.generated_intakes),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None


@router.post("/learning/restore", dependencies=[require_scope("admin")])
def restore_learning_state_endpoint(req: RestoreLearningStateRequest) -> dict[str, Any]:
    """Restore learning state from a portable JSON backup."""
    if not Path(req.backup_path).exists():
        raise HTTPException(status_code=404, detail=f"Backup file not found: {req.backup_path}")
    try:
        state = restore_learning_state(_service._learning_store, req.backup_path)
        _reset_service()
        return {
            "status": "ok",
            "backup_path": req.backup_path,
            "signal_count": len(state.signals),
            "intake_count": len(state.generated_intakes),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


# ---------------------------------------------------------------------------
# Analytics Dashboard endpoints
# ---------------------------------------------------------------------------


@router.get("/analytics/dashboard")
def analytics_dashboard(
    request: Request,
    tenant_id: str | None = None,
    periods: int = 8,
    bucket_size: float = Query(default=0.1, ge=0.01, le=0.5),
) -> dict[str, Any]:
    """Return the composite analytics dashboard summary."""
    _ensure_learning_enabled()
    resolved = _resolve_tenant_id(request, tenant_id)
    svc = get_analytics_service()
    return svc.dashboard_summary(
        tenant_id=resolved, periods=periods, bucket_size=bucket_size
    ).model_dump(mode="json")


@router.get("/analytics/intake-funnel")
def analytics_intake_funnel(
    request: Request,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Return intake funnel breakdown."""
    resolved = _resolve_tenant_id(request, tenant_id)
    svc = get_analytics_service()
    return svc.intake_funnel(tenant_id=resolved).model_dump(mode="json")


@router.get("/analytics/lesson-actions")
def analytics_lesson_actions() -> dict[str, Any]:
    """Return lesson action completion report."""
    svc = get_analytics_service()
    return svc.lesson_action_completion().model_dump(mode="json")


@router.get("/analytics/checklist-completion")
def analytics_checklist_completion(
    period: str | None = None,
) -> dict[str, Any]:
    """Return checklist completion report."""
    svc = get_analytics_service()
    try:
        return svc.checklist_completion(period=period).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/analytics/signal-intake-conversion")
def analytics_signal_intake_conversion(
    request: Request,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Return signal-to-intake conversion report."""
    _ensure_learning_enabled()
    resolved = _resolve_tenant_id(request, tenant_id)
    svc = get_analytics_service()
    return svc.signal_to_intake_conversion(tenant_id=resolved).model_dump(mode="json")


@router.get("/analytics/quality-distribution")
def analytics_quality_distribution(
    request: Request,
    tenant_id: str | None = None,
    bucket_size: float = Query(default=0.1, ge=0.01, le=0.5),
) -> dict[str, Any]:
    """Return quality score distribution histogram."""
    _ensure_learning_enabled()
    resolved = _resolve_tenant_id(request, tenant_id)
    svc = get_analytics_service()
    return svc.quality_distribution(tenant_id=resolved, bucket_size=bucket_size).model_dump(
        mode="json"
    )


@router.get("/analytics/metrics-timeseries")
def analytics_metrics_timeseries(
    metric_id: str | None = None,
    periods: int = 8,
) -> list[dict[str, Any]]:
    """Return metrics time series data."""
    svc = get_analytics_service()
    series = svc.metrics_time_series(metric_id=metric_id, periods=periods)
    return [s.model_dump(mode="json") for s in series]


@router.get("/analytics/refresh-cadence")
def analytics_refresh_cadence() -> dict[str, Any]:
    """Return roadmap refresh cadence report."""
    svc = get_analytics_service()
    return svc.refresh_cadence().model_dump(mode="json")


# ---------------------------------------------------------------------------
# Tuning Loop endpoints
# ---------------------------------------------------------------------------


@router.get("/tuning/status")
def tuning_status() -> dict[str, Any]:
    """Return current tuning loop status."""
    svc = get_tuning_service()
    return svc.get_status()


@router.post("/tuning/run")
def tuning_run(dry_run: bool | None = None) -> dict[str, Any]:
    """Manually trigger a tuning cycle."""
    _ensure_learning_enabled()
    svc = get_tuning_service()
    record = svc.run_cycle(dry_run=dry_run)
    return record.model_dump(mode="json")


@router.post("/tuning/proposal-sandbox/run")
def tuning_proposal_sandbox_run() -> dict[str, Any]:
    """Generate a self-improvement tuning proposal without production mutation."""
    _ensure_learning_enabled()
    if not settings.self_improve_proposal_sandbox_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    svc = get_tuning_service()
    record = svc.run_proposal_sandbox()
    return record.model_dump(mode="json")


@router.get("/tuning/history")
def tuning_history(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent tuning cycle records."""
    svc = get_tuning_service()
    return [r.model_dump(mode="json") for r in svc.get_history(limit=limit)]


@router.post("/tuning/approve/{cycle_id}")
def tuning_approve(cycle_id: str, approved_by: str = "operator") -> dict[str, Any]:
    """Approve a pending tuning cycle and apply its changes."""
    _ensure_learning_enabled()
    svc = get_tuning_service()
    try:
        record = svc.approve_cycle(cycle_id, approved_by=approved_by)
        return record.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


# ---------------------------------------------------------------------------
# Self-evolution proposal endpoints (Gate 3.1 fix)
# Maps the frontend self-evolution domain to real TuningCycleRecord data.
# ---------------------------------------------------------------------------


@router.get("/proposals", dependencies=[require_scope("agents:read")])
def list_proposals(limit: int = 20, status: str | None = None) -> dict[str, Any]:
    """List self-improvement proposals from the tuning loop.

    Returns real ``TuningCycleRecord`` entries from the in-process tuning loop
    history.  The ``status`` parameter filters by ``TuningCycleOutcome`` value
    (e.g. ``pending_approval``, ``applied``, ``proposal_only``).
    """
    svc = get_tuning_service()
    history = svc.get_history(limit=limit)
    proposals = []
    for record in history:
        rec_status = record.outcome.value
        if status is not None and rec_status != status:
            continue
        proposals.append(
            {
                "id": record.cycle_id,
                "status": rec_status,
                "proposal_type": "config-calibration",
                "summary": record.rationale,
                "created_at": record.started_at.isoformat(),
                "completed_at": record.completed_at.isoformat(),
                "approved_at": record.approved_at.isoformat() if record.approved_at else None,
                "approved_by": record.approved_by,
                "sample_size": record.sample_size,
                "before_values": record.before_values,
                "after_values": record.after_values,
                "deltas": record.deltas,
            }
        )
    return {"proposals": proposals, "count": len(proposals), "type": "tuning-calibration"}


@router.post("/proposals/generate", dependencies=[require_scope("agents:write")])
def generate_proposal() -> dict[str, Any]:
    """Generate a self-improvement proposal via the tuning loop sandbox.

    Runs ``run_proposal_sandbox()`` which computes calibration deltas without
    mutating production state.  Requires ``self_improve_proposal_sandbox_enabled``
    to be set; returns 404 when the feature is disabled.
    """
    _ensure_learning_enabled()
    if not settings.self_improve_proposal_sandbox_enabled:
        raise HTTPException(status_code=404, detail="Proposal sandbox not enabled")
    svc = get_tuning_service()
    record = svc.run_proposal_sandbox()
    return record.model_dump(mode="json")
