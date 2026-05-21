"""Task-level collaboration mode contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from agent33.policy.capabilities import AuthorityLevel


class CollaborationMode(StrEnum):
    PAIRED = "paired"
    AUTONOMOUS = "autonomous"
    REVIEW_ONLY = "review_only"
    APPROVAL_REQUIRED = "approval_required"
    BACKGROUND_WORKER = "background_worker"


class CollaborationModePolicy(BaseModel):
    mode: CollaborationMode
    authority: AuthorityLevel
    requires_approval: bool = False
    completion_gate: str = "advisory"
    interaction_cadence: str = "on_blocker"
    allowed_tools: list[str] = Field(default_factory=list)


def policy_for_mode(mode: CollaborationMode) -> CollaborationModePolicy:
    if mode == CollaborationMode.REVIEW_ONLY:
        return CollaborationModePolicy(
            mode=mode,
            authority=AuthorityLevel.READ_ONLY,
            completion_gate="advisory",
            interaction_cadence="on_completion",
        )
    if mode == CollaborationMode.APPROVAL_REQUIRED:
        return CollaborationModePolicy(
            mode=mode,
            authority=AuthorityLevel.DRY_RUN,
            requires_approval=True,
            completion_gate="fail_closed",
            interaction_cadence="before_mutation",
        )
    if mode == CollaborationMode.AUTONOMOUS:
        return CollaborationModePolicy(
            mode=mode,
            authority=AuthorityLevel.APPROVED_WRITE,
            completion_gate="fail_closed",
            interaction_cadence="on_blocker",
        )
    if mode == CollaborationMode.BACKGROUND_WORKER:
        return CollaborationModePolicy(
            mode=mode,
            authority=AuthorityLevel.DRY_RUN,
            completion_gate="fail_closed",
            interaction_cadence="periodic",
        )
    return CollaborationModePolicy(
        mode=mode,
        authority=AuthorityLevel.DRY_RUN,
        completion_gate="advisory",
        interaction_cadence="frequent",
    )
