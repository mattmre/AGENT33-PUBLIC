"""Unified Doctor Center status projection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from agent33.operator.models import CheckStatus, DiagnosticCheck, DiagnosticResult

DoctorSeverity = Literal["ok", "warning", "error"]
DoctorActionType = Literal["none", "navigate", "rerun", "docs"]


@dataclass(frozen=True)
class DoctorFinding:
    id: str
    category: str
    severity: DoctorSeverity
    owner: str
    message: str
    fix_action: str
    action_type: DoctorActionType
    action_target: str
    stale_age_seconds: int
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DoctorStatus:
    overall: DoctorSeverity
    generated_at: datetime
    findings: tuple[DoctorFinding, ...]


_OWNER_BY_CATEGORY = {
    "database": "setup",
    "redis": "automation",
    "nats": "automation",
    "llm": "models",
    "agents": "automation",
    "skills": "resources",
    "plugins": "resources",
    "packs": "resources",
    "security": "security",
    "config": "setup",
    "sessions": "automation",
    "hooks": "automation",
    "scheduler": "automation",
    "mcp": "tools",
    "voice": "integrations",
    "backup": "setup",
}

_ACTION_TARGET_BY_OWNER = {
    "setup": "setup",
    "models": "models",
    "tools": "mcp",
    "resources": "tools",
    "automation": "operations",
    "security": "safety",
    "integrations": "setup",
}


def _severity(status: CheckStatus) -> DoctorSeverity:
    if status == CheckStatus.ERROR:
        return "error"
    if status == CheckStatus.WARNING:
        return "warning"
    return "ok"


def _owner(category: str) -> str:
    return _OWNER_BY_CATEGORY.get(category, "setup")


def _fix_action(check: DiagnosticCheck) -> str:
    if check.remediation:
        return check.remediation
    if check.status == CheckStatus.OK:
        return "No action required."
    return f"Open the {check.category} setup surface and rerun Doctor Center."


def _action_type(check: DiagnosticCheck) -> DoctorActionType:
    if check.status == CheckStatus.OK:
        return "none"
    if check.remediation:
        return "navigate"
    return "rerun"


def _action_target(check: DiagnosticCheck) -> str:
    if check.status == CheckStatus.OK:
        return ""
    return _ACTION_TARGET_BY_OWNER.get(_owner(check.category), "setup")


def _evidence_ref(check: DiagnosticCheck) -> str:
    return f"doctor:{check.id}:{check.category}"


def build_doctor_status(result: DiagnosticResult) -> DoctorStatus:
    """Convert operator diagnostics into the Doctor Center contract."""
    findings = tuple(
        DoctorFinding(
            id=check.id,
            category=check.category,
            severity=_severity(check.status),
            owner=_owner(check.category),
            message=check.message,
            fix_action=_fix_action(check),
            action_type=_action_type(check),
            action_target=_action_target(check),
            stale_age_seconds=0,
            evidence_refs=(_evidence_ref(check),),
        )
        for check in result.checks
    )
    generated_at = (
        result.timestamp if result.timestamp.tzinfo else result.timestamp.replace(tzinfo=UTC)
    )
    return DoctorStatus(
        overall=_severity(result.overall),
        generated_at=generated_at,
        findings=findings,
    )
