"""Validation for the production service-level-objectives doc."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OBJECTIVES_PATH = _REPO_ROOT / "docs" / "operators" / "service-level-objectives.md"
_EXPECTED_SECTIONS = {
    "## Purpose",
    "## SLA, SLO, and SLI Boundary",
    "## Current Measurable Objective Baseline",
    "## Formal Objective",
    "## Error Budget Policy",
    "## Operational Guardrails",
    "## Deferred Objectives",
    "## Threshold Map",
    "## Validation Sequence",
}
_EXPECTED_STRINGS = {
    "incident-response-playbooks.md",
    "production-deployment-runbook.md",
    "deploy/monitoring/README.md",
    "deploy/monitoring/prometheus/agent33-alerts.rules.yaml",
    "There is no external customer SLA defined in this repo today.",
    "effort_routing_export_failures_total",
    "effort_routing_high_effort_total",
    "effort_routing_decisions_total",
    "effort_routing_estimated_cost_usd_avg",
    "effort_routing_estimated_token_budget_avg",
    "agent33:sli:effort_telemetry_export_failures:count_28d",
    "agent33:sli:high_effort_routing_ratio:ratio_15m",
    "agent33:sli:estimated_cost_usd_avg:max",
    "at least `28d`",
    "process-lifetime averages",
    "persistent estimated cost lifetime-average elevation",
    "/metrics",
    "/v1/dashboard/alerts",
    "API availability success rate",
    "request latency",
    "evaluation regression rate",
    "webhook backlog / dead-letter rate",
    "connector fleet reliability",
}
_REFERENCED_PATHS = [
    _REPO_ROOT / "docs" / "operators" / "incident-response-playbooks.md",
    _REPO_ROOT / "docs" / "operators" / "production-deployment-runbook.md",
    _REPO_ROOT / "deploy" / "monitoring" / "README.md",
    _REPO_ROOT / "deploy" / "monitoring" / "prometheus" / "agent33-alerts.rules.yaml",
]


def test_service_level_objectives_doc_has_expected_sections_and_content() -> None:
    content = _OBJECTIVES_PATH.read_text(encoding="utf-8")

    for section in _EXPECTED_SECTIONS:
        assert section in content, section

    for expected in _EXPECTED_STRINGS:
        assert expected in content, expected

    assert "agent33-slo.rules.yaml" not in content
    assert 'up{service="agent33-api"}' not in content


def test_service_level_objectives_doc_references_files_that_exist() -> None:
    for path in _REFERENCED_PATHS:
        assert path.exists(), path
