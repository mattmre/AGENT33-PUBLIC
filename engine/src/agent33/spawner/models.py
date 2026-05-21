"""Data models for the Sub-Agent Spawner (Phase 71).

Defines the workflow definition, child agent configuration, isolation modes,
and the execution tree structure used for live status tracking.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class IsolationMode(StrEnum):
    """Environment isolation level for a spawned child agent."""

    LOCAL = "local"  # same process, no sandboxing
    SUBPROCESS = "subprocess"  # subprocess isolation
    DOCKER = "docker"  # Docker container (if available)


class ChildAgentConfig(BaseModel):
    """Configuration for a single child agent within a spawner workflow."""

    agent_name: str = Field(min_length=1, description="Name of the agent definition to invoke.")
    system_prompt_override: str | None = Field(
        default=None,
        description="Optional system prompt override for this child invocation.",
    )
    tool_allowlist: list[str] = Field(
        default_factory=list,
        description="Tool names the child is allowed to use (empty = all).",
    )
    autonomy_level: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Autonomy level (0=ask everything, 3=fully autonomous).",
    )
    isolation: IsolationMode = Field(
        default=IsolationMode.LOCAL,
        description="Isolation environment for the child agent.",
    )
    pack_names: list[str] = Field(
        default_factory=list,
        description="Improvement packs to apply to this child.",
    )


class SubAgentWorkflow(BaseModel):
    """A saved sub-agent workflow definition: one parent + N children."""

    id: str = Field(default_factory=lambda: f"wf-{uuid.uuid4().hex[:8]}")
    name: str = Field(min_length=1, max_length=200, description="Human-readable workflow name.")
    description: str = Field(default="", max_length=2000)
    parent_agent: str = Field(min_length=1, description="Name of the parent agent.")
    children: list[ChildAgentConfig] = Field(
        default_factory=list,
        description="Ordered list of child agent configurations.",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExecutionNode(BaseModel):
    """A node in the live execution tree, representing one agent invocation."""

    agent_name: str
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result_summary: str | None = Field(
        default=None,
        description="First 200 chars of the agent's output.",
    )
    error: str | None = None
    children: list[ExecutionNode] = Field(default_factory=list)


class ExecutionTree(BaseModel):
    """Full execution status for a running/completed spawner workflow."""

    workflow_id: str
    execution_id: str = Field(default_factory=lambda: f"exec-{uuid.uuid4().hex[:8]}")
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    root: ExecutionNode
    started_at: datetime | None = None
    completed_at: datetime | None = None
