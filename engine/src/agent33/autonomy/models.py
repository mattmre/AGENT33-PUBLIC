"""Data models for autonomy budgets, policies, and enforcement.

Implements the spec from ``core/orchestrator/AUTONOMY_ENFORCEMENT.md``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class BudgetState(StrEnum):
    """Lifecycle states for an autonomy budget."""

    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    COMPLETED = "completed"
    REJECTED = "rejected"


class StopAction(StrEnum):
    """Action to take when a stop condition triggers."""

    STOP = "stop"
    ESCALATE = "escalate"
    WARN = "warn"


class EscalationUrgency(StrEnum):
    """Urgency level for escalation triggers."""

    IMMEDIATE = "immediate"
    NORMAL = "normal"
    LOW = "low"


class PolicyAction(StrEnum):
    """Action a policy rule can take."""

    ALLOW = "allow"
    BLOCK = "block"
    WARN = "warn"
    ESCALATE = "escalate"
    STOP = "stop"


class EnforcementResult(StrEnum):
    """Result of an enforcement check."""

    ALLOWED = "allowed"
    BLOCKED = "blocked"
    WARNED = "warned"
    ESCALATED = "escalated"


class PreflightStatus(StrEnum):
    """Status of a preflight check."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


# ---------------------------------------------------------------------------
# Budget sub-models
# ---------------------------------------------------------------------------


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class FileScope(BaseModel):
    """File access scope within a budget."""

    read: list[str] = Field(default_factory=list)
    write: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class CommandPermission(BaseModel):
    """A single command permission entry."""

    command: str
    args_pattern: str = ""
    max_calls: int = 0  # 0 = unlimited


class NetworkScope(BaseModel):
    """Network access scope within a budget."""

    enabled: bool = False
    allowed_domains: list[str] = Field(default_factory=list)
    denied_domains: list[str] = Field(default_factory=list)
    max_requests: int = 0  # 0 = unlimited


class ResourceLimits(BaseModel):
    """Resource consumption limits."""

    max_iterations: int = 100
    max_duration_minutes: int = 60
    max_files_modified: int = 50
    max_lines_changed: int = 5000
    max_tool_calls: int = 200


class StopCondition(BaseModel):
    """A stop condition that triggers an action."""

    condition_id: str = ""
    description: str
    action: StopAction = StopAction.STOP


class EscalationTrigger(BaseModel):
    """An escalation trigger with target and urgency."""

    trigger_id: str = ""
    description: str
    target: str = "orchestrator"
    urgency: EscalationUrgency = EscalationUrgency.NORMAL


# ---------------------------------------------------------------------------
# Main budget model
# ---------------------------------------------------------------------------


class AutonomyBudget(BaseModel):
    """Full autonomy budget for a task or agent."""

    budget_id: str = Field(default_factory=lambda: _new_id("BDG"))
    task_id: str = ""
    agent_id: str = ""
    state: BudgetState = BudgetState.DRAFT

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    approved_by: str = ""

    # Scope
    in_scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    files: FileScope = Field(default_factory=FileScope)

    # Commands
    allowed_commands: list[CommandPermission] = Field(default_factory=list)
    denied_commands: list[str] = Field(default_factory=list)
    require_approval_commands: list[str] = Field(default_factory=list)

    # Network
    network: NetworkScope = Field(default_factory=NetworkScope)

    # Limits
    limits: ResourceLimits = Field(default_factory=ResourceLimits)

    # Stop conditions
    stop_conditions: list[StopCondition] = Field(default_factory=list)

    # Escalation
    escalation_triggers: list[EscalationTrigger] = Field(default_factory=list)
    default_escalation_target: str = "orchestrator"


# ---------------------------------------------------------------------------
# Enforcement tracking
# ---------------------------------------------------------------------------


class EnforcementContext(BaseModel):
    """Tracks resource consumption during a budget-scoped execution."""

    budget_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    iterations: int = 0
    tool_calls: int = 0
    files_modified: int = 0
    lines_changed: int = 0
    network_requests: int = 0

    warnings: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    stopped: bool = False
    stop_reason: str = ""

    def record_iteration(self) -> None:
        self.iterations += 1

    def record_tool_call(self) -> None:
        self.tool_calls += 1

    def record_file_modified(self, lines: int = 0) -> None:
        self.files_modified += 1
        self.lines_changed += lines

    def record_network_request(self) -> None:
        self.network_requests += 1

    def elapsed_minutes(self) -> float:
        delta = datetime.now(UTC) - self.started_at
        return delta.total_seconds() / 60.0

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def add_violation(self, msg: str) -> None:
        self.violations.append(msg)

    def mark_stopped(self, reason: str) -> None:
        self.stopped = True
        self.stop_reason = reason


# ---------------------------------------------------------------------------
# Preflight result
# ---------------------------------------------------------------------------


class PreflightCheck(BaseModel):
    """Result of a single preflight check."""

    check_id: str  # PF-01 .. PF-10
    name: str
    status: PreflightStatus = PreflightStatus.PASS
    message: str = ""


class PreflightReport(BaseModel):
    """Complete preflight check report."""

    budget_id: str
    overall: PreflightStatus = PreflightStatus.PASS
    checks: list[PreflightCheck] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Escalation record
# ---------------------------------------------------------------------------


class EscalationRecord(BaseModel):
    """Record of a triggered escalation."""

    escalation_id: str = Field(default_factory=lambda: _new_id("ESC"))
    budget_id: str = ""
    trigger_description: str = ""
    target: str = ""
    urgency: EscalationUrgency = EscalationUrgency.NORMAL
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    acknowledged: bool = False
    resolved: bool = False
