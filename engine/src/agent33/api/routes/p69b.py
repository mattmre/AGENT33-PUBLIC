"""P69b: Human-in-the-loop tool approval — REST API endpoints.

Provides 4 endpoints per the P69b API contract:
  POST /v1/invocations/{invocation_id}/pause
  POST /v1/invocations/{invocation_id}/resume
  GET  /v1/invocations/{invocation_id}/pending-approvals
  GET  /v1/approvals/pending
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 -- Pydantic models need runtime type
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from agent33.autonomy.p69b_models import (
    ToolApprovalDenied,
    ToolApprovalFeatureDisabled,
    ToolApprovalInvalidState,
    ToolApprovalNonceReplay,
    ToolApprovalTimeout,
)
from agent33.autonomy.p69b_service import P69bService  # noqa: TC001
from agent33.security.permissions import require_scope

router = APIRouter(tags=["p69b-tool-approvals"])

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class PauseRequest(BaseModel):
    """Request body for POST /v1/invocations/{invocation_id}/pause."""

    tool_name: str
    tool_input: dict[str, Any] = Field(default_factory=dict)
    nonce: str


class PauseResponse(BaseModel):
    """Response body for a successful pause operation."""

    approval_id: str
    status: str = "PENDING"
    expires_at: datetime
    nonce: str


class ResumeRequest(BaseModel):
    """Request body for POST /v1/invocations/{invocation_id}/resume."""

    approved: bool
    nonce: str
    reason: str = ""


class ResumeResponse(BaseModel):
    """Response body for a successful resume operation."""

    invocation_id: str
    status: str  # "RUNNING" or "FAILED"
    resumed_at: datetime


class PendingApprovalItem(BaseModel):
    """Single pending approval (invocation-scoped view — no invocation_id field)."""

    approval_id: str
    tool_name: str
    tool_input: dict[str, Any]
    status: str
    created_at: datetime
    expires_at: datetime


class PendingApprovalItemWithInvocation(BaseModel):
    """Single pending approval (global view — includes invocation_id)."""

    approval_id: str
    invocation_id: str
    tool_name: str
    tool_input: dict[str, Any]
    status: str
    created_at: datetime
    expires_at: datetime


class PendingApprovalsResponse(BaseModel):
    """Response body for GET /v1/invocations/{invocation_id}/pending-approvals."""

    approvals: list[PendingApprovalItem]


class GlobalPendingApprovalsResponse(BaseModel):
    """Response body for GET /v1/approvals/pending."""

    approvals: list[PendingApprovalItemWithInvocation]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ERR_FEATURE_DISABLED = {
    "error": "ToolApprovalFeatureDisabled",
    "detail": (
        "The tool approval feature (p69b_tool_approval_enabled) is currently disabled. "
        "Tool calls are proceeding without approval checks. "
        "Check the feature flag configuration or remove the kill switch file."
    ),
}


def _get_service(request: Request) -> P69bService:
    """Return the P69bService from app.state, or 503 if not initialised."""
    svc: P69bService | None = getattr(request.app.state, "p69b_service", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="P69b service not initialized",
        )
    return svc


def _check_enabled(svc: P69bService) -> None:
    """Raise HTTP 503 if the P69b feature is disabled."""
    if not svc.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_ERR_FEATURE_DISABLED,
        )


def _approved_by(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        return ""
    return getattr(user, "sub", "") or ""


def _tenant_id(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        return ""
    return getattr(user, "tenant_id", "") or ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/v1/invocations/{invocation_id}/pause",
    response_model=PauseResponse,
    dependencies=[require_scope("invocations:write")],
)
async def pause_invocation(
    invocation_id: str,
    body: PauseRequest,
    request: Request,
) -> PauseResponse:
    """Pause an invocation at a tool call and register a pending approval."""
    svc = _get_service(request)
    _check_enabled(svc)
    try:
        record = svc.pause(
            invocation_id=invocation_id,
            tenant_id=_tenant_id(request),
            tool_name=body.tool_name,
            tool_input=body.tool_input,
            nonce=body.nonce,
        )
    except ToolApprovalNonceReplay as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "ToolApprovalNonceReplay", "detail": str(exc)},
        ) from exc
    except ToolApprovalInvalidState as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "ToolApprovalInvalidState", "detail": str(exc)},
        ) from exc
    except ToolApprovalTimeout as exc:
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail={"error": "ToolApprovalTimeout", "detail": str(exc)},
        ) from exc
    except ToolApprovalFeatureDisabled as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "ToolApprovalFeatureDisabled", "detail": str(exc)},
        ) from exc
    return PauseResponse(
        approval_id=record.id,
        status="PENDING",
        expires_at=record.expires_at,
        nonce=record.nonce,
    )


@router.post(
    "/v1/invocations/{invocation_id}/resume",
    response_model=ResumeResponse,
    dependencies=[require_scope("invocations:write")],
)
async def resume_invocation(
    invocation_id: str,
    body: ResumeRequest,
    request: Request,
) -> ResumeResponse:
    """Submit an operator approval/denial decision for a paused invocation."""
    svc = _get_service(request)
    _check_enabled(svc)

    # Locate the pending approval record for this invocation
    pending = svc.get_pending(invocation_id)
    if not pending:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "ToolApprovalInvalidState",
                "detail": (
                    f"Invocation {invocation_id} is not in PAUSED_FOR_APPROVAL state. "
                    "It may have timed out or been resolved by another operator."
                ),
            },
        )

    # Validate nonce against stored record
    record = pending[0]
    if record.nonce != body.nonce:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ToolApprovalNonceReplay",
                "detail": (
                    "The submitted nonce does not match the stored nonce. "
                    "Possible causes: replay attack, duplicate submission, "
                    "or 30-second window boundary crossed between pause and resume."
                ),
            },
        )

    try:
        updated = svc.resume(
            record.id,
            approved=body.approved,
            approved_by=_approved_by(request),
        )
    except ToolApprovalInvalidState as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "ToolApprovalInvalidState", "detail": str(exc)},
        ) from exc
    except ToolApprovalTimeout as exc:
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail={"error": "ToolApprovalTimeout", "detail": str(exc)},
        ) from exc
    except ToolApprovalDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "ToolApprovalDenied", "detail": str(exc)},
        ) from exc

    invocation_status = "RUNNING" if body.approved else "FAILED"
    resolved_at = updated.resolved_at if updated.resolved_at is not None else updated.created_at
    return ResumeResponse(
        invocation_id=invocation_id,
        status=invocation_status,
        resumed_at=resolved_at,
    )


@router.get(
    "/v1/invocations/{invocation_id}/pending-approvals",
    response_model=PendingApprovalsResponse,
    dependencies=[require_scope("invocations:read")],
)
async def list_pending_approvals(
    invocation_id: str,
    request: Request,
) -> PendingApprovalsResponse:
    """List all pending tool approval requests for a specific invocation."""
    svc = _get_service(request)
    _check_enabled(svc)

    records = svc.get_pending(invocation_id)
    approvals = [
        PendingApprovalItem(
            approval_id=r.id,
            tool_name=r.tool_name,
            tool_input=r.tool_input,
            status=r.status.value.upper(),
            created_at=r.created_at,
            expires_at=r.expires_at,
        )
        for r in records
    ]
    return PendingApprovalsResponse(approvals=approvals)


@router.get(
    "/v1/approvals/pending",
    response_model=GlobalPendingApprovalsResponse,
    dependencies=[require_scope("invocations:read")],
)
async def list_all_pending_approvals(
    request: Request,
    page: int = 1,
    page_size: int = 20,
) -> GlobalPendingApprovalsResponse:
    """List all pending tool approval requests for the authenticated tenant."""
    svc = _get_service(request)
    _check_enabled(svc)

    tenant = _tenant_id(request)
    all_records = svc.get_all_pending(tenant)

    # Cap page_size at 100
    page_size = min(page_size, 100)
    page_size = max(page_size, 1)
    page = max(page, 1)

    total = len(all_records)
    start = (page - 1) * page_size
    end = start + page_size
    page_records = all_records[start:end]

    approvals = [
        PendingApprovalItemWithInvocation(
            approval_id=r.id,
            invocation_id=r.invocation_id,
            tool_name=r.tool_name,
            tool_input=r.tool_input,
            status=r.status.value.upper(),
            created_at=r.created_at,
            expires_at=r.expires_at,
        )
        for r in page_records
    ]
    return GlobalPendingApprovalsResponse(
        approvals=approvals,
        total=total,
        page=page,
        page_size=page_size,
    )
