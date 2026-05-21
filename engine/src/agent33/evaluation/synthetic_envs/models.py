"""Pydantic models for synthetic environment generation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from agent33.workflows.definition import WorkflowDefinition  # noqa: TC001


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class SyntheticToolContract(BaseModel):
    """Simplified tool contract included in generated environment bundles."""

    tool_id: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    governance: dict[str, Any] = Field(default_factory=dict)


class SyntheticWorkflowCatalogEntry(BaseModel):
    """Discovered workflow template available for synthetic generation."""

    workflow_name: str
    workflow_version: str
    description: str = ""
    step_count: int = 0
    tags: list[str] = Field(default_factory=list)
    inferred_tool_ids: list[str] = Field(default_factory=list)


class SyntheticTaskPrompt(BaseModel):
    """Synthetic task prompt derived from a workflow variant."""

    task_id: str = Field(default_factory=lambda: _new_id("TASK"))
    title: str
    prompt: str
    success_criteria: list[str] = Field(default_factory=list)
    recommended_tool_ids: list[str] = Field(default_factory=list)


class SyntheticVerificationQuery(BaseModel):
    """Deterministic SQL assertion for synthetic environment verification."""

    query_id: str = Field(default_factory=lambda: _new_id("CHK"))
    description: str
    sql: str
    expected_value: int | str


class SyntheticEnvironment(BaseModel):
    """A single generated synthetic environment variant."""

    environment_id: str = Field(default_factory=lambda: _new_id("SENV"))
    workflow_name: str
    workflow_version: str
    variant_index: int = Field(ge=1)
    domain_tags: list[str] = Field(default_factory=list)
    inferred_tool_ids: list[str] = Field(default_factory=list)
    tool_contracts: list[SyntheticToolContract] = Field(default_factory=list)
    workflow: WorkflowDefinition
    initial_state_sql: list[str] = Field(default_factory=list)
    completion_sql: list[str] = Field(default_factory=list)
    tasks: list[SyntheticTaskPrompt] = Field(default_factory=list)
    verification_queries: list[SyntheticVerificationQuery] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class SyntheticEnvironmentBundle(BaseModel):
    """A collection of generated synthetic environments."""

    bundle_id: str = Field(default_factory=lambda: _new_id("BND"))
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_workflows: list[str] = Field(default_factory=list)
    environments: list[SyntheticEnvironment] = Field(default_factory=list)
