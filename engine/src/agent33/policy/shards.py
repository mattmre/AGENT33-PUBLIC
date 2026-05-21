"""Versioned policy shards for task and run authority."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class PolicyShardKind(StrEnum):
    TOOL_USE = "tool_use"
    FILESYSTEM_WRITE = "filesystem_write"
    NETWORK = "network"
    EXTERNAL_WRITE = "external_write"
    MODEL_ESCALATION = "model_escalation"
    MEMORY_WRITE = "memory_write"
    REVIEW_REQUIREMENT = "review_requirement"
    EVIDENCE_GATE = "evidence_gate"


class PolicyShard(BaseModel):
    id: str
    version: str
    kind: PolicyShardKind
    description: str = ""
    enabled: bool = True
    rules: list[str] = Field(default_factory=list)
    required_scopes: list[str] = Field(default_factory=list)


class ActivePolicySet(BaseModel):
    task_id: str = ""
    run_id: str = ""
    shards: list[PolicyShard] = Field(default_factory=list)

    def active_kinds(self) -> list[PolicyShardKind]:
        return sorted({shard.kind for shard in self.shards if shard.enabled}, key=str)


def default_policy_shards() -> list[PolicyShard]:
    return [
        PolicyShard(
            id="policy.tool-use.default",
            version="1.0.0",
            kind=PolicyShardKind.TOOL_USE,
            description="Allow bounded tool use through declared scopes.",
            rules=["tools require schema validation", "mutating tools require audit receipts"],
            required_scopes=["tools:execute"],
        ),
        PolicyShard(
            id="policy.evidence.default",
            version="1.0.0",
            kind=PolicyShardKind.EVIDENCE_GATE,
            description="Require evidence before completion.",
            rules=["completion requires at least one evidence record"],
        ),
    ]
