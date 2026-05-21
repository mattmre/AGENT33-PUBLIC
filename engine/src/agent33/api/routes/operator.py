"""Operator control plane API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from agent33.operator.models import (
    BackupListResponse,
    DiagnosticResult,
    OperatorConfig,
    ResetRequest,
    ResetResult,
    SessionListResponse,
    SystemStatus,
    ToolSummaryResponse,
)
from agent33.operator.onboarding import OnboardingService, OnboardingStatus
from agent33.operator.service import OperatorService
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/operator", tags=["operator"])


def get_operator_service(request: Request) -> OperatorService:
    """Extract the OperatorService from app.state."""
    svc: OperatorService | None = getattr(request.app.state, "operator_service", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operator service not initialized",
        )
    return svc


OperatorServiceDependency = Annotated[OperatorService, Depends(get_operator_service)]


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    response_model=SystemStatus,
    dependencies=[require_scope("operator:read")],
)
async def operator_status(
    svc: OperatorServiceDependency,
) -> SystemStatus:
    """Aggregated system health, subsystem inventories, and runtime info."""
    return await svc.get_status()


# ---------------------------------------------------------------------------
# Config (redacted)
# ---------------------------------------------------------------------------


@router.get(
    "/config",
    response_model=OperatorConfig,
    dependencies=[require_scope("operator:read")],
)
async def operator_config(
    svc: OperatorServiceDependency,
) -> OperatorConfig:
    """Effective runtime configuration with secrets redacted."""
    return svc.get_config()


# ---------------------------------------------------------------------------
# Doctor (diagnostics)
# ---------------------------------------------------------------------------


@router.get(
    "/doctor",
    response_model=DiagnosticResult,
    dependencies=[require_scope("operator:read")],
)
async def operator_doctor(
    svc: OperatorServiceDependency,
) -> DiagnosticResult:
    """Run diagnostic checks and return results with severity and remediation."""
    return await svc.run_doctor()


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


@router.post(
    "/reset",
    response_model=ResetResult,
    dependencies=[require_scope("operator:write")],
)
async def operator_reset(
    svc: OperatorServiceDependency,
    body: ResetRequest,
) -> ResetResult:
    """Reset specified operator state (clear caches, re-discover registries)."""
    return await svc.reset(body.targets)


# ---------------------------------------------------------------------------
# Tools summary
# ---------------------------------------------------------------------------


@router.get(
    "/tools/summary",
    response_model=ToolSummaryResponse,
    dependencies=[require_scope("operator:read")],
)
async def operator_tools_summary(
    svc: OperatorServiceDependency,
) -> ToolSummaryResponse:
    """Lightweight listing of registered tools."""
    return svc.get_tools_summary()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    dependencies=[require_scope("operator:read")],
)
async def operator_sessions(
    svc: OperatorServiceDependency,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> SessionListResponse:
    """Session catalog (lightweight, full management in Track Phase 8)."""
    return await svc.get_sessions(
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------


@router.get(
    "/backups",
    response_model=BackupListResponse,
    dependencies=[require_scope("operator:read")],
)
async def operator_backups(
    svc: OperatorServiceDependency,
) -> BackupListResponse:
    """Backup catalog delegated to the platform backup service when available."""
    return svc.get_backups()


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------


@router.get(
    "/onboarding",
    response_model=OnboardingStatus,
    dependencies=[require_scope("operator:read")],
)
async def operator_onboarding(request: Request) -> OnboardingStatus:
    """Onboarding checklist: evaluates deployment readiness steps."""
    onboarding_svc: OnboardingService | None = getattr(
        request.app.state, "onboarding_service", None
    )
    if onboarding_svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Onboarding service not initialized",
        )
    return onboarding_svc.check()
