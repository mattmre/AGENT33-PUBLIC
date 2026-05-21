"""Trace models matching ``core/orchestrator/TRACE_SCHEMA.md``.

Provides Pydantic models for the trace hierarchy:
Session → Run → Task → Step → Action
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# ID generators
# ---------------------------------------------------------------------------


def _trace_id(prefix: str = "TRC") -> str:
    now = datetime.now(UTC)
    rand = uuid.uuid4().hex[:4].upper()
    return f"{prefix}-{now:%Y%m%d-%H%M%S}-{rand}"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TraceStatus(StrEnum):
    """Outcome status for a trace record."""

    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    ESCALATED = "escalated"
    RUNNING = "running"


class ActionStatus(StrEnum):
    """Status of a single action within a step."""

    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class ArtifactType(StrEnum):
    """Types of artifacts produced during execution."""

    LOG = "LOG"
    OUT = "OUT"
    DIF = "DIF"
    TST = "TST"
    REV = "REV"
    EVD = "EVD"
    SES = "SES"
    CFG = "CFG"
    TMP = "TMP"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class TraceAction(BaseModel):
    """A single tool call or operation within a step."""

    action_id: str = ""
    tool: str = ""
    input: str = ""
    output: str = ""
    exit_code: int | None = None
    duration_ms: int = 0
    status: ActionStatus = ActionStatus.SUCCESS


class TraceStep(BaseModel):
    """A numbered step within a task."""

    step_id: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    actions: list[TraceAction] = Field(default_factory=list)


class TraceContext(BaseModel):
    """Execution context for a trace."""

    agent_id: str = ""
    agent_role: str = ""
    model: str = ""
    branch: str = ""
    commit: str = ""
    working_directory: str = ""


class TraceInput(BaseModel):
    """Input data for a trace."""

    prompt: str = ""
    parameters: dict[str, str] = Field(default_factory=dict)
    files_read: list[str] = Field(default_factory=list)
    context_loaded: list[str] = Field(default_factory=list)


class TraceOutput(BaseModel):
    """Output data from a trace."""

    result: str = ""
    files_written: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    artifacts_created: list[str] = Field(default_factory=list)


class TraceOutcome(BaseModel):
    """Final outcome of a trace."""

    status: TraceStatus = TraceStatus.RUNNING
    failure_code: str = ""
    failure_message: str = ""
    failure_category: str = ""


class TraceEvidence(BaseModel):
    """Links to evidence artifacts."""

    verification_log_ref: str = ""
    evidence_capture_ref: str = ""
    session_log_ref: str = ""
    review_signoff_ref: str = ""


class TraceMetadata(BaseModel):
    """Trace metadata for linking and tagging."""

    tags: list[str] = Field(default_factory=list)
    annotations: dict[str, str] = Field(default_factory=dict)
    parent_trace: str = ""
    child_traces: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level trace record
# ---------------------------------------------------------------------------


class TraceRecord(BaseModel):
    """Full trace record matching TRACE_SCHEMA.md."""

    trace_id: str = Field(default_factory=_trace_id)
    session_id: str = ""
    run_id: str = ""
    task_id: str = ""
    tenant_id: str = ""

    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_ms: int = 0

    context: TraceContext = Field(default_factory=TraceContext)
    input: TraceInput = Field(default_factory=TraceInput)
    execution: list[TraceStep] = Field(default_factory=list)
    output: TraceOutput = Field(default_factory=TraceOutput)
    outcome: TraceOutcome = Field(default_factory=TraceOutcome)
    evidence: TraceEvidence = Field(default_factory=TraceEvidence)
    metadata: TraceMetadata = Field(default_factory=TraceMetadata)

    def complete(
        self,
        status: TraceStatus = TraceStatus.COMPLETED,
        failure_code: str = "",
        failure_message: str = "",
    ) -> None:
        """Mark the trace as completed and compute duration."""
        self.completed_at = datetime.now(UTC)
        self.duration_ms = int((self.completed_at - self.started_at).total_seconds() * 1000)
        self.outcome.status = status
        if failure_code:
            self.outcome.failure_code = failure_code
        if failure_message:
            self.outcome.failure_message = failure_message
