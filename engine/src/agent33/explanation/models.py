"""Models for explanation artifact metadata and API contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class FactCheckStatus(StrEnum):
    """Status of fact-check validation."""

    PENDING = "pending"
    VERIFIED = "verified"
    FLAGGED = "flagged"
    SKIPPED = "skipped"


class ExplanationMode(StrEnum):
    """Supported explanation generation modes."""

    GENERIC = "generic"
    DIFF_REVIEW = "diff_review"
    PLAN_REVIEW = "plan_review"
    PROJECT_RECAP = "project_recap"


class ClaimType(StrEnum):
    """Supported deterministic fact-check claim types."""

    FILE_EXISTS = "file_exists"
    METADATA_EQUALS = "metadata_equals"
    CONTENT_CONTAINS = "content_contains"


class ExplanationClaimRequest(BaseModel):
    """Input claim definition for fact-check validation."""

    claim_type: ClaimType
    target: str = Field(..., min_length=1, description="Claim target key/path")
    expected: str = Field(default="", description="Expected value for validation")
    description: str = Field(default="", description="Human-readable claim description")


class ExplanationClaim(BaseModel):
    """Stored claim with validation details."""

    id: str = Field(default_factory=lambda: f"claim-{uuid.uuid4().hex[:8]}")
    claim_type: ClaimType
    target: str
    expected: str = ""
    description: str = ""
    actual: str = ""
    message: str = ""
    status: FactCheckStatus = FactCheckStatus.PENDING


class ExplanationRequest(BaseModel):
    """Request to generate an explanation."""

    entity_type: str = Field(..., min_length=1, description="Type of entity to explain")
    entity_id: str = Field(..., min_length=1, description="ID of the entity")
    mode: ExplanationMode = Field(
        default=ExplanationMode.GENERIC,
        description="Rendering mode used to structure explanation content",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata for generation",
    )
    claims: list[ExplanationClaimRequest] = Field(
        default_factory=list,
        description="Optional deterministic claims for fact-check validation",
    )


class DiffReviewRequest(BaseModel):
    """Request to generate a diff review explanation."""

    entity_type: str = Field(..., min_length=1, description="Type of entity")
    entity_id: str = Field(..., min_length=1, description="ID of the entity")
    diff_text: str = Field(..., min_length=1, description="Diff content to review")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata",
    )
    claims: list[ExplanationClaimRequest] = Field(
        default_factory=list,
        description="Optional deterministic claims for fact-check validation",
    )


class PlanReviewRequest(BaseModel):
    """Request to generate a plan review explanation."""

    entity_type: str = Field(..., min_length=1, description="Type of entity")
    entity_id: str = Field(..., min_length=1, description="ID of the entity")
    plan_text: str = Field(..., min_length=1, description="Plan content (markdown format)")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata",
    )
    claims: list[ExplanationClaimRequest] = Field(
        default_factory=list,
        description="Optional deterministic claims for fact-check validation",
    )


class ProjectRecapRequest(BaseModel):
    """Request to generate a project recap explanation."""

    entity_type: str = Field(..., min_length=1, description="Type of entity")
    entity_id: str = Field(..., min_length=1, description="ID of the entity")
    recap_text: str = Field(..., min_length=1, description="Recap content")
    highlights: list[str] = Field(
        default_factory=list,
        description="Optional list of highlight items",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata",
    )
    claims: list[ExplanationClaimRequest] = Field(
        default_factory=list,
        description="Optional deterministic claims for fact-check validation",
    )


class ExplanationMetadata(BaseModel):
    """Metadata for a generated explanation artifact."""

    id: str = Field(..., description="Unique explanation identifier")
    entity_type: str = Field(..., description="Type of entity (workflow, agent, etc.)")
    entity_id: str = Field(..., description="ID of the entity being explained")
    content: str = Field(..., description="Explanation text content")
    fact_check_status: FactCheckStatus = Field(
        default=FactCheckStatus.PENDING,
        description="Current fact-check validation status",
    )
    mode: ExplanationMode = Field(
        default=ExplanationMode.GENERIC,
        description="Generation mode used to produce this explanation",
    )
    claims: list[ExplanationClaim] = Field(
        default_factory=list,
        description="Deterministic fact-check claims and validation results",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when explanation was generated",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata (model used, confidence, etc.)",
    )
