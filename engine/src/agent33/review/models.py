"""Pydantic models for the two-layer review system.

Schema aligns with ``core/orchestrator/TWO_LAYER_REVIEW.md`` signoff_record.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RiskLevel(StrEnum):
    """Risk level for a change set."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskTrigger(StrEnum):
    """Categories of risk triggers from RISK_TRIGGERS.md."""

    DOCUMENTATION = "documentation"
    CONFIG = "config"
    CODE_ISOLATED = "code-isolated"
    API_INTERNAL = "api-internal"
    API_PUBLIC = "api-public"
    SECURITY = "security"
    SCHEMA = "schema"
    INFRASTRUCTURE = "infrastructure"
    PROMPT_AGENT = "prompt-agent"
    SECRETS = "secrets"
    PRODUCTION_DATA = "production-data"
    PROMPT_INJECTION = "prompt-injection"
    SANDBOX_ESCAPE = "sandbox-escape"
    SUPPLY_CHAIN = "supply-chain"


class SignoffState(StrEnum):
    """Lifecycle states for a review record."""

    DRAFT = "draft"
    READY = "ready"
    L1_REVIEW = "l1-review"
    L1_CHANGES_REQUESTED = "l1-changes-requested"
    L1_APPROVED = "l1-approved"
    L2_REVIEW = "l2-review"
    L2_CHANGES_REQUESTED = "l2-changes-requested"
    L2_APPROVED = "l2-approved"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes-requested"
    DEFERRED = "deferred"
    MERGED = "merged"


class ReviewDecision(StrEnum):
    """Decision a reviewer can make."""

    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    ESCALATED = "escalated"


class ChecklistVerdict(StrEnum):
    """Verdict for a single checklist category."""

    PASS = "pass"
    FAIL = "fail"
    NA = "na"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class L1ChecklistResults(BaseModel):
    """L1 (technical) checklist outcomes."""

    code_quality: ChecklistVerdict = ChecklistVerdict.NA
    correctness: ChecklistVerdict = ChecklistVerdict.NA
    testing: ChecklistVerdict = ChecklistVerdict.NA
    scope: ChecklistVerdict = ChecklistVerdict.NA


class L2ChecklistResults(BaseModel):
    """L2 (domain) checklist outcomes."""

    architecture: ChecklistVerdict = ChecklistVerdict.NA
    security: ChecklistVerdict = ChecklistVerdict.NA
    compliance: ChecklistVerdict = ChecklistVerdict.NA
    impact: ChecklistVerdict = ChecklistVerdict.NA


class RiskAssessment(BaseModel):
    """Automated or manual risk assessment for a change set."""

    risk_level: RiskLevel = RiskLevel.NONE
    triggers_identified: list[RiskTrigger] = Field(default_factory=list)
    l1_required: bool = False
    l2_required: bool = False


class LayerReview(BaseModel):
    """Review record for a single layer (L1 or L2)."""

    reviewer_id: str = ""
    reviewer_role: str = ""
    assigned_at: datetime | None = None
    completed_at: datetime | None = None
    decision: ReviewDecision | None = None
    checklist_results: dict[str, str] = Field(default_factory=dict)
    issues_found: list[str] = Field(default_factory=list)
    comments: str = ""


class FinalSignoff(BaseModel):
    """Final approval record."""

    approved_by: str = ""
    approved_at: datetime | None = None
    approval_type: str = ""  # l1_only | l1_l2_agent | l1_l2_human
    conditions: list[str] = Field(default_factory=list)
    rationale: str = ""
    modification_summary: str = ""
    linked_intake_id: str | None = None


class ReviewEvidence(BaseModel):
    """Links to verification artifacts."""

    verification_log_ref: str = ""
    evidence_capture_ref: str = ""


class ReviewArtifactLink(BaseModel):
    """Operator-facing linkage to a review artifact such as an explanation."""

    kind: str = ""
    artifact_id: str = ""
    label: str = ""
    mode: str = ""


# ---------------------------------------------------------------------------
# Top-level review record
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return f"rev-{uuid.uuid4().hex[:12]}"


class ReviewRecord(BaseModel):
    """Complete review record matching the signoff_record schema."""

    id: str = Field(default_factory=_new_id)
    task_id: str = ""
    branch: str = ""
    pr_number: int | None = None
    tenant_id: str = ""

    state: SignoffState = SignoffState.DRAFT
    risk_assessment: RiskAssessment = Field(default_factory=RiskAssessment)
    l1_review: LayerReview = Field(default_factory=LayerReview)
    l2_review: LayerReview = Field(default_factory=LayerReview)
    final_signoff: FinalSignoff = Field(default_factory=FinalSignoff)
    evidence: ReviewEvidence = Field(default_factory=ReviewEvidence)
    artifacts: list[ReviewArtifactLink] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def touch(self) -> None:
        """Update the ``updated_at`` timestamp."""
        self.updated_at = datetime.now(UTC)
