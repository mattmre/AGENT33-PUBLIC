"""Pydantic models for workflow definitions."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class StepAction(StrEnum):
    """Available step actions."""

    INVOKE_AGENT = "invoke-agent"
    RUN_COMMAND = "run-command"
    VALIDATE = "validate"
    TRANSFORM = "transform"
    CONDITIONAL = "conditional"
    PARALLEL_GROUP = "parallel-group"
    WAIT = "wait"
    EXECUTE_CODE = "execute-code"
    HTTP_REQUEST = "http-request"
    SUB_WORKFLOW = "sub-workflow"
    ROUTE = "route"
    GROUP_CHAT = "group-chat"


class ExecutionMode(StrEnum):
    """Workflow execution modes."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    DEPENDENCY_AWARE = "dependency-aware"


class TriggerEvent(StrEnum):
    """System events that can trigger workflows."""

    SESSION_START = "session-start"
    SESSION_END = "session-end"
    ARTIFACT_CREATED = "artifact-created"
    REVIEW_COMPLETE = "review-complete"
    WEBHOOK = "webhook"
    SCHEDULE = "schedule"


class StepRetry(BaseModel):
    """Retry configuration for a workflow step."""

    max_attempts: int = Field(default=1, ge=1, le=10)
    delay_seconds: int = Field(default=1, ge=1)


class WorkflowStep(BaseModel):
    """A single step within a workflow."""

    id: str = Field(..., pattern=r"^[a-z][a-z0-9_-]*$")
    name: str | None = None
    action: StepAction
    agent: str | None = None
    command: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    condition: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    retry: StepRetry = Field(default_factory=StepRetry)
    timeout_seconds: int | None = Field(default=None, ge=10)
    # For parallel-group action: sub-steps
    steps: list[WorkflowStep] = Field(default_factory=list)
    # For conditional action: branches
    then_steps: list[WorkflowStep] = Field(default_factory=list, alias="then")
    else_steps: list[WorkflowStep] = Field(default_factory=list, alias="else")
    # For wait action
    duration_seconds: int | None = None
    wait_condition: str | None = None
    # For execute-code action
    tool_id: str | None = None
    adapter_id: str | None = None
    sandbox: dict[str, Any] | None = None
    # For http-request action
    url: str | None = None
    http_method: str = "GET"
    http_headers: dict[str, str] | None = None
    http_body: Any | None = None
    # For sub-workflow action
    sub_workflow: dict[str, Any] | None = None
    # For route action
    query: str | None = None
    route_candidates: list[str] | None = None
    route_model: str = "llama3.2"
    # For group-chat action
    group_chat: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


class WorkflowTriggers(BaseModel):
    """Trigger configuration for a workflow."""

    manual: bool = True
    on_change: list[str] = Field(default_factory=list)
    schedule: str | None = None
    on_event: list[TriggerEvent] = Field(default_factory=list)


class ParameterDef(BaseModel):
    """Workflow input/output parameter definition."""

    type: str
    description: str | None = None
    required: bool = False
    default: Any = None


class WorkflowExecution(BaseModel):
    """Execution configuration for a workflow."""

    mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    parallel_limit: int = Field(default=4, ge=1, le=32)
    continue_on_error: bool = False
    fail_fast: bool = True
    timeout_seconds: int | None = Field(default=None, ge=60, le=86400)
    dry_run: bool = False


class WorkflowMetadata(BaseModel):
    """Optional workflow metadata."""

    author: str | None = None
    created: str | None = None
    updated: str | None = None
    tags: list[str] = Field(default_factory=list)


class WorkflowDefinition(BaseModel):
    """Complete workflow definition."""

    name: str = Field(..., pattern=r"^[a-z][a-z0-9-]*$", min_length=2, max_length=64)
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    description: str | None = Field(default=None, max_length=500)
    triggers: WorkflowTriggers = Field(default_factory=WorkflowTriggers)
    inputs: dict[str, ParameterDef] = Field(default_factory=dict)
    outputs: dict[str, ParameterDef] = Field(default_factory=dict)
    steps: list[WorkflowStep] = Field(..., min_length=1)
    execution: WorkflowExecution = Field(default_factory=WorkflowExecution)
    metadata: WorkflowMetadata = Field(default_factory=WorkflowMetadata)

    @field_validator("steps")
    @classmethod
    def validate_unique_step_ids(cls, steps: list[WorkflowStep]) -> list[WorkflowStep]:
        """Ensure all step IDs are unique."""
        ids = [s.id for s in steps]
        if len(ids) != len(set(ids)):
            duplicates = [sid for sid in ids if ids.count(sid) > 1]
            raise ValueError(f"Duplicate step IDs: {set(duplicates)}")
        return steps

    @field_validator("steps")
    @classmethod
    def validate_depends_on_references(cls, steps: list[WorkflowStep]) -> list[WorkflowStep]:
        """Ensure depends_on references exist."""
        ids = {s.id for s in steps}
        for step in steps:
            for dep in step.depends_on:
                if dep not in ids:
                    raise ValueError(f"Step '{step.id}' depends on unknown step '{dep}'")
        return steps

    @classmethod
    def load_from_file(cls, path: str | Path) -> WorkflowDefinition:
        """Load a workflow definition from a JSON or YAML file."""
        file_path = Path(path)
        content = file_path.read_text(encoding="utf-8")

        if file_path.suffix in (".yaml", ".yml"):
            try:
                import yaml
            except ImportError as exc:
                raise ImportError("PyYAML is required to load YAML workflow files") from exc
            data = yaml.safe_load(content)
        else:
            data = json.loads(content)

        # Strip $schema key if present
        data.pop("$schema", None)
        return cls.model_validate(data)
