"""FastAPI router for scheduled evaluation gates."""

# NOTE: no ``from __future__ import annotations`` — Pydantic needs these
# types at runtime for request-body validation.

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agent33.evaluation.models import GateType
from agent33.evaluation.scheduled_gates import (
    ScheduledGateService,
    ScheduleType,
)
from agent33.security.permissions import require_scope

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/evaluations/schedules", tags=["scheduled-gates"])

# ---------------------------------------------------------------------------
# Service singleton (set from lifespan)
# ---------------------------------------------------------------------------

_service: ScheduledGateService | None = None


def set_service(service: ScheduledGateService | None) -> None:
    """Install the service instance (called from lifespan)."""
    global _service  # noqa: PLW0603
    _service = service


def get_service() -> ScheduledGateService:
    """Return the service or raise 503 if not initialized."""
    if _service is None:
        raise HTTPException(
            status_code=503,
            detail="Scheduled gate service not initialized",
        )
    return _service


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateScheduleRequest(BaseModel):
    gate_type: GateType = GateType.G_MON
    schedule_type: ScheduleType = ScheduleType.CRON
    cron_expr: str | None = None
    interval_seconds: int | None = None
    task_filter: list[str] | None = None
    auto_baseline: bool = False
    enabled: bool = True


class ScheduleResponse(BaseModel):
    schedule_id: str
    gate_type: str
    schedule_type: str
    cron_expr: str | None = None
    interval_seconds: int | None = None
    task_filter: list[str] | None = None
    auto_baseline: bool = False
    enabled: bool = True


class TriggerResponse(BaseModel):
    schedule_id: str
    run_id: str
    gate_result: str
    metrics: dict[str, float] = Field(default_factory=dict)
    regressions_found: int = 0
    executed_at: str = ""
    error: str | None = None


class HistoryItemResponse(BaseModel):
    schedule_id: str
    run_id: str
    gate_result: str
    metrics: dict[str, float] = Field(default_factory=dict)
    regressions_found: int = 0
    executed_at: str = ""
    error: str | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "",
    status_code=201,
    dependencies=[require_scope("tools:execute")],
)
async def create_schedule(body: CreateScheduleRequest) -> dict[str, Any]:
    """Create a new scheduled evaluation gate."""
    service = get_service()

    from agent33.evaluation.scheduled_gates import ScheduledGateConfig

    config = ScheduledGateConfig(
        gate_type=body.gate_type,
        schedule_type=body.schedule_type,
        cron_expr=body.cron_expr,
        interval_seconds=body.interval_seconds,
        task_filter=body.task_filter,
        auto_baseline=body.auto_baseline,
        enabled=body.enabled,
    )

    try:
        created = service.create_schedule(config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "schedule_id": created.schedule_id,
        "gate_type": created.gate_type.value,
        "schedule_type": created.schedule_type.value,
        "enabled": created.enabled,
    }


@router.get(
    "",
    dependencies=[require_scope("workflows:read")],
)
async def list_schedules() -> list[dict[str, Any]]:
    """List all scheduled evaluation gates."""
    service = get_service()
    schedules = service.list_schedules()
    return [
        {
            "schedule_id": s.schedule_id,
            "gate_type": s.gate_type.value,
            "schedule_type": s.schedule_type.value,
            "cron_expr": s.cron_expr,
            "interval_seconds": s.interval_seconds,
            "auto_baseline": s.auto_baseline,
            "enabled": s.enabled,
        }
        for s in schedules
    ]


@router.get(
    "/{schedule_id}",
    dependencies=[require_scope("workflows:read")],
)
async def get_schedule(schedule_id: str) -> dict[str, Any]:
    """Get schedule detail."""
    service = get_service()
    schedule = service.get_schedule(schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail=f"Schedule not found: {schedule_id}")
    return {
        "schedule_id": schedule.schedule_id,
        "gate_type": schedule.gate_type.value,
        "schedule_type": schedule.schedule_type.value,
        "cron_expr": schedule.cron_expr,
        "interval_seconds": schedule.interval_seconds,
        "task_filter": schedule.task_filter,
        "auto_baseline": schedule.auto_baseline,
        "enabled": schedule.enabled,
    }


@router.delete(
    "/{schedule_id}",
    status_code=204,
    response_model=None,
    dependencies=[require_scope("tools:execute")],
)
async def remove_schedule(schedule_id: str) -> None:
    """Remove a scheduled evaluation gate."""
    service = get_service()
    removed = service.remove_schedule(schedule_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Schedule not found: {schedule_id}")


@router.post(
    "/{schedule_id}/trigger",
    dependencies=[require_scope("tools:execute")],
)
async def trigger_schedule(schedule_id: str) -> dict[str, Any]:
    """Manually trigger a scheduled gate evaluation."""
    service = get_service()
    try:
        result = await service.trigger_now(schedule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "schedule_id": result.schedule_id,
        "run_id": result.run_id,
        "gate_result": result.gate_result.value,
        "metrics": result.metrics,
        "regressions_found": result.regressions_found,
        "executed_at": result.executed_at.isoformat(),
        "error": result.error,
    }


@router.get(
    "/{schedule_id}/history",
    dependencies=[require_scope("workflows:read")],
)
async def get_schedule_history(
    schedule_id: str,
    limit: int = Query(default=20, gt=0, le=100),
) -> list[dict[str, Any]]:
    """Get execution history for a scheduled gate."""
    service = get_service()

    # Verify schedule exists
    schedule = service.get_schedule(schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail=f"Schedule not found: {schedule_id}")

    results = service.get_history(schedule_id, limit=limit)
    return [
        {
            "schedule_id": r.schedule_id,
            "run_id": r.run_id,
            "gate_result": r.gate_result.value,
            "metrics": r.metrics,
            "regressions_found": r.regressions_found,
            "executed_at": r.executed_at.isoformat(),
            "error": r.error,
        }
        for r in results
    ]
