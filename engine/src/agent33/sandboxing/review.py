"""Sandboxing review model."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SandboxRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SandboxReview(BaseModel):
    surface: str
    risk: SandboxRisk
    recommendation: str
    blockers: list[str] = Field(default_factory=list)
    safe_mounts_required: bool = True


def requires_review(review: SandboxReview) -> bool:
    return review.risk != SandboxRisk.LOW or bool(review.blockers)


def sandbox_review_summary(review: SandboxReview) -> dict[str, object]:
    return {
        "surface": review.surface,
        "requires_review": requires_review(review),
        "risk": review.risk.value,
        "blockers": list(review.blockers),
        "safe_mounts_required": review.safe_mounts_required,
        "recommendation": review.recommendation,
    }
