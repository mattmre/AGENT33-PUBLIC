"""Validation for the security audit checklist and dependency audit script."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHECKLIST_PATH = _REPO_ROOT / "docs" / "operators" / "security-audit-checklist.md"
_AUDIT_SCRIPT_PATH = _REPO_ROOT / "scripts" / "dependency-audit.sh"

# Sections that must appear in the checklist document.
_EXPECTED_SECTIONS = {
    "## Purpose",
    "## Dependency Audit",
    "### Python Dependencies",
    "### Docker Base Image",
    "### GitHub Actions",
    "## CI Security Scans",
    "### Targeted CVE Verification",
    "### GitGuardian",
    "## Audit Schedule",
    "## Referenced Files",
    "## Last Audit",
}

# Key strings the checklist must reference to ensure it stays
# grounded in the actual repo layout rather than becoming a
# generic template.
_EXPECTED_STRINGS = {
    "scripts/dependency-audit.sh",
    "scripts/verify_trivy_image.py",
    "engine/Dockerfile",
    "engine/pyproject.toml",
    "engine/uv.lock",
    ".github/workflows/security-scan.yml",
    ".github/dependabot.yml",
    "pip-audit",
    "CVE-2026-0861",
    "TODO(node24)",
    "production-deployment-runbook.md",
    "incident-response-playbooks.md",
    "python:3.11.13-slim-trixie",
    "trivy-fs",
    "trivy-image",
    "trivy-config",
    "trivy-secrets",
    "trivy-sarif",
}

# Files referenced by the checklist that must exist in the repo.
_REFERENCED_PATHS = [
    _REPO_ROOT / "engine" / "Dockerfile",
    _REPO_ROOT / "engine" / "pyproject.toml",
    _REPO_ROOT / ".github" / "workflows" / "security-scan.yml",
    _REPO_ROOT / ".github" / "dependabot.yml",
    _REPO_ROOT / "scripts" / "dependency-audit.sh",
    _REPO_ROOT / "scripts" / "verify_trivy_image.py",
    _REPO_ROOT / "docs" / "operators" / "production-deployment-runbook.md",
    _REPO_ROOT / "docs" / "operators" / "incident-response-playbooks.md",
]


def test_security_audit_checklist_exists() -> None:
    assert _CHECKLIST_PATH.exists(), f"Missing: {_CHECKLIST_PATH}"


def test_security_audit_checklist_has_expected_sections() -> None:
    content = _CHECKLIST_PATH.read_text(encoding="utf-8")
    for section in _EXPECTED_SECTIONS:
        assert section in content, f"Missing section: {section}"


def test_security_audit_checklist_references_real_artifacts() -> None:
    content = _CHECKLIST_PATH.read_text(encoding="utf-8")
    for expected in _EXPECTED_STRINGS:
        assert expected in content, f"Missing reference: {expected}"


def test_security_audit_checklist_referenced_files_exist() -> None:
    for path in _REFERENCED_PATHS:
        assert path.exists(), f"Referenced file missing: {path}"


def test_dependency_audit_script_exists_and_is_valid_shell() -> None:
    assert _AUDIT_SCRIPT_PATH.exists(), f"Missing: {_AUDIT_SCRIPT_PATH}"
    content = _AUDIT_SCRIPT_PATH.read_text(encoding="utf-8")
    # Verify it is a bash script with strict mode
    assert content.startswith("#!/usr/bin/env bash"), "Missing bash shebang"
    assert "set -euo pipefail" in content, "Missing strict mode"
    # Verify it invokes pip-audit
    assert "pip_audit" in content, "Script does not invoke pip_audit"
    # Verify it has an error path that exits non-zero
    assert "exit 1" in content, "Script has no failure exit path"


def test_dependency_audit_script_references_engine_directory() -> None:
    content = _AUDIT_SCRIPT_PATH.read_text(encoding="utf-8")
    # The script must cd into the engine directory
    assert "engine" in content, "Script does not reference engine directory"
