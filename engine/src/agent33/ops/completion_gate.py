"""Completion gate contract for proof-aware run finalization."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class CompletionGateMode(StrEnum):
    ADVISORY = "advisory"
    FAIL_CLOSED = "fail_closed"


class CompletionGateInput(BaseModel):
    run_id: str = ""
    mode: CompletionGateMode = CompletionGateMode.ADVISORY
    evidence_count: int = Field(default=0, ge=0)
    verification_count: int = Field(default=0, ge=0)
    unresolved_blockers: list[str] = Field(default_factory=list)
    require_evidence: bool = True
    require_verification: bool = True


class CompletionGateResult(BaseModel):
    run_id: str = ""
    mode: CompletionGateMode
    allowed: bool
    missing_requirements: list[str] = Field(default_factory=list)
    summary: str


def evaluate_completion_gate(request: CompletionGateInput) -> CompletionGateResult:
    """Evaluate completion readiness without mutating run state."""
    missing: list[str] = []
    if request.require_evidence and request.evidence_count < 1:
        missing.append("evidence")
    if request.require_verification and request.verification_count < 1:
        missing.append("verification")
    if request.unresolved_blockers:
        missing.append("blockers")

    allowed = request.mode == CompletionGateMode.ADVISORY or not missing
    summary = (
        "Completion gate passed."
        if not missing
        else f"Completion gate found missing requirements: {', '.join(missing)}."
    )
    if missing and request.mode == CompletionGateMode.ADVISORY:
        summary += " Advisory mode reports issues without blocking completion."

    return CompletionGateResult(
        run_id=request.run_id,
        mode=request.mode,
        allowed=allowed,
        missing_requirements=missing,
        summary=summary,
    )
