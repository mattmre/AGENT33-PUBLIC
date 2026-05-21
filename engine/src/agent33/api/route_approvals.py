"""Helpers for approval-token-gated route mutations."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request, status

from agent33.api.routes.tool_approvals import (
    _resolve_approval_token_manager,
    get_tool_approval_service,
)
from agent33.security.approval_tokens import ApprovalTokenError
from agent33.security.permissions import _get_token_payload
from agent33.tools.approvals import ApprovalReason, ApprovalRiskTier

APPROVAL_TOKEN_HEADER = "X-Agent33-Approval-Token"


def require_route_mutation_approval(
    request: Request,
    *,
    route_name: str,
    operation: str,
    arguments: dict[str, Any],
    details: str,
    risk_tier: ApprovalRiskTier = ApprovalRiskTier.HIGH,
) -> None:
    """Require a valid approval token for a sensitive route mutation.

    When the token is missing, a new pending approval request is created and the
    caller receives a ``428 Precondition Required`` response with the approval ID.
    """
    approval_service = get_tool_approval_service()
    token_manager = _resolve_approval_token_manager(request)
    if token_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Approval tokens are not enabled",
        )

    token_payload = _get_token_payload(request)
    tenant_id = token_payload.tenant_id or ""
    approval_token = request.headers.get(APPROVAL_TOKEN_HEADER, "").strip()
    tool_name = f"route:{route_name}"
    normalized_arguments = dict(arguments)

    if not approval_token:
        approval = approval_service.request(
            reason=ApprovalReason.ROUTE_MUTATION,
            tool_name=tool_name,
            operation=operation,
            command=f"{operation} {route_name}",
            requested_by=token_payload.sub or "",
            tenant_id=tenant_id,
            details=details,
            arguments=normalized_arguments,
            risk_tier=risk_tier,
        )
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={
                "message": "Sensitive route mutation requires approval",
                "approval_id": approval.approval_id,
                "status": approval.status,
                "approval_header": APPROVAL_TOKEN_HEADER,
            },
        )

    try:
        approval_claims = token_manager.validate(
            approval_token,
            tool_name,
            normalized_arguments,
            tenant_id=tenant_id,
            consume=False,
        )
    except ApprovalTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Invalid approval token: {exc}",
        ) from exc

    if not approval_service.consume_if_approved(
        approval_claims.jti,
        tool_name=tool_name,
        operation=operation,
        tenant_id=tenant_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Approval is not approved or has already been consumed",
        )

    if approval_claims.one_time and not token_manager.consume(approval_claims.jti):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Approval token has already been consumed",
        )
