"""Memory write gate for governed durable memory writes."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from enum import StrEnum

from pydantic import BaseModel, Field


class MemoryReviewState(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    DISPUTED = "disputed"


class MemoryWriteRequest(BaseModel):
    content: str
    source: str
    confidence: float = Field(ge=0, le=1)
    authority: str
    ttl_expires_at: datetime | None = None
    evidence_uri: str
    tenant_id: str
    scope: str
    review_state: MemoryReviewState = MemoryReviewState.PENDING


class MemoryWriteGateResult(BaseModel):
    allowed: bool
    missing_requirements: list[str] = Field(default_factory=list)


def evaluate_memory_write(request: MemoryWriteRequest) -> MemoryWriteGateResult:
    missing: list[str] = []
    for field_name in ["content", "source", "authority", "evidence_uri", "tenant_id", "scope"]:
        if not getattr(request, field_name).strip():
            missing.append(field_name)
    if request.confidence < 0.5 and request.review_state != MemoryReviewState.VERIFIED:
        missing.append("verified_review_for_low_confidence")
    return MemoryWriteGateResult(allowed=not missing, missing_requirements=missing)
