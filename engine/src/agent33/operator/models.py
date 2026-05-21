"""Pydantic models for the operator control plane."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agent33.backup.manifest import BackupSummary  # noqa: TC001

# ---------------------------------------------------------------------------
# Health / status
# ---------------------------------------------------------------------------


class HealthStatus(StrEnum):
    """Overall system health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class SubsystemInventory(BaseModel):
    """Inventory count for a single subsystem."""

    count: int = 0
    loaded: bool = False
    active: int | None = None
    enabled: int | None = None


class RuntimeInfo(BaseModel):
    """Static runtime metadata."""

    version: str = "0.1.0"
    python_version: str = ""
    uptime_seconds: float = 0.0
    start_time: datetime | None = None


class PendingItems(BaseModel):
    """Outstanding items requiring operator attention."""

    approvals: int = 0
    reviews: int = 0
    improvements: int = 0


class SystemStatus(BaseModel):
    """Aggregated system status returned by GET /v1/operator/status."""

    health: dict[str, Any] = Field(default_factory=dict)
    inventories: dict[str, SubsystemInventory] = Field(default_factory=dict)
    runtime: RuntimeInfo = Field(default_factory=RuntimeInfo)
    pending: PendingItems = Field(default_factory=PendingItems)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class OperatorConfig(BaseModel):
    """Redacted runtime configuration grouped by subsystem."""

    groups: dict[str, dict[str, Any]] = Field(default_factory=dict)
    feature_flags: dict[str, bool] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Doctor / diagnostics
# ---------------------------------------------------------------------------


class CheckStatus(StrEnum):
    """Severity level for a diagnostic check."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


class DiagnosticCheck(BaseModel):
    """Result of a single diagnostic check."""

    id: str
    category: str
    status: CheckStatus
    message: str
    remediation: str | None = None


class DiagnosticResult(BaseModel):
    """Aggregated diagnostic results from GET /v1/operator/doctor."""

    overall: CheckStatus = CheckStatus.OK
    checks: list[DiagnosticCheck] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class ResetTarget(StrEnum):
    """Targets that can be reset by the operator."""

    CACHES = "caches"
    REGISTRIES = "registries"
    ALL = "all"


class ResetRequest(BaseModel):
    """Request body for POST /v1/operator/reset."""

    targets: list[ResetTarget] = Field(default_factory=lambda: [ResetTarget.ALL])


class ResetAction(BaseModel):
    """Single action performed during a reset."""

    target: str
    success: bool
    detail: str = ""


class ResetResult(BaseModel):
    """Report from a reset operation."""

    actions: list[ResetAction] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Tool summary
# ---------------------------------------------------------------------------


class ToolSummaryItem(BaseModel):
    """Lightweight tool info for operator listing."""

    name: str
    source: str = "builtin"
    status: str = "active"
    has_schema: bool = False


class ToolSummaryResponse(BaseModel):
    """Response for GET /v1/operator/tools/summary."""

    tools: list[ToolSummaryItem] = Field(default_factory=list)
    count: int = 0
    note: str = "Full catalog with grouping, provenance, and availability coming in Track Phase 2"


# ---------------------------------------------------------------------------
# Session catalog
# ---------------------------------------------------------------------------


class SessionSummary(BaseModel):
    """Lightweight session info for operator listing."""

    session_id: str
    type: str = "chat"
    status: str = "active"
    agent: str = ""
    started_at: datetime | None = None
    last_activity: datetime | None = None
    message_count: int = 0
    tenant_id: str = ""


class SessionListResponse(BaseModel):
    """Response for GET /v1/operator/sessions."""

    sessions: list[SessionSummary] = Field(default_factory=list)
    count: int = 0
    total: int = 0
    degraded: bool = False


# ---------------------------------------------------------------------------
# Backup catalog
# ---------------------------------------------------------------------------


class BackupListResponse(BaseModel):
    """Response for GET /v1/operator/backups."""

    backups: list[BackupSummary] = Field(default_factory=list)
    count: int = 0
    note: str = "Platform backup inventory is available under /v1/backups"
