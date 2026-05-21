"""Validation for the pricing and effort operator runbook."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNBOOK_PATH = _REPO_ROOT / "docs" / "operators" / "pricing-and-effort-runbook.md"
_EXPECTED_SECTIONS = {
    "## Purpose",
    "## MCP Inspection Surface",
    "## Pricing Catalog Contract",
    "## Effort Heuristic Contract",
    "## Verification Steps",
    "## Fast-Path Spot Check",
    "## Escalation Guidance",
}
_EXPECTED_STRINGS = {
    "agent33://pricing-catalog",
    "component-security:read",
    "catalog_snapshot_fetched_at",
    "override_count",
    "official_docs_snapshot",
    "pricing_catalog_overrides",
    "simple_message_fast_path",
    "flat_rate_fallback_cost_per_1k_tokens",
    "estimated_cost_source",
    "/v1/agents/{id}/invoke",
    "gpt-4.1",
    "llama3.2",
    "service-level-objectives.md",
}
_REFERENCED_PATHS = [
    _REPO_ROOT / "docs" / "operators" / "production-deployment-runbook.md",
    _REPO_ROOT / "docs" / "operators" / "operator-verification-runbook.md",
    _REPO_ROOT / "docs" / "operators" / "service-level-objectives.md",
]


def test_pricing_and_effort_runbook_has_expected_sections_and_content() -> None:
    content = _RUNBOOK_PATH.read_text(encoding="utf-8")

    for section in _EXPECTED_SECTIONS:
        assert section in content, section

    for expected in _EXPECTED_STRINGS:
        assert expected in content, expected


def test_pricing_and_effort_runbook_references_files_that_exist() -> None:
    content = _RUNBOOK_PATH.read_text(encoding="utf-8")

    for path in _REFERENCED_PATHS:
        assert path.exists(), path
        assert path.name in content
