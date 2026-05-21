"""Marketplace moderation and reputation queue contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ModerationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"


class ModerationQueueItem(BaseModel):
    resource_id: str
    submitter: str
    reputation: int = 0
    status: ModerationStatus = ModerationStatus.PENDING
    flags: list[str] = Field(default_factory=list)


class ModerationRecommendation(BaseModel):
    resource_id: str
    next_action: str
    reasons: list[str] = Field(default_factory=list)


def prioritize_moderation(
    items: list[ModerationQueueItem],
) -> list[ModerationQueueItem]:
    return sorted(
        items,
        key=lambda item: (
            item.status != ModerationStatus.PENDING,
            -item.reputation,
            item.resource_id,
        ),
    )


def recommend_moderation_action(item: ModerationQueueItem) -> ModerationRecommendation:
    if item.status != ModerationStatus.PENDING:
        return ModerationRecommendation(
            resource_id=item.resource_id,
            next_action="no_action",
            reasons=[f"status is {item.status.value}"],
        )
    if item.flags:
        return ModerationRecommendation(
            resource_id=item.resource_id,
            next_action="manual_review",
            reasons=item.flags,
        )
    if item.reputation >= 50:
        return ModerationRecommendation(
            resource_id=item.resource_id,
            next_action="expedite_review",
            reasons=["trusted submitter reputation"],
        )
    return ModerationRecommendation(
        resource_id=item.resource_id,
        next_action="standard_review",
    )
