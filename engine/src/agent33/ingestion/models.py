"""Type models for the candidate asset ingestion lifecycle.

Defines the ``CandidateAsset`` Pydantic model and its supporting enumerations.
Lifecycle behavior is implemented by the ingestion service, state machine,
persistence layer, journal, and notification modules.

CLEAN-ROOM RESTRICTION
=======================
No code in this file may originate from the EvoMap/Evolver project.  All types
are derived from AGENT33's own architectural decisions:

- **Decision #17** — concept-only clean-room adaptation
  (docs/phases/PHASE-PLAN-POST-P72-2026.md)
- **Decision #18** — ``candidate -> validated -> published -> revoked`` lifecycle
  with confidence/trust labels
  (docs/phases/PHASE-PLAN-POST-P72-2026.md)

Full design contract: ``docs/research/evolver-clean-room-guardrails.md``
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 -- Pydantic needs datetime at runtime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class CandidateStatus(StrEnum):
    """Lifecycle status of a candidate asset.

    Mirrors the canonical lifecycle defined in architectural decision #18:
    ``candidate -> validated -> published -> revoked``.
    """

    CANDIDATE = "candidate"
    VALIDATED = "validated"
    PUBLISHED = "published"
    REVOKED = "revoked"


class ConfidenceLevel(StrEnum):
    """Trust / confidence label applied to an ingested asset.

    Confidence is layered onto lifecycle status per architectural decision #18.
    External assets always enter at LOW; confidence may be upgraded through
    explicit operator review.
    """

    HIGH = "high"
    """First-party / internal assets with full provenance documentation."""

    MEDIUM = "medium"
    """Community-reviewed external assets whose origin and integrity are known."""

    LOW = "low"
    """Unreviewed external or community submissions (default for all intake)."""


class CandidateAsset(BaseModel):
    """A candidate asset progressing through the AGENT33 ingestion lifecycle.

    This model is the canonical record for any skill, pack, workflow, or tool
    that originates outside AGENT33's first-party tree.  It tracks the asset's
    position in the lifecycle, its confidence level, and the timestamps and
    reasons for each transition.
    """

    model_config = {"frozen": False, "extra": "forbid"}

    id: str = Field(..., description="UUID identifying this candidate asset record.")
    name: str = Field(..., min_length=1, max_length=128, description="Human-readable asset name.")
    asset_type: str = Field(
        ...,
        description='Asset category: "skill", "pack", "workflow", or "tool".',
    )
    status: CandidateStatus = Field(
        ...,
        description="Current position in the candidate lifecycle.",
    )
    confidence: ConfidenceLevel = Field(
        ...,
        description="Trust/confidence label.  Defaults to LOW for all external intake.",
    )
    source_uri: str | None = Field(
        default=None,
        description="URI identifying the upstream source of this asset, if known.",
    )
    tenant_id: str = Field(
        ...,
        description="Tenant scope for this asset record.",
    )
    created_at: datetime = Field(
        ...,
        description="When the asset record was first created (intake timestamp).",
    )
    updated_at: datetime = Field(
        ...,
        description="When the asset record was last modified.",
    )
    validated_at: datetime | None = Field(
        default=None,
        description="When the asset was promoted to VALIDATED status.",
    )
    published_at: datetime | None = Field(
        default=None,
        description="When the asset was promoted to PUBLISHED status.",
    )
    revoked_at: datetime | None = Field(
        default=None,
        description="When the asset was revoked, if applicable.",
    )
    revocation_reason: str | None = Field(
        default=None,
        description="Operator-supplied reason for revocation.  Required on revocation.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key/value metadata attached by the intake workflow.",
    )
