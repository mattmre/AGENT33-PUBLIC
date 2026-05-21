"""FastAPI router for HITL tool-approval lifecycle operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from agent33.config import settings
from agent33.security.approval_tokens import ApprovalTokenManager
from agent33.security.permissions import require_scope
from agent33.tools.approvals import ApprovalRiskTier, ApprovalStatus, ToolApprovalService

router = APIRouter(prefix="/v1/approvals/tools", tags=["tool-approvals"])

_service = ToolApprovalService()
_approval_token_manager: ApprovalTokenManager | None = None

_TOKEN_PRESETS: dict[str, tuple[int, bool]] = {
    "single_use": (300, True),
    "session_15m": (900, False),
    "session_1h": (3600, False),
    "workday": (28_800, False),
}


def set_tool_approval_service(service: ToolApprovalService) -> None:
    """Inject a shared approval service instance (called from lifespan)."""
    global _service  # noqa: PLW0603
    _service = service


def set_approval_token_manager(manager: ApprovalTokenManager | None) -> None:
    """Inject the shared approval-token manager."""
    global _approval_token_manager  # noqa: PLW0603
    _approval_token_manager = manager


def get_tool_approval_service() -> ToolApprovalService:
    """Return singleton approval service."""
    return _service


def get_approval_token_manager() -> ApprovalTokenManager | None:
    """Return the shared approval-token manager if enabled."""
    return _approval_token_manager


def _reset_tool_approval_service() -> None:
    """Reset singleton approval service for tests."""
    global _service  # noqa: PLW0603
    _service = ToolApprovalService()


def _get_token_payload(request: Request) -> Any:
    """Extract token payload previously set by auth middleware."""
    payload = getattr(request.state, "user", None)
    if payload is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return payload


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"] = "approve"
    review_note: str = ""


class TokenRequest(BaseModel):
    token_preset: Literal["single_use", "session_15m", "session_1h", "workday"] | None = None
    ttl_seconds: int | None = Field(default=None, ge=60, le=86_400)
    one_time: bool | None = None


class BatchDecisionRequest(TokenRequest):
    approval_ids: list[str] = Field(min_length=1, max_length=100)
    decision: Literal["approve", "reject"] = "approve"
    review_note: str = ""
    issue_tokens: bool = False


def _resolve_token_settings(body: TokenRequest) -> tuple[int | None, bool | None]:
    ttl_seconds = body.ttl_seconds
    one_time = body.one_time
    if body.token_preset is not None:
        preset_ttl, preset_one_time = _TOKEN_PRESETS[body.token_preset]
        if ttl_seconds is None:
            ttl_seconds = preset_ttl
        if one_time is None:
            one_time = preset_one_time
    return ttl_seconds, one_time


def _batch_safety_summary(records: list[Any], body: BatchDecisionRequest) -> dict[str, Any]:
    ttl_seconds, one_time = _resolve_token_settings(body)
    risk_order = {
        ApprovalRiskTier.LOW: 0,
        ApprovalRiskTier.MEDIUM: 1,
        ApprovalRiskTier.HIGH: 2,
    }
    max_risk = max(
        (record.risk_tier for record in records),
        key=lambda risk: risk_order[risk],
        default=ApprovalRiskTier.LOW,
    )
    expires_at = None
    if body.issue_tokens and ttl_seconds is not None:
        expires_at = (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat()
    return {
        "affected_tools": sorted({record.tool_name for record in records}),
        "affected_operations": sorted({record.operation for record in records}),
        "max_risk_tier": max_risk.value,
        "approval_count": len(records),
        "issue_tokens": body.issue_tokens,
        "token_ttl_seconds": ttl_seconds if body.issue_tokens else None,
        "one_time": one_time if body.issue_tokens else None,
        "expires_at": expires_at,
        "rollback": "tokens can be revoked by approval id before expiry",
    }


def _resolve_approval_token_manager(request: Request | None = None) -> ApprovalTokenManager | None:
    """Resolve a shared approval-token manager from module state or app state."""
    manager = get_approval_token_manager()
    if manager is None and request is not None:
        manager = getattr(request.app.state, "approval_token_manager", None)
        if isinstance(manager, ApprovalTokenManager):
            set_approval_token_manager(manager)
    if manager is None and settings.approval_token_enabled:
        manager = ApprovalTokenManager(
            secret=settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_algorithm,
            default_ttl_seconds=settings.approval_token_ttl_seconds,
            default_one_time=settings.approval_token_one_time_default,
        )
        set_approval_token_manager(manager)
    return manager


def _issue_token_response(record: Any, body: TokenRequest, request: Request) -> dict[str, Any]:
    manager = _resolve_approval_token_manager(request)
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Approval tokens are not enabled",
        )
    ttl_seconds, one_time = _resolve_token_settings(body)
    token = manager.issue(
        record,
        arguments=dict(record.arguments),
        ttl_seconds=ttl_seconds,
        one_time=one_time,
    )
    return {
        "approval_token": token,
        "ttl_seconds": ttl_seconds,
        "one_time": manager._default_one_time if one_time is None else one_time,
    }


@router.get("", dependencies=[require_scope("workflows:read")])
async def list_tool_approvals(
    request: Request,
    status: str | None = None,
    requested_by: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    token_payload = _get_token_payload(request)
    tenant_id = token_payload.tenant_id or ""
    status_filter: ApprovalStatus | None = None
    if status is not None:
        try:
            status_filter = ApprovalStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid status value: {status}") from exc
    records = _service.list_requests(
        status=status_filter,
        requested_by=requested_by,
        tenant_id=tenant_id,
        limit=limit,
    )
    return [record.model_dump(mode="json") for record in records]


@router.get("/{approval_id}", dependencies=[require_scope("workflows:read")])
async def get_tool_approval(request: Request, approval_id: str) -> dict[str, Any]:
    token_payload = _get_token_payload(request)
    tenant_id = token_payload.tenant_id or ""
    record = _service.get_request(approval_id)
    if record is None or (tenant_id and record.tenant_id != tenant_id):
        raise HTTPException(status_code=404, detail=f"Approval request not found: {approval_id}")
    return record.model_dump(mode="json")


@router.post("/{approval_id}/decision", dependencies=[require_scope("tools:execute")])
async def decide_tool_approval(
    request: Request, approval_id: str, body: DecisionRequest
) -> dict[str, Any]:
    token_payload = _get_token_payload(request)
    tenant_id = token_payload.tenant_id or ""
    reviewed_by = token_payload.sub or ""
    record = _service.get_request(approval_id)
    if record is None or (tenant_id and record.tenant_id != tenant_id):
        raise HTTPException(status_code=404, detail=f"Approval request not found: {approval_id}")
    record = _service.decide(
        approval_id,
        approved=body.decision == "approve",
        reviewed_by=reviewed_by,
        review_note=body.review_note,
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"Approval request not found: {approval_id}")
    return record.model_dump(mode="json")


@router.post("/{approval_id}/token", dependencies=[require_scope("tools:execute")])
async def issue_tool_approval_token(
    request: Request,
    approval_id: str,
    body: TokenRequest,
) -> dict[str, Any]:
    token_payload = _get_token_payload(request)
    tenant_id = token_payload.tenant_id or ""
    record = _service.get_request(approval_id)
    if record is None or (tenant_id and record.tenant_id != tenant_id):
        raise HTTPException(status_code=404, detail=f"Approval request not found: {approval_id}")
    if record.status != ApprovalStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Approval request is not approved: {approval_id}",
        )
    response = record.model_dump(mode="json")
    response.update(_issue_token_response(record, body, request))
    return response


@router.post("/batch-decision", dependencies=[require_scope("tools:execute")])
async def batch_decide_tool_approvals(
    request: Request,
    body: BatchDecisionRequest,
) -> dict[str, Any]:
    token_payload = _get_token_payload(request)
    tenant_id = token_payload.tenant_id or ""
    reviewed_by = token_payload.sub or ""
    records = []
    for approval_id in body.approval_ids:
        record = _service.get_request(approval_id)
        if record is None or (tenant_id and record.tenant_id != tenant_id):
            raise HTTPException(
                status_code=404,
                detail=f"Approval request not found: {approval_id}",
            )
        if body.decision == "approve" and record.risk_tier == ApprovalRiskTier.HIGH:
            raise HTTPException(
                status_code=400,
                detail=f"High-risk approval requires an individual decision: {approval_id}",
            )
        records.append(record)

    results = []
    for record in records:
        updated = _service.decide(
            record.approval_id,
            approved=body.decision == "approve",
            reviewed_by=reviewed_by,
            review_note=body.review_note,
        )
        if updated is None:
            raise HTTPException(
                status_code=404,
                detail=f"Approval request not found: {record.approval_id}",
            )
        result = updated.model_dump(mode="json")
        if body.issue_tokens and body.decision == "approve":
            result.update(_issue_token_response(updated, body, request))
        results.append(result)

    return {
        "count": len(results),
        "safety_summary": _batch_safety_summary(records, body),
        "results": results,
    }
