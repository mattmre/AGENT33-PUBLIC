"""Structured approval decision models for the improvement-cycle wizard.

Extends the base review signoff with richer decision metadata: rationale,
modification summary, conditions, and optional intake linkage.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ApprovalDecisionType(StrEnum):
    """Extended decision types beyond simple approve/reject."""

    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    ESCALATED = "escalated"
    DEFERRED = "deferred"


class ApproveWithRationaleRequest(BaseModel):
    """Request body for structured approval with rationale.

    Used by ``POST /v1/reviews/{review_id}/approve-with-rationale``.
    """

    decision: ApprovalDecisionType
    rationale: str = ""
    modification_summary: str = ""
    conditions: list[str] = Field(default_factory=list)
    linked_intake_id: str | None = None


class ApprovalDecisionRecord(BaseModel):
    """Persisted record of a structured approval decision."""

    approver_id: str
    decision: ApprovalDecisionType
    rationale: str = ""
    modification_summary: str = ""
    conditions: list[str] = Field(default_factory=list)
    linked_intake_id: str | None = None
