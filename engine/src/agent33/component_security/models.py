"""Domain models for component security scans."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def _new_run_id() -> str:
    return f"secrun-{uuid.uuid4().hex[:12]}"


def _new_finding_id() -> str:
    return f"finding-{uuid.uuid4().hex[:12]}"


class SecurityProfile(StrEnum):
    """Supported scan profiles."""

    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"


class RunStatus(StrEnum):
    """Lifecycle state for a security run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class FindingSeverity(StrEnum):
    """Normalized finding severity."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingCategory(StrEnum):
    """Normalized finding category."""

    DEPENDENCY_VULNERABILITY = "dependency-vulnerability"
    SECRETS_EXPOSURE = "secrets-exposure"
    INJECTION_RISK = "injection-risk"
    CODE_QUALITY = "code-quality"
    AUTHENTICATION_WEAKNESS = "authentication-weakness"
    AUTHORIZATION_BYPASS = "authorization-bypass"
    CRYPTOGRAPHY_WEAKNESS = "cryptography-weakness"
    CONFIGURATION_ISSUE = "configuration-issue"
    PROMPT_INJECTION = "prompt-injection"
    TOOL_POISONING = "tool-poisoning"
    SUPPLY_CHAIN = "supply-chain"
    MODEL_SECURITY = "model-security"


class ScanTarget(BaseModel):
    """Repository target for component security scanning."""

    repository_path: str
    commit_ref: str = ""
    branch: str = ""


class ScanOptions(BaseModel):
    """Execution options for a component security run."""

    timeout_seconds: int = Field(default=600, ge=30, le=3600)
    fail_on_high: bool = True
    scan_dependencies: bool = True
    scan_secrets: bool = True


class RunMetadata(BaseModel):
    """Audit metadata associated with a security run."""

    requested_by: str = ""
    session_id: str = ""
    release_candidate_id: str = ""
    tools_executed: list[str] = Field(default_factory=list)
    tool_warnings: list[str] = Field(default_factory=list)


class SecurityFinding(BaseModel):
    """Normalized finding produced by scanner integrations."""

    id: str = Field(default_factory=_new_finding_id)
    run_id: str
    severity: FindingSeverity
    category: FindingCategory
    title: str
    description: str
    tool: str
    file_path: str = ""
    line_number: int | None = None
    remediation: str = ""
    cwe_id: str = ""
    cvss_score: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FindingsSummary(BaseModel):
    """Finding counters grouped by severity."""

    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0

    @property
    def total(self) -> int:
        """Return total findings across all severities."""
        return self.critical + self.high + self.medium + self.low + self.info

    @classmethod
    def from_findings(cls, findings: list[SecurityFinding]) -> FindingsSummary:
        """Build summary counts from findings."""
        summary = cls()
        for finding in findings:
            match finding.severity:
                case FindingSeverity.CRITICAL:
                    summary.critical += 1
                case FindingSeverity.HIGH:
                    summary.high += 1
                case FindingSeverity.MEDIUM:
                    summary.medium += 1
                case FindingSeverity.LOW:
                    summary.low += 1
                case FindingSeverity.INFO:
                    summary.info += 1
        return summary


class SecurityRun(BaseModel):
    """Security run record and execution status."""

    id: str = Field(default_factory=_new_run_id)
    tenant_id: str = ""
    profile: SecurityProfile = SecurityProfile.QUICK
    status: RunStatus = RunStatus.PENDING
    target: ScanTarget
    options: ScanOptions = Field(default_factory=ScanOptions)
    metadata: RunMetadata = Field(default_factory=RunMetadata)
    findings_count: int = 0
    findings_summary: FindingsSummary = Field(default_factory=FindingsSummary)
    error_message: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def duration_seconds(self) -> int:
        """Return run duration in seconds when start/end are available."""
        if self.started_at is None or self.completed_at is None:
            return 0
        return int((self.completed_at - self.started_at).total_seconds())

    def touch(self) -> None:
        """Refresh last-updated timestamp."""
        self.updated_at = datetime.now(UTC)


class SecurityGatePolicy(BaseModel):
    """Configurable policy for release gate decisions."""

    block_on_critical: bool = True
    block_on_high: bool = True
    max_high: int = 0
    max_medium: int = 10


class SecurityGateDecision(StrEnum):
    """Outcome of evaluating a run against gate policy."""

    PASS = "pass"
    FAIL = "fail"


class SecurityGateResult(BaseModel):
    """Result of release security gate policy evaluation."""

    decision: SecurityGateDecision
    message: str
    run_id: str
    summary: FindingsSummary
