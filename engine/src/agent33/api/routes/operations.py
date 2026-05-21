"""Operations API routes — /v1/ops/ endpoints.

Provides a unified operations surface for system doctor, config management,
cron controls, onboarding, and runtime info.
"""

from __future__ import annotations

import sys
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from agent33.ops.config_manager import ConfigField, ConfigManager, ConfigManagerResult
from agent33.ops.cron_manager import (
    CronJobEntry,
    CronJobHistoryEntry,
    CronManager,
    CronTriggerResult,
)
from agent33.ops.doctor import DoctorReport, SystemDoctor
from agent33.ops.onboarding import OnboardingChecklist, OnboardingChecklistService
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/ops", tags=["ops"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ConfigSchemaResponse(BaseModel):
    """Response for GET /v1/ops/config."""

    fields: list[ConfigField] = Field(default_factory=list)
    count: int = 0


class ConfigValidateRequest(BaseModel):
    """Request body for POST /v1/ops/config/validate."""

    changes: dict[str, Any] = Field(default_factory=dict)


class ConfigValidateResponse(BaseModel):
    """Response for POST /v1/ops/config/validate."""

    valid: bool = True
    errors: list[str] = Field(default_factory=list)


class ConfigApplyRequest(BaseModel):
    """Request body for POST /v1/ops/config/apply."""

    changes: dict[str, Any] = Field(default_factory=dict)


class CronJobListResponse(BaseModel):
    """Response for GET /v1/ops/cron."""

    jobs: list[CronJobEntry] = Field(default_factory=list)
    count: int = 0


class CronJobHistoryResponse(BaseModel):
    """Response for GET /v1/ops/cron/{id}/history."""

    runs: list[CronJobHistoryEntry] = Field(default_factory=list)
    count: int = 0


class CronJobPatchRequest(BaseModel):
    """Request body for PATCH /v1/ops/cron/{id}."""

    enabled: bool | None = None


class VersionInfoResponse(BaseModel):
    """Response for GET /v1/ops/version."""

    version: str = "0.1.0"
    python_version: str = ""
    platform: str = ""
    git_hash: str = ""
    uptime_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_doctor(request: Request) -> SystemDoctor:
    svc: SystemDoctor | None = getattr(request.app.state, "system_doctor", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="System doctor not initialized",
        )
    return svc


def _get_config_manager(request: Request) -> ConfigManager:
    svc: ConfigManager | None = getattr(request.app.state, "ops_config_manager", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Config manager not initialized",
        )
    return svc


def _get_cron_manager(request: Request) -> CronManager:
    svc: CronManager | None = getattr(request.app.state, "ops_cron_manager", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cron manager not initialized",
        )
    return svc


def _get_onboarding(request: Request) -> OnboardingChecklistService:
    svc: OnboardingChecklistService | None = getattr(request.app.state, "ops_onboarding", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Onboarding service not initialized",
        )
    return svc


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------


@router.get(
    "/doctor",
    response_model=DoctorReport,
    dependencies=[require_scope("operator:read")],
)
async def ops_doctor(request: Request) -> DoctorReport:
    """Run all system doctor checks and return the report."""
    doctor = _get_doctor(request)
    return await doctor.run_all()


@router.get(
    "/doctor/{check_name}",
    dependencies=[require_scope("operator:read")],
)
async def ops_doctor_single(request: Request, check_name: str) -> Any:
    """Run a single doctor check by name."""
    doctor = _get_doctor(request)
    result = await doctor.run_check(check_name)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Check '{check_name}' not found",
        )
    return result


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@router.get(
    "/config",
    response_model=ConfigSchemaResponse,
    dependencies=[require_scope("operator:read")],
)
async def ops_config_schema(request: Request) -> ConfigSchemaResponse:
    """Get config schema with current values (secrets redacted)."""
    mgr = _get_config_manager(request)
    fields = mgr.get_schema()
    return ConfigSchemaResponse(fields=fields, count=len(fields))


@router.post(
    "/config/validate",
    response_model=ConfigValidateResponse,
    dependencies=[require_scope("operator:read")],
)
async def ops_config_validate(
    request: Request, body: ConfigValidateRequest
) -> ConfigValidateResponse:
    """Validate proposed config changes without applying them."""
    mgr = _get_config_manager(request)
    errors = mgr.validate_changes(body.changes)
    return ConfigValidateResponse(valid=len(errors) == 0, errors=errors)


@router.post(
    "/config/apply",
    response_model=ConfigManagerResult,
    dependencies=[require_scope("admin")],
)
async def ops_config_apply(request: Request, body: ConfigApplyRequest) -> ConfigManagerResult:
    """Apply config changes (admin only). Returns diffs and restart flags."""
    mgr = _get_config_manager(request)
    return mgr.apply_changes(body.changes)


# ---------------------------------------------------------------------------
# Cron
# ---------------------------------------------------------------------------


@router.get(
    "/cron",
    response_model=CronJobListResponse,
    dependencies=[require_scope("cron:read")],
)
async def ops_cron_list(request: Request) -> CronJobListResponse:
    """List all scheduled cron jobs."""
    mgr = _get_cron_manager(request)
    jobs = mgr.list_jobs()
    return CronJobListResponse(jobs=jobs, count=len(jobs))


@router.get(
    "/cron/{job_id}",
    response_model=CronJobEntry,
    dependencies=[require_scope("cron:read")],
)
async def ops_cron_get(request: Request, job_id: str) -> CronJobEntry:
    """Get details for a single cron job."""
    mgr = _get_cron_manager(request)
    entry = mgr.get_job(job_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cron job '{job_id}' not found",
        )
    return entry


@router.post(
    "/cron/{job_id}/trigger",
    response_model=CronTriggerResult,
    dependencies=[require_scope("cron:write")],
)
async def ops_cron_trigger(request: Request, job_id: str) -> CronTriggerResult:
    """Manually trigger a cron job."""
    mgr = _get_cron_manager(request)
    result = mgr.trigger_job(job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cron job '{job_id}' not found",
        )
    return result


@router.patch(
    "/cron/{job_id}",
    response_model=CronJobEntry,
    dependencies=[require_scope("cron:write")],
)
async def ops_cron_patch(request: Request, job_id: str, body: CronJobPatchRequest) -> CronJobEntry:
    """Enable or disable a cron job."""
    mgr = _get_cron_manager(request)

    if body.enabled is not None:
        success = mgr.enable_job(job_id) if body.enabled else mgr.disable_job(job_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Cron job '{job_id}' not found",
            )

    entry = mgr.get_job(job_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cron job '{job_id}' not found",
        )
    return entry


@router.get(
    "/cron/{job_id}/history",
    response_model=CronJobHistoryResponse,
    dependencies=[require_scope("cron:read")],
)
async def ops_cron_history(
    request: Request, job_id: str, limit: int = 50
) -> CronJobHistoryResponse:
    """Get run history for a cron job."""
    mgr = _get_cron_manager(request)
    # Verify job exists
    if mgr.get_job(job_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cron job '{job_id}' not found",
        )
    runs = mgr.get_history(job_id, limit=limit)
    return CronJobHistoryResponse(runs=runs, count=len(runs))


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------


@router.get(
    "/onboarding",
    response_model=OnboardingChecklist,
    dependencies=[require_scope("operator:read")],
)
async def ops_onboarding(request: Request) -> OnboardingChecklist:
    """Get the onboarding checklist with auto-resolved step statuses."""
    svc = _get_onboarding(request)
    return svc.get_checklist()


# ---------------------------------------------------------------------------
# Version / runtime info
# ---------------------------------------------------------------------------


@router.get(
    "/version",
    response_model=VersionInfoResponse,
    dependencies=[require_scope("operator:read")],
)
async def ops_version(request: Request) -> VersionInfoResponse:
    """Get system version and runtime info."""
    version_info = getattr(request.app.state, "runtime_version_info", None)
    start_time: float | None = getattr(request.app.state, "start_time", None)
    uptime = time.time() - start_time if start_time is not None else 0.0

    return VersionInfoResponse(
        version=getattr(version_info, "version", "0.1.0") if version_info else "0.1.0",
        python_version=sys.version,
        platform=sys.platform,
        git_hash=(getattr(version_info, "git_short_hash", "") if version_info else ""),
        uptime_seconds=round(uptime, 2),
    )
