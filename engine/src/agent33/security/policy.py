"""Active policy state — reads from config/settings and exposes as a structured model."""

from __future__ import annotations

from pydantic import BaseModel


class PolicyShard(BaseModel):
    id: str
    label: str
    mode: str


class CollaborationMode(BaseModel):
    id: str
    label: str
    detail: str


class ActivePolicy(BaseModel):
    tool_use_mode: str  # "audit" | "dry-run" | "approved"
    evidence_required: bool
    review_authority: str  # "user" | "automation" | "disabled"
    policy_shards: list[PolicyShard]
    collaboration_modes: list[CollaborationMode]


def get_active_policy(settings: object) -> ActivePolicy:
    """Derive active policy from current config settings.

    The policy-shard and collaboration-mode lists mirror the constants that
    were previously hardcoded in the frontend, now served from the engine so
    they can be driven by runtime config in the future.
    """
    tool_use_mode: str = str(getattr(settings, "tool_use_mode", "audit"))
    evidence_required: bool = bool(getattr(settings, "evidence_required", True))
    review_authority: str = str(getattr(settings, "review_authority", "user"))

    return ActivePolicy(
        tool_use_mode=tool_use_mode,
        evidence_required=evidence_required,
        review_authority=review_authority,
        policy_shards=[
            PolicyShard(
                id="policy.tool-use.default",
                label="Tool use",
                mode="Schema validation and audit receipts",
            ),
            PolicyShard(
                id="policy.evidence.default",
                label="Evidence gate",
                mode="Completion requires proof",
            ),
            PolicyShard(
                id="policy.review.default",
                label="Review",
                mode="High-risk work asks for review",
            ),
        ],
        collaboration_modes=[
            CollaborationMode(
                id="paired",
                label="Paired",
                detail="Frequent interaction with dry-run authority",
            ),
            CollaborationMode(
                id="autonomous",
                label="Autonomous",
                detail="Approved writes with fail-closed completion",
            ),
            CollaborationMode(
                id="review_only",
                label="Review only",
                detail="Read-only inspection and recommendations",
            ),
            CollaborationMode(
                id="approval_required",
                label="Approval required",
                detail="Dry runs until a mutation is approved",
            ),
            CollaborationMode(
                id="background_worker",
                label="Background worker",
                detail="Periodic check-ins with fail-closed proof",
            ),
        ],
    )
