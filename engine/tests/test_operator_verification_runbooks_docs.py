"""Validation for the operator verification and process-registry runbooks."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROCESS_RUNBOOK = _REPO_ROOT / "docs" / "operators" / "process-registry-runbook.md"
_VERIFICATION_RUNBOOK = _REPO_ROOT / "docs" / "operators" / "operator-verification-runbook.md"

_PROCESS_SECTIONS = {
    "## Purpose",
    "## Current Contract",
    "## Canonical Inventory Command",
    "## Lifecycle Verification",
    "## Recovery After Restart",
    "## Bounded Cleanup",
    "## Escalate When",
}
_PROCESS_STRINGS = {
    "/v1/processes",
    "/v1/processes/{process_id}",
    "/v1/processes/{process_id}/log",
    "/v1/processes/{process_id}/write",
    "/v1/processes/cleanup",
    "processes:read",
    "processes:manage",
    "tool governance",
    "status_filter=interrupted",
    "interrupted",
    "redacted command",
    "prefix...suffix",
    "processes.py",
    "service.py",
}
_PROCESS_REFERENCED_PATHS = [
    _REPO_ROOT / "docs" / "operators" / "operator-verification-runbook.md",
    _REPO_ROOT / "docs" / "operators" / "production-deployment-runbook.md",
    _REPO_ROOT / "docs" / "operators" / "incident-response-playbooks.md",
    _REPO_ROOT / "engine" / "src" / "agent33" / "api" / "routes" / "processes.py",
    _REPO_ROOT / "engine" / "src" / "agent33" / "processes" / "service.py",
]

_VERIFICATION_SECTIONS = {
    "## Purpose",
    "## Required Scopes",
    "## Canonical Verification Order",
    "## Operator Control Plane Check",
    "## Process Registry Check",
    "## Backup Verification Check",
    "## Bounded Reset Path",
    "## Escalate When",
}
_VERIFICATION_STRINGS = {
    "/v1/operator/status",
    "/v1/operator/doctor",
    "/v1/operator/reset",
    "/v1/processes?limit=50",
    "/v1/backups/inventory",
    "/v1/backups",
    "/v1/backups/$BACKUP_ID/verify",
    "/v1/backups/$BACKUP_ID/restore-plan",
    "/v1/backups/$BACKUP_ID/restore",
    "$RESTORE_TOKEN",
    '"confirm":true',
    '"allow_overwrite":true',
    "restore-plan output",
    "process-registry-runbook.md",
    "operator.py",
    "backups.py",
    "operator:read",
    "processes:read",
    "operator:write",
    "admin",
    "$READ_TOKEN",
    "$RESET_TOKEN",
}
_VERIFICATION_REFERENCED_PATHS = [
    _REPO_ROOT / "docs" / "operators" / "production-deployment-runbook.md",
    _REPO_ROOT / "docs" / "operators" / "incident-response-playbooks.md",
    _REPO_ROOT / "docs" / "operators" / "process-registry-runbook.md",
    _REPO_ROOT / "engine" / "src" / "agent33" / "api" / "routes" / "operator.py",
    _REPO_ROOT / "engine" / "src" / "agent33" / "api" / "routes" / "backups.py",
]


def _assert_runbook(
    path: Path,
    *,
    expected_sections: set[str],
    expected_strings: set[str],
    referenced_paths: list[Path],
) -> None:
    content = path.read_text(encoding="utf-8")
    for section in expected_sections:
        assert section in content, section
    for expected in expected_strings:
        assert expected in content, expected
    for referenced_path in referenced_paths:
        assert referenced_path.exists(), referenced_path


def test_process_registry_runbook_has_expected_sections_commands_and_paths() -> None:
    _assert_runbook(
        _PROCESS_RUNBOOK,
        expected_sections=_PROCESS_SECTIONS,
        expected_strings=_PROCESS_STRINGS,
        referenced_paths=_PROCESS_REFERENCED_PATHS,
    )


def test_operator_verification_runbook_has_expected_sections_commands_and_paths() -> None:
    _assert_runbook(
        _VERIFICATION_RUNBOOK,
        expected_sections=_VERIFICATION_SECTIONS,
        expected_strings=_VERIFICATION_STRINGS,
        referenced_paths=_VERIFICATION_REFERENCED_PATHS,
    )
