"""Validation for the connector boundary runbook."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNBOOK_PATH = _REPO_ROOT / "docs" / "operators" / "connector-boundary-runbook.md"
_EXPECTED_SECTIONS = {
    "## Purpose",
    "## Middleware Order",
    "## Current Breaker Policy",
    "## Retry Semantics",
    "## Verification Steps",
    "## How To Read Open Circuits",
    "## Recovery Guidance",
}
_EXPECTED_STRINGS = {
    "production-deployment-runbook.md",
    "service-level-objectives.md",
    "incident-response-playbooks.md",
    "/v1/connectors",
    "/v1/connectors/{connector_id}/events",
    "connector_circuit_failure_threshold=3",
    "connector_circuit_recovery_seconds=30.0",
    "connector_circuit_half_open_successes=2",
    "connector_circuit_max_recovery_seconds=300.0",
    "no automatic retry unless a caller opts into",
    "retry_attempts > 1",
    "cooldown_remaining_seconds",
    "effective_recovery_timeout_seconds",
    "max_recovery_timeout_seconds",
}
_REFERENCED_PATHS = [
    _REPO_ROOT / "docs" / "operators" / "production-deployment-runbook.md",
    _REPO_ROOT / "docs" / "operators" / "service-level-objectives.md",
    _REPO_ROOT / "docs" / "operators" / "incident-response-playbooks.md",
]


def test_connector_boundary_runbook_has_expected_sections_and_content() -> None:
    content = _RUNBOOK_PATH.read_text(encoding="utf-8")

    for section in _EXPECTED_SECTIONS:
        assert section in content, section

    for expected in _EXPECTED_STRINGS:
        assert expected in content, expected


def test_connector_boundary_runbook_references_files_that_exist() -> None:
    content = _RUNBOOK_PATH.read_text(encoding="utf-8")

    for path in _REFERENCED_PATHS:
        assert path.exists(), path
        assert path.name in content
