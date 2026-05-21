"""FastAPI routes for the candidate asset ingestion lifecycle.

Provides REST endpoints:
- ``POST /v1/ingestion/candidates``                       — ingest a new candidate
- ``GET  /v1/ingestion/candidates/{id}``                  — get by ID
- ``GET  /v1/ingestion/candidates``                       — list (by status or tenant)
- ``POST /v1/ingestion/candidates/{id}/transition``       — apply a lifecycle transition
- ``GET  /v1/ingestion/candidates/{id}/journal``          — audit journal for asset
- ``GET  /v1/ingestion/candidates/{id}/history``          — asset detail plus timeline history
- ``POST /v1/ingestion/intake``                           — batch intake via pipeline
- ``GET  /v1/ingestion/intake/stats``                     — pipeline stats for tenant
- ``POST /v1/ingestion/mailbox``                          — post an operator event
- ``GET  /v1/ingestion/mailbox/drain``                    — drain inbox for tenant
- ``GET  /v1/ingestion/heartbeat``                        — unauthenticated liveness check
- ``GET  /v1/ingestion/metrics``                          — task metrics summary
- ``GET  /v1/ingestion/metrics/history``                  — recent task metrics
- ``GET  /v1/ingestion/journal``                          — tenant journal (default last 100)
- ``GET  /v1/ingestion/review-queue``                     — pending-review candidates
- ``POST /v1/ingestion/review-queue/{id}/approve``        — approve a candidate
- ``POST /v1/ingestion/review-queue/{id}/reject``         — reject a candidate
- ``GET  /v1/ingestion/notification-hooks``               — list tenant notification hooks
- ``POST /v1/ingestion/notification-hooks``               — create a notification hook
- ``PATCH /v1/ingestion/notification-hooks/{id}``         — update a notification hook
- ``GET  /v1/ingestion/doctor/report``                    — summary report (warn/critical only)
- ``GET  /v1/ingestion/doctor``                           — full tenant diagnostic report
- ``GET  /v1/ingestion/doctor/{asset_id}``                — single-asset diagnostic report

Auth: write endpoints require ``ingestion:write`` scope; read endpoints
require ``ingestion:read`` scope.  Heartbeat is public.

CLEAN-ROOM RESTRICTION
=======================
No code in this file may originate from the EvoMap/Evolver project.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agent33.ingestion.doctor import SkillsDoctor
from agent33.ingestion.intake import IntakePipeline
from agent33.ingestion.mailbox import IngestionMailbox
from agent33.ingestion.metrics import TaskMetricsCollector
from agent33.ingestion.models import CandidateStatus, ConfidenceLevel
from agent33.ingestion.notifications import (
    IngestionNotificationEvent,
    IngestionNotificationService,
    NotificationHookStore,
)
from agent33.ingestion.service import IngestionService
from agent33.ingestion.state_machine import CandidateTransitionError
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/ingestion", tags=["ingestion"])
logger = structlog.get_logger()

# Module-level fallbacks; replaced by lifespan via set_ingestion_service() /
# set_intake_pipeline() / set_ingestion_mailbox() / set_task_metrics() /
# set_skills_doctor().
_service = IngestionService()
_intake_pipeline = IntakePipeline(_service)
_ingestion_mailbox = IngestionMailbox(pipeline=_intake_pipeline)
_task_metrics = TaskMetricsCollector()
_skills_doctor = SkillsDoctor(service=_service)
_notification_service = IngestionNotificationService(NotificationHookStore(":memory:"))


def set_ingestion_service(service: IngestionService) -> None:
    """Swap the module-level ingestion service (called from lifespan)."""
    global _service
    _service = service


def set_intake_pipeline(pipeline: IntakePipeline) -> None:
    """Swap the module-level intake pipeline (called from lifespan)."""
    global _intake_pipeline
    _intake_pipeline = pipeline


def set_ingestion_mailbox(mailbox: IngestionMailbox) -> None:
    """Swap the module-level ingestion mailbox (called from lifespan)."""
    global _ingestion_mailbox
    _ingestion_mailbox = mailbox


def set_task_metrics(metrics: TaskMetricsCollector) -> None:
    """Swap the module-level task metrics collector (called from lifespan)."""
    global _task_metrics
    _task_metrics = metrics


def set_skills_doctor(doctor: SkillsDoctor) -> None:
    """Swap the module-level skills doctor (called from lifespan)."""
    global _skills_doctor
    _skills_doctor = doctor


def set_ingestion_notification_service(service: IngestionNotificationService) -> None:
    """Swap the module-level ingestion notification service (called from lifespan)."""
    global _notification_service
    _notification_service = service


def get_ingestion_service(request: Request) -> IngestionService:
    """Return the ingestion service from app.state, falling back to module-level."""
    svc: IngestionService | None = getattr(request.app.state, "ingestion_service", None)
    return svc if svc is not None else _service


def get_intake_pipeline(request: Request) -> IntakePipeline:
    """Return the intake pipeline from app.state, falling back to module-level."""
    pipeline: IntakePipeline | None = getattr(request.app.state, "intake_pipeline", None)
    return pipeline if pipeline is not None else _intake_pipeline


def get_ingestion_mailbox(request: Request) -> IngestionMailbox:
    """Return the ingestion mailbox from app.state, falling back to module-level."""
    mailbox: IngestionMailbox | None = getattr(request.app.state, "ingestion_mailbox", None)
    return mailbox if mailbox is not None else _ingestion_mailbox


def get_task_metrics(request: Request) -> TaskMetricsCollector:
    """Return the task metrics collector from app.state, falling back to module-level."""
    metrics: TaskMetricsCollector | None = getattr(request.app.state, "task_metrics", None)
    return metrics if metrics is not None else _task_metrics


def get_skills_doctor(request: Request) -> SkillsDoctor:
    """Return the skills doctor from app.state, falling back to module-level."""
    doctor: SkillsDoctor | None = getattr(request.app.state, "skills_doctor", None)
    return doctor if doctor is not None else _skills_doctor


def get_notification_service(request: Request) -> IngestionNotificationService:
    """Return the notification service from app.state, falling back to module-level."""
    service: IngestionNotificationService | None = getattr(
        request.app.state, "ingestion_notification_service", None
    )
    return service if service is not None else _notification_service


# ------------------------------------------------------------------
# Request / Response bodies
# ------------------------------------------------------------------


class IngestRequest(BaseModel):
    """Request body for creating a new candidate asset."""

    name: str = Field(..., min_length=1, max_length=128)
    asset_type: str = Field(..., min_length=1)
    source_uri: str | None = None
    tenant_id: str = Field(..., min_length=1)
    confidence: ConfidenceLevel = ConfidenceLevel.LOW
    metadata: dict[str, Any] = Field(default_factory=dict)


class TransitionRequest(BaseModel):
    """Request body for applying a lifecycle transition."""

    target_status: CandidateStatus
    operator: str | None = None
    reason: str | None = None


class IntakeRequest(BaseModel):
    """Request body for the batch intake endpoint."""

    assets: list[dict[str, Any]] = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    tenant_id: str = Field(..., min_length=1)


class MailboxPostRequest(BaseModel):
    """Request body for posting an event to the ingestion mailbox."""

    event_type: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    sender: str = Field(..., min_length=1)


class ReviewActionRequest(BaseModel):
    """Request body for approve/reject review-queue actions."""

    operator: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class NotificationHookRequest(BaseModel):
    """Request body for creating a notification hook."""

    name: str = Field(..., min_length=1, max_length=128)
    target_url: str = Field(..., min_length=1)
    event_types: list[IngestionNotificationEvent] = Field(..., min_length=1)
    signing_secret: str | None = None
    enabled: bool = True


class NotificationHookUpdateRequest(BaseModel):
    """Request body for updating a notification hook."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    target_url: str | None = Field(default=None, min_length=1)
    event_types: list[IngestionNotificationEvent] | None = None
    signing_secret: str | None = None
    enabled: bool | None = None


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.post(
    "/candidates",
    status_code=201,
    dependencies=[require_scope("ingestion:write")],
)
async def ingest_candidate(body: IngestRequest, request: Request) -> dict[str, Any]:
    """Create a new candidate asset in ``CANDIDATE`` status."""
    svc = get_ingestion_service(request)
    asset = svc.ingest(
        name=body.name,
        asset_type=body.asset_type,
        source_uri=body.source_uri,
        tenant_id=body.tenant_id,
        confidence=body.confidence,
        metadata=body.metadata,
    )
    return asset.model_dump(mode="json")


@router.get(
    "/candidates/{asset_id}",
    dependencies=[require_scope("ingestion:read")],
)
async def get_candidate(asset_id: str, request: Request) -> dict[str, Any]:
    """Retrieve a candidate asset by ID."""
    svc = get_ingestion_service(request)
    asset = svc.get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Candidate asset {asset_id!r} not found.")
    return asset.model_dump(mode="json")


@router.get(
    "/candidates",
    dependencies=[require_scope("ingestion:read")],
)
async def list_candidates(
    request: Request,
    status: CandidateStatus | None = None,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    """List candidate assets, optionally filtered by status or tenant."""
    svc = get_ingestion_service(request)
    if status is not None:
        assets = svc.list_by_status(status)
    elif tenant_id is not None:
        assets = svc.list_by_tenant(tenant_id)
    else:
        # Return all assets across all statuses
        assets = [a for status_val in CandidateStatus for a in svc.list_by_status(status_val)]
    return [a.model_dump(mode="json") for a in assets]


@router.post(
    "/candidates/{asset_id}/transition",
    dependencies=[require_scope("ingestion:write")],
)
async def transition_candidate(
    asset_id: str,
    body: TransitionRequest,
    request: Request,
) -> dict[str, Any]:
    """Apply a lifecycle transition to a candidate asset.

    Returns the updated asset on success.  Returns 404 if the asset is not
    found, and 422 if the requested transition is not permitted.
    """
    svc = get_ingestion_service(request)

    # Resolve the asset first so we can give a clean 404.
    asset = svc.get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Candidate asset {asset_id!r} not found.")

    target = body.target_status

    try:
        if target == CandidateStatus.VALIDATED:
            updated = svc.validate(asset_id, operator=body.operator)
        elif target == CandidateStatus.PUBLISHED:
            updated = svc.promote(asset_id, operator=body.operator)
        elif target == CandidateStatus.REVOKED:
            reason = body.reason or "No reason supplied."
            updated = svc.revoke(asset_id, reason=reason, operator=body.operator)
        else:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot transition to {target.value!r}: not a supported target status.",
            )
    except CandidateTransitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return updated.model_dump(mode="json")


@router.post(
    "/intake",
    status_code=201,
    dependencies=[require_scope("ingestion:write")],
)
async def batch_intake(body: IntakeRequest, request: Request) -> dict[str, Any]:
    """Submit a batch of assets through the intake pipeline.

    Each asset is routed by confidence level:
    - HIGH → auto-advanced to VALIDATED
    - MEDIUM → stays CANDIDATE with ``review_required=True`` in metadata
    - LOW → stays CANDIDATE with ``review_required=True`` and ``quarantine=True``

    Individual failures do not abort the batch; errors are captured in the
    asset's ``metadata.intake_error`` field.

    Returns a dict with ``assets`` (list of created asset dicts) and ``stats``
    (counts by status for the given tenant).
    """
    pipeline = get_intake_pipeline(request)
    created = pipeline.batch_submit(body.assets, source=body.source, tenant_id=body.tenant_id)
    stats = pipeline.get_pipeline_stats(body.tenant_id)
    return {
        "assets": [a.model_dump(mode="json") for a in created],
        "stats": stats,
    }


@router.get(
    "/intake/stats",
    dependencies=[require_scope("ingestion:read")],
)
async def intake_stats(request: Request, tenant_id: str) -> dict[str, Any]:
    """Return per-status asset counts for the given tenant.

    Query parameter:
    - ``tenant_id``: The tenant scope to aggregate counts for.
    """
    pipeline = get_intake_pipeline(request)
    return pipeline.get_pipeline_stats(tenant_id)


@router.post(
    "/mailbox",
    status_code=202,
    dependencies=[require_scope("ingestion:write")],
)
async def post_mailbox_event(body: MailboxPostRequest, request: Request) -> dict[str, str]:
    """Deposit an operator event into the ingestion mailbox.

    ``candidate_asset`` events are forwarded immediately to the intake pipeline.
    All other event types are durably queued in the mailbox inbox until drained.

    Returns ``{"status": "accepted", "event_id": "<uuid4>"}`` on success.
    Returns 422 if the event fails validation.
    """
    mailbox = get_ingestion_mailbox(request)
    metrics = get_task_metrics(request)

    import time

    start = time.monotonic()
    try:
        result = mailbox.post(
            {"event_type": body.event_type, "payload": body.payload},
            sender=body.sender,
            tenant_id=_resolve_tenant_id(request),
        )
        latency_ms = (time.monotonic() - start) * 1000
        metrics.record(
            body.event_type,
            _resolve_tenant_id(request),
            success=True,
            latency_ms=latency_ms,
        )
    except ValueError as exc:
        metrics.record(body.event_type, _resolve_tenant_id(request), success=False)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return result


@router.get(
    "/mailbox/drain",
    dependencies=[require_scope("ingestion:read")],
)
async def drain_mailbox(request: Request) -> list[dict[str, Any]]:
    """Drain and return all queued inbox events for the authenticated tenant.

    Events that were routed to the intake pipeline are not returned here.
    """
    mailbox = get_ingestion_mailbox(request)
    return mailbox.drain(_resolve_tenant_id(request))


@router.get("/heartbeat")
async def heartbeat(request: Request) -> dict[str, Any]:
    """Return a combined liveness snapshot.  This endpoint is unauthenticated.

    Merges :meth:`IngestionMailbox.heartbeat` with
    :meth:`IntakePipeline.get_pipeline_stats` using the ``"system"`` tenant
    to provide a broad operational view.
    """
    mailbox = get_ingestion_mailbox(request)
    pipeline = get_intake_pipeline(request)
    hb = mailbox.heartbeat()
    pipeline_stats = pipeline.get_pipeline_stats("system")
    return {**hb, "pipeline_stats": pipeline_stats}


@router.get(
    "/metrics",
    dependencies=[require_scope("ingestion:read")],
)
async def task_metrics(request: Request) -> dict[str, Any]:
    """Return the task metrics summary for the authenticated tenant."""
    metrics = get_task_metrics(request)
    return metrics.summary(_resolve_tenant_id(request))


@router.get(
    "/metrics/history",
    dependencies=[require_scope("ingestion:read")],
)
async def task_metrics_history(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Return recent task metrics for the authenticated tenant."""
    metrics = get_task_metrics(request)
    return metrics.history(_resolve_tenant_id(request), limit=limit)


@router.get(
    "/candidates/{asset_id}/journal",
    dependencies=[require_scope("ingestion:read")],
)
async def get_asset_journal(asset_id: str, request: Request) -> list[dict[str, Any]]:
    """Return the audit journal entries for the given candidate asset.

    Entries are ordered ascending by ``occurred_at``.
    Returns 404 if the asset does not exist.
    """
    svc = get_ingestion_service(request)
    asset = svc.get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Candidate asset {asset_id!r} not found.")
    return svc.get_journal(asset_id)


@router.get(
    "/candidates/{asset_id}/history",
    dependencies=[require_scope("ingestion:read")],
)
async def get_asset_history(asset_id: str, request: Request) -> dict[str, Any]:
    """Return the current asset plus its timeline history."""
    svc = get_ingestion_service(request)
    asset = svc.get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Candidate asset {asset_id!r} not found.")
    return {
        "asset": asset.model_dump(mode="json"),
        "history": svc.get_journal(asset_id),
    }


@router.get(
    "/journal",
    dependencies=[require_scope("ingestion:read")],
)
async def get_tenant_journal(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Return recent journal entries for the authenticated tenant."""
    svc = get_ingestion_service(request)
    return svc.get_tenant_journal(_resolve_tenant_id(request), limit=limit)


@router.get(
    "/review-queue",
    dependencies=[require_scope("ingestion:read")],
)
async def list_review_queue(request: Request) -> list[dict[str, Any]]:
    """Return all CANDIDATE assets that require operator review for the authenticated tenant."""
    svc = get_ingestion_service(request)
    assets = svc.list_pending_review(_resolve_tenant_id(request))
    return [a.model_dump(mode="json") for a in assets]


@router.post(
    "/review-queue/{asset_id}/approve",
    dependencies=[require_scope("ingestion:write")],
)
async def approve_candidate(
    asset_id: str,
    body: ReviewActionRequest,
    request: Request,
) -> dict[str, Any]:
    """Approve a pending-review candidate: advance to VALIDATED and clear flags.

    Returns 404 if the asset does not exist.
    Returns 422 if the transition is not permitted.
    """
    svc = get_ingestion_service(request)
    asset = svc.get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Candidate asset {asset_id!r} not found.")
    try:
        updated = svc.approve(asset_id, operator=body.operator, reason=body.reason)
    except CandidateTransitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return updated.model_dump(mode="json")


@router.post(
    "/review-queue/{asset_id}/reject",
    dependencies=[require_scope("ingestion:write")],
)
async def reject_candidate(
    asset_id: str,
    body: ReviewActionRequest,
    request: Request,
) -> dict[str, Any]:
    """Reject a pending-review candidate: revoke it.

    Returns 404 if the asset does not exist.
    Returns 422 if the transition is not permitted.
    """
    svc = get_ingestion_service(request)
    asset = svc.get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Candidate asset {asset_id!r} not found.")
    try:
        updated = svc.reject(asset_id, operator=body.operator, reason=body.reason)
    except CandidateTransitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return updated.model_dump(mode="json")


@router.get(
    "/notification-hooks",
    dependencies=[require_scope("ingestion:read")],
)
async def list_notification_hooks(request: Request) -> list[dict[str, Any]]:
    """List configured notification hooks for the authenticated tenant."""
    service = get_notification_service(request)
    hooks = service.list_hooks(_resolve_tenant_id(request))
    return [hook.model_dump(mode="json") for hook in hooks]


@router.post(
    "/notification-hooks",
    status_code=201,
    dependencies=[require_scope("ingestion:write")],
)
async def create_notification_hook(
    body: NotificationHookRequest,
    request: Request,
) -> dict[str, Any]:
    """Create a webhook-style notification hook for operator-relevant events."""
    service = get_notification_service(request)
    hook = service.create_hook(
        tenant_id=_resolve_tenant_id(request),
        name=body.name,
        target_url=body.target_url,
        event_types=body.event_types,
        signing_secret=body.signing_secret,
        enabled=body.enabled,
    )
    return hook.model_dump(mode="json")


@router.patch(
    "/notification-hooks/{hook_id}",
    dependencies=[require_scope("ingestion:write")],
)
async def update_notification_hook(
    hook_id: str,
    body: NotificationHookUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    """Update an existing notification hook."""
    service = get_notification_service(request)
    tenant_id = _resolve_tenant_id(request)
    hook = service.update_hook(
        hook_id,
        tenant_id=tenant_id,
        name=body.name,
        target_url=body.target_url,
        event_types=body.event_types,
        signing_secret=body.signing_secret,
        replace_signing_secret="signing_secret" in body.model_fields_set,
        enabled=body.enabled,
    )
    if hook is None:
        raise HTTPException(status_code=404, detail=f"Notification hook {hook_id!r} not found.")
    return hook.model_dump(mode="json")


# ------------------------------------------------------------------
# Skills Doctor endpoints (detect-only)
# ------------------------------------------------------------------

# IMPORTANT: /doctor/report is registered before /doctor/{asset_id} so FastAPI
# resolves the literal path before the wildcard parameter.


@router.get(
    "/doctor/report",
    dependencies=[require_scope("ingestion:read")],
)
async def doctor_summary_report(request: Request) -> dict[str, Any]:
    """Return a summary diagnostic report for the authenticated tenant.

    Only warning and critical assets are included in the ``assets`` list.
    Healthy assets contribute to the counts but are omitted for brevity.
    """
    doctor = get_skills_doctor(request)
    return doctor.summary_report(_resolve_tenant_id(request))


@router.get(
    "/doctor",
    dependencies=[require_scope("ingestion:read")],
)
async def doctor_tenant_report(request: Request) -> dict[str, Any]:
    """Return a full diagnostic report for the authenticated tenant.

    Runs all health checks on every asset in the tenant and returns
    aggregate counts plus the full per-asset report list.
    """
    doctor = get_skills_doctor(request)
    return doctor.diagnose_tenant(_resolve_tenant_id(request))


@router.get(
    "/doctor/{asset_id}",
    dependencies=[require_scope("ingestion:read")],
)
async def doctor_asset_report(asset_id: str, request: Request) -> dict[str, Any]:
    """Return a diagnostic report for a single candidate asset.

    Runs all health checks and returns the combined result with
    ``status`` (``"healthy"`` | ``"warning"`` | ``"critical"``) and
    an ordered list of ``checks``.
    """
    doctor = get_skills_doctor(request)
    return doctor.diagnose_asset(asset_id, _resolve_tenant_id(request))


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _resolve_tenant_id(request: Request) -> str:
    """Extract tenant_id from the authenticated request state, or use 'unknown'."""
    user = getattr(request.state, "user", None)
    if user is None:
        return "unknown"
    return str(getattr(user, "tenant_id", None) or getattr(user, "sub", "unknown"))
