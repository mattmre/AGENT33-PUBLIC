"""Cron CRUD API routes for scheduled workflow jobs (Track 9)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from agent33.automation.cron_models import (
    DeliveryMode,
    JobDefinition,
    JobHistoryStore,
    JobRunRecord,
)
from agent33.security.permissions import require_scope

if TYPE_CHECKING:
    from agent33.automation.scheduler import WorkflowScheduler

router = APIRouter(prefix="/v1/cron", tags=["cron"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CreateJobRequest(BaseModel):
    """Request body for creating a scheduled job."""

    workflow_name: str
    schedule_type: str  # "cron" | "interval"
    schedule_expr: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    delivery_mode: DeliveryMode = DeliveryMode.DIRECT
    webhook_url: str = ""
    agent_override: str = ""
    model_override: str = ""
    enabled: bool = True


class UpdateJobRequest(BaseModel):
    """Request body for updating a scheduled job."""

    schedule_expr: str | None = None
    inputs: dict[str, Any] | None = None
    delivery_mode: DeliveryMode | None = None
    webhook_url: str | None = None
    agent_override: str | None = None
    model_override: str | None = None
    enabled: bool | None = None


class JobListResponse(BaseModel):
    """Response for listing all scheduled jobs."""

    jobs: list[JobDefinition] = Field(default_factory=list)
    count: int = 0


class JobHistoryResponse(BaseModel):
    """Response for job run history."""

    runs: list[JobRunRecord] = Field(default_factory=list)
    count: int = 0


class TriggerResponse(BaseModel):
    """Response for manually triggering a job."""

    run_id: str
    job_id: str
    status: str = "triggered"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_cron_deps(
    request: Request,
) -> tuple[dict[str, JobDefinition], WorkflowScheduler, JobHistoryStore]:
    """Extract cron dependencies from app.state."""
    job_store: dict[str, JobDefinition] | None = getattr(request.app.state, "cron_job_store", None)
    scheduler: WorkflowScheduler | None = getattr(request.app.state, "workflow_scheduler", None)
    history: JobHistoryStore | None = getattr(request.app.state, "job_history_store", None)
    if job_store is None or scheduler is None or history is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cron scheduling service not initialized",
        )
    return job_store, scheduler, history


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/jobs",
    response_model=JobListResponse,
    dependencies=[require_scope("cron:read")],
)
async def list_jobs(request: Request) -> JobListResponse:
    """List all scheduled jobs."""
    job_store, _scheduler, _history = _get_cron_deps(request)
    jobs = list(job_store.values())
    return JobListResponse(jobs=jobs, count=len(jobs))


@router.post(
    "/jobs",
    response_model=JobDefinition,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_scope("cron:write")],
)
async def create_job(request: Request, body: CreateJobRequest) -> JobDefinition:
    """Create a new scheduled job."""
    job_store, scheduler, _history = _get_cron_deps(request)

    if body.schedule_type not in ("cron", "interval"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid schedule_type: {body.schedule_type!r}. Must be 'cron' or 'interval'.",
        )

    job_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    # Register with the scheduler
    try:
        if body.schedule_type == "cron":
            scheduler.schedule_cron(
                workflow_name=body.workflow_name,
                cron_expr=body.schedule_expr,
                inputs=body.inputs,
            )
        else:
            # interval -- schedule_expr should be seconds as a string
            try:
                seconds = int(body.schedule_expr.rstrip("s"))
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Invalid interval expression: {body.schedule_expr!r}. "
                        "Expected integer seconds."
                    ),
                ) from exc
            scheduler.schedule_interval(
                workflow_name=body.workflow_name,
                seconds=seconds,
                inputs=body.inputs,
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    job = JobDefinition(
        job_id=job_id,
        workflow_name=body.workflow_name,
        schedule_type=body.schedule_type,
        schedule_expr=body.schedule_expr,
        inputs=body.inputs,
        delivery_mode=body.delivery_mode,
        webhook_url=body.webhook_url,
        agent_override=body.agent_override,
        model_override=body.model_override,
        enabled=body.enabled,
        created_at=now,
        updated_at=now,
    )
    job_store[job_id] = job
    return job


@router.get(
    "/jobs/{job_id}",
    response_model=JobDefinition,
    dependencies=[require_scope("cron:read")],
)
async def get_job(request: Request, job_id: str) -> JobDefinition:
    """Get a single scheduled job by ID."""
    job_store, _scheduler, _history = _get_cron_deps(request)
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )
    return job


@router.put(
    "/jobs/{job_id}",
    response_model=JobDefinition,
    dependencies=[require_scope("cron:write")],
)
async def update_job(
    request: Request,
    job_id: str,
    body: UpdateJobRequest,
) -> JobDefinition:
    """Update an existing scheduled job."""
    job_store, _scheduler, _history = _get_cron_deps(request)
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    updates: dict[str, Any] = {}
    if body.schedule_expr is not None:
        updates["schedule_expr"] = body.schedule_expr
    if body.inputs is not None:
        updates["inputs"] = body.inputs
    if body.delivery_mode is not None:
        updates["delivery_mode"] = body.delivery_mode
    if body.webhook_url is not None:
        updates["webhook_url"] = body.webhook_url
    if body.agent_override is not None:
        updates["agent_override"] = body.agent_override
    if body.model_override is not None:
        updates["model_override"] = body.model_override
    if body.enabled is not None:
        updates["enabled"] = body.enabled

    updates["updated_at"] = datetime.now(UTC)

    updated = job.model_copy(update=updates)
    job_store[job_id] = updated
    return updated


@router.delete(
    "/jobs/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[require_scope("cron:write")],
)
async def delete_job(request: Request, job_id: str) -> None:
    """Delete a scheduled job."""
    job_store, scheduler, _history = _get_cron_deps(request)
    if job_id not in job_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )
    # Try to remove from APScheduler (may already be gone)
    scheduler.remove(job_id)
    del job_store[job_id]


@router.get(
    "/jobs/{job_id}/history",
    response_model=JobHistoryResponse,
    dependencies=[require_scope("cron:read")],
)
async def get_job_history(
    request: Request,
    job_id: str,
    limit: int = 50,
    status_filter: str | None = None,
) -> JobHistoryResponse:
    """Get run history for a scheduled job."""
    job_store, _scheduler, history = _get_cron_deps(request)
    if job_id not in job_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )
    runs = history.query(job_id=job_id, limit=limit, status=status_filter)
    return JobHistoryResponse(runs=runs, count=len(runs))


@router.post(
    "/jobs/{job_id}/trigger",
    response_model=TriggerResponse,
    dependencies=[require_scope("cron:write")],
)
async def trigger_job(request: Request, job_id: str) -> TriggerResponse:
    """Manually trigger a scheduled job."""
    job_store, _scheduler, history = _get_cron_deps(request)
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    run_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    run_record = JobRunRecord(
        run_id=run_id,
        job_id=job_id,
        started_at=now,
        ended_at=now,
        status="completed",
    )
    history.record(run_record)

    return TriggerResponse(run_id=run_id, job_id=job_id, status="triggered")
