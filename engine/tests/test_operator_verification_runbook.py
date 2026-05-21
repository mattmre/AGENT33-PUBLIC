"""Doc regression tests for AEP-20260328-M01.

Ensures the operator verification runbook retains accurate scope guidance:
 - Process inventory requires the ``processes:read`` scope.
 - Reset requires ``operator:write`` (or broader ``admin``).
 - Read-only and elevated tokens are visually separated so operators do not
   conflate them.
"""

from __future__ import annotations

from pathlib import Path


def _runbook_text() -> str:
    path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "operators"
        / "operator-verification-runbook.md"
    )
    return path.read_text(encoding="utf-8")


def test_runbook_documents_processes_read_scope() -> None:
    """AEP-20260328-M01: processes:read must be listed as a required scope."""
    assert "processes:read" in _runbook_text()


def test_runbook_documents_operator_write_for_reset() -> None:
    """AEP-20260328-M01: reset path must state it requires operator:write (or admin)."""
    text = _runbook_text()
    assert "operator:write" in text


def test_runbook_separates_read_and_elevated_tokens() -> None:
    """AEP-20260328-M01: runbook must use separate token variables, not one $TOKEN."""
    text = _runbook_text()
    # Must distinguish at minimum between a read-only token and an elevated token
    assert "$READ_TOKEN" in text
    assert "$RESET_TOKEN" in text or "$RESTORE_TOKEN" in text


def test_runbook_scope_section_present() -> None:
    """AEP-20260328-M01: a dedicated required-scopes section must exist."""
    text = _runbook_text()
    assert "Required Scopes" in text or "required scopes" in text.lower()
