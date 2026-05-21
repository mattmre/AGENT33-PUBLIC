"""Hook framework data models: event types, contexts, results, and definitions."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Event Taxonomy
# ---------------------------------------------------------------------------


class HookEventType(StrEnum):
    """Supported hook event types (Phase 1 scope)."""

    # Agent lifecycle
    AGENT_INVOKE_PRE = "agent.invoke.pre"
    AGENT_INVOKE_POST = "agent.invoke.post"

    # Tool execution
    TOOL_EXECUTE_PRE = "tool.execute.pre"
    TOOL_EXECUTE_POST = "tool.execute.post"

    # Workflow step execution
    WORKFLOW_STEP_PRE = "workflow.step.pre"
    WORKFLOW_STEP_POST = "workflow.step.post"

    # Request lifecycle (HTTP layer)
    REQUEST_PRE = "request.pre"
    REQUEST_POST = "request.post"

    # CLI session lifecycle (Phase 44)
    SESSION_START = "session.start"
    SESSION_END = "session.end"
    SESSION_CHECKPOINT = "session.checkpoint"
    SESSION_RESUME = "session.resume"


# ---------------------------------------------------------------------------
# Context Dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(slots=True)
class HookContext:
    """Base context passed through hook chains."""

    event_type: str
    tenant_id: str
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)
    abort: bool = False
    abort_reason: str = ""
    results: list[HookResult] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(slots=True)
class AgentHookContext(HookContext):
    """Context for agent.invoke.pre and agent.invoke.post hooks."""

    agent_name: str = ""
    agent_definition: Any | None = None  # AgentDefinition (avoid circular import)
    inputs: dict[str, Any] = dataclasses.field(default_factory=dict)
    system_prompt: str = ""
    model: str = ""
    result: Any | None = None  # AgentResult, populated in post hooks
    duration_ms: float = 0.0  # populated in post hooks


@dataclasses.dataclass(slots=True)
class ToolHookContext(HookContext):
    """Context for tool.execute.pre and tool.execute.post hooks."""

    tool_name: str = ""
    arguments: dict[str, Any] = dataclasses.field(default_factory=dict)
    tool_context: Any | None = None  # ToolContext
    result: Any | None = None  # ToolResult, populated in post hooks
    duration_ms: float = 0.0  # populated in post hooks


@dataclasses.dataclass(slots=True)
class WorkflowHookContext(HookContext):
    """Context for workflow.step.pre and workflow.step.post hooks."""

    workflow_name: str = ""
    step_id: str = ""
    step_action: str = ""
    inputs: dict[str, Any] = dataclasses.field(default_factory=dict)
    state: dict[str, Any] = dataclasses.field(default_factory=dict)
    result: Any | None = None  # StepResult, populated in post hooks
    duration_ms: float = 0.0  # populated in post hooks


@dataclasses.dataclass(slots=True)
class RequestHookContext(HookContext):
    """Context for request.pre and request.post hooks."""

    method: str = ""
    path: str = ""
    headers: dict[str, str] = dataclasses.field(default_factory=dict)
    body: bytes = b""
    status_code: int = 0  # populated in post hooks
    response_headers: dict[str, str] = dataclasses.field(default_factory=dict)
    duration_ms: float = 0.0  # populated in post hooks


# ---------------------------------------------------------------------------
# Result Models
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class HookResult:
    """Result of a single hook execution within a chain."""

    hook_name: str
    success: bool
    data: dict[str, Any] = dataclasses.field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0.0


@dataclasses.dataclass(frozen=True, slots=True)
class HookChainResult:
    """Aggregated result of running a full hook chain."""

    event_type: str
    hook_results: list[HookResult]
    aborted: bool = False
    abort_reason: str = ""
    total_duration_ms: float = 0.0

    @property
    def all_succeeded(self) -> bool:
        return all(r.success for r in self.hook_results)

    @property
    def hook_count(self) -> int:
        return len(self.hook_results)


# ---------------------------------------------------------------------------
# Persistent Models (Pydantic)
# ---------------------------------------------------------------------------


class HookDefinition(BaseModel):
    """Persistent hook configuration stored in DB or loaded from YAML."""

    hook_id: str = Field(default_factory=lambda: f"hook_{uuid4().hex[:12]}")
    name: str
    description: str = ""
    event_type: HookEventType
    priority: int = Field(default=100, ge=0, le=1000)
    handler_ref: str  # dotted Python path or plugin identifier
    timeout_ms: float = Field(default=200.0, gt=0, le=5000)
    enabled: bool = True
    tenant_id: str = ""  # "" = system hook
    config: dict[str, Any] = Field(default_factory=dict)
    fail_mode: Literal["open", "closed"] = "open"
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class HookExecutionLog(BaseModel):
    """Persisted record of a hook chain execution."""

    log_id: str = Field(default_factory=lambda: uuid4().hex)
    event_type: str
    tenant_id: str
    hook_results: list[dict[str, Any]]
    aborted: bool = False
    abort_reason: str = ""
    total_duration_ms: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    request_id: str = ""  # correlation ID
