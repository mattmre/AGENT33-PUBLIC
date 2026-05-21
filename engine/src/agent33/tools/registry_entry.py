"""Tool registry entry with metadata per Phase 12 spec."""

from __future__ import annotations

from datetime import date  # noqa: TC003 – Pydantic needs runtime access
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolStatus(StrEnum):
    """Lifecycle status of a registered tool."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    BLOCKED = "blocked"


class ToolProvenance(BaseModel):
    """Source and integrity metadata for a tool."""

    repo_url: str = ""
    commit_or_tag: str = ""
    checksum: str = ""
    license: str = ""


class ToolScope(BaseModel):
    """Permission scope for a tool."""

    commands: list[str] = Field(default_factory=list)
    endpoints: list[str] = Field(default_factory=list)
    data_access: Literal["read", "write", "none"] = "none"
    network: bool = False
    filesystem: list[str] = Field(default_factory=list)


class ToolApproval(BaseModel):
    """Approval record for a tool registry entry."""

    approver: str = ""
    approved_date: date | None = None
    evidence: str = ""


class ToolRegistryEntry(BaseModel):
    """Complete registry entry per Phase 12 spec."""

    tool_id: str
    name: str
    version: str
    description: str = ""
    owner: str = ""
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)
    scope: ToolScope = Field(default_factory=ToolScope)
    approval: ToolApproval = Field(default_factory=ToolApproval)
    status: ToolStatus = ToolStatus.ACTIVE
    last_review: date | None = None
    next_review: date | None = None
    deprecation_message: str = ""
    tags: list[str] = Field(default_factory=list)
    parameters_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema for tool input parameters.",
    )
    result_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema for tool output.",
    )
