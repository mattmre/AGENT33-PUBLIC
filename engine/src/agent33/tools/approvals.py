"""HITL approval lifecycle for governed tool operations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, ValidationError

if TYPE_CHECKING:
    from agent33.services.orchestration_state import OrchestrationStateStore


class ApprovalStatus(StrEnum):
    """Lifecycle state for a tool approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONSUMED = "consumed"
    EXPIRED = "expired"


class ApprovalReason(StrEnum):
    """Reason a governed tool call requires operator approval."""

    TOOL_POLICY_ASK = "tool_policy_ask"
    SUPERVISED_DESTRUCTIVE = "supervised_destructive"
    ROUTE_MUTATION = "route_mutation"


class ApprovalRiskTier(StrEnum):
    """Risk class used for approval batching and token presets."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _new_approval_id() -> str:
    return f"APR-{uuid.uuid4().hex[:12]}"


class ToolApprovalRequest(BaseModel):
    """Single operator approval request for a governed tool call."""

    approval_id: str = Field(default_factory=_new_approval_id)
    status: ApprovalStatus = ApprovalStatus.PENDING
    reason: ApprovalReason
    tool_name: str
    operation: str = ""
    command: str = ""
    requested_by: str = ""
    tenant_id: str = ""
    details: str = ""
    arguments: dict[str, object] = Field(default_factory=dict)
    risk_tier: ApprovalRiskTier = ApprovalRiskTier.MEDIUM
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    reviewed_by: str = ""
    reviewed_at: datetime | None = None
    review_note: str = ""


class ToolApprovalService:
    """In-memory approval service with optional durable namespace backing."""

    def __init__(
        self,
        state_store: OrchestrationStateStore | None = None,
        *,
        default_ttl_minutes: int = 60,
    ) -> None:
        self._state_store = state_store
        self._default_ttl_minutes = max(1, default_ttl_minutes)
        self._requests: dict[str, ToolApprovalRequest] = {}
        self._load_state()

    def request(
        self,
        *,
        reason: ApprovalReason,
        tool_name: str,
        operation: str = "",
        command: str = "",
        requested_by: str = "",
        tenant_id: str = "",
        details: str = "",
        arguments: dict[str, object] | None = None,
        risk_tier: ApprovalRiskTier = ApprovalRiskTier.MEDIUM,
    ) -> ToolApprovalRequest:
        """Create and persist a pending approval request."""
        self._expire_pending()
        req = ToolApprovalRequest(
            reason=reason,
            tool_name=tool_name,
            operation=operation,
            command=command,
            requested_by=requested_by,
            tenant_id=tenant_id,
            details=details,
            arguments=dict(arguments or {}),
            risk_tier=risk_tier,
            expires_at=datetime.now(UTC) + timedelta(minutes=self._default_ttl_minutes),
        )
        self._requests[req.approval_id] = req
        self._persist_state()
        return req

    def get_request(self, approval_id: str) -> ToolApprovalRequest | None:
        """Return a request by ID, expiring stale pending requests first."""
        self._expire_pending()
        return self._requests.get(approval_id)

    def list_requests(
        self,
        *,
        status: ApprovalStatus | None = None,
        requested_by: str | None = None,
        tenant_id: str = "",
        limit: int = 100,
    ) -> list[ToolApprovalRequest]:
        """List approval requests with optional filters."""
        self._expire_pending()
        items = list(self._requests.values())
        if tenant_id:
            items = [item for item in items if item.tenant_id == tenant_id]
        if status is not None:
            items = [item for item in items if item.status == status]
        if requested_by is not None:
            items = [item for item in items if item.requested_by == requested_by]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[:limit]

    def decide(
        self,
        approval_id: str,
        *,
        approved: bool,
        reviewed_by: str,
        review_note: str = "",
    ) -> ToolApprovalRequest | None:
        """Approve or reject a pending request."""
        self._expire_pending()
        req = self._requests.get(approval_id)
        if req is None:
            return None
        if req.status != ApprovalStatus.PENDING:
            return req
        req.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        req.reviewed_by = reviewed_by
        req.reviewed_at = datetime.now(UTC)
        req.review_note = review_note
        self._persist_state()
        return req

    def consume_if_approved(
        self,
        approval_id: str,
        *,
        tool_name: str,
        operation: str = "",
        tenant_id: str = "",
    ) -> bool:
        """Consume an approved request for a matching governed operation."""
        self._expire_pending()
        req = self._requests.get(approval_id)
        if req is None or req.status != ApprovalStatus.APPROVED:
            return False
        if tenant_id and req.tenant_id != tenant_id:
            return False
        if req.tool_name != tool_name:
            return False
        if req.operation and req.operation != operation:
            return False
        req.status = ApprovalStatus.CONSUMED
        consumed_note = "Consumed by governed execution."
        if req.review_note:
            req.review_note = f"{req.review_note} {consumed_note}"
        else:
            req.review_note = consumed_note
        self._persist_state()
        return True

    def is_approved(
        self,
        approval_id: str,
        *,
        tool_name: str,
        operation: str = "",
        tenant_id: str = "",
    ) -> bool:
        """Return True when an approval is currently approved for the request."""
        self._expire_pending()
        req = self._requests.get(approval_id)
        if req is None or req.status != ApprovalStatus.APPROVED:
            return False
        if tenant_id and req.tenant_id != tenant_id:
            return False
        if req.tool_name != tool_name:
            return False
        return not (req.operation and req.operation != operation)

    def _expire_pending(self) -> None:
        now = datetime.now(UTC)
        changed = False
        for req in self._requests.values():
            if (
                req.status == ApprovalStatus.PENDING
                and req.expires_at is not None
                and req.expires_at <= now
            ):
                req.status = ApprovalStatus.EXPIRED
                req.review_note = "Approval request expired."
                changed = True
        if changed:
            self._persist_state()

    def _persist_state(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            "tool_approvals",
            {
                "requests": {
                    approval_id: req.model_dump(mode="json")
                    for approval_id, req in self._requests.items()
                }
            },
        )

    def _load_state(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace("tool_approvals")
        requests_payload = payload.get("requests", {})
        if not isinstance(requests_payload, dict):
            return
        for approval_id, request_data in requests_payload.items():
            if not isinstance(approval_id, str):
                continue
            try:
                self._requests[approval_id] = ToolApprovalRequest.model_validate(request_data)
            except ValidationError:
                continue
