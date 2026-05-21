"""Setup diagnostics contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SetupDiagnosticStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class SetupDiagnosticCheck(BaseModel):
    check_id: str
    status: SetupDiagnosticStatus
    owner: str = ""
    fix_action: str = ""
    evidence_uri: str = ""


class SetupDiagnosticReport(BaseModel):
    counts: dict[SetupDiagnosticStatus, int]
    required_actions: list[str] = Field(default_factory=list)
    evidence_uris: list[str] = Field(default_factory=list)


def summarize_setup_diagnostics(
    checks: list[SetupDiagnosticCheck],
) -> dict[SetupDiagnosticStatus, int]:
    return {
        status: sum(1 for check in checks if check.status == status)
        for status in SetupDiagnosticStatus
    }


def build_setup_diagnostic_report(checks: list[SetupDiagnosticCheck]) -> SetupDiagnosticReport:
    return SetupDiagnosticReport(
        counts=summarize_setup_diagnostics(checks),
        required_actions=[
            check.fix_action
            for check in checks
            if check.status != SetupDiagnosticStatus.PASS and check.fix_action
        ],
        evidence_uris=[check.evidence_uri for check in checks if check.evidence_uri],
    )
