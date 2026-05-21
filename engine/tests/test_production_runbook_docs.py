"""Validation for the production deployment runbook."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNBOOK_PATH = _REPO_ROOT / "docs" / "operators" / "production-deployment-runbook.md"
_EXPECTED_SECTIONS = {
    "## Purpose",
    "## Current Baseline",
    "## Pre-Deployment Checklist",
    "## Rollout Procedure",
    "## Bootstrap Admin Flow",
    "## Health Checks",
    "## Monitoring Checks",
    "## Rollback",
    "## Common Recovery Cases",
}
_EXPECTED_STRINGS = {
    "deploy/k8s/base/README.md",
    "deploy/k8s/overlays/production/README.md",
    "deploy/monitoring/README.md",
    "agent33-api",
    "agent33",
    "/health",
    "/healthz",
    "/readyz",
    "/metrics",
    "/v1/dashboard/alerts",
    "/v1/operator/status",
    "kubectl apply -n agent33 -f /tmp/postgres-secret.yaml",
    "kubectl apply -n agent33 -f /tmp/api-secret.yaml",
    "metadata.namespace: agent33",
    "kubectl apply -k deploy/k8s/overlays/production",
    "kubectl rollout status deployment/agent33-api -n agent33 --timeout=180s",
    "kubectl rollout undo deployment/agent33-api -n agent33",
    "kubectl exec -n agent33 deploy/ollama -- ollama pull llama3.2",
}
_REFERENCED_PATHS = [
    _REPO_ROOT / "deploy" / "k8s" / "base" / "README.md",
    _REPO_ROOT / "deploy" / "k8s" / "overlays" / "production" / "README.md",
    _REPO_ROOT / "deploy" / "monitoring" / "README.md",
    _REPO_ROOT
    / "deploy"
    / "monitoring"
    / "grafana"
    / "agent33-production-overview.dashboard.json",
    _REPO_ROOT / "deploy" / "monitoring" / "prometheus" / "agent33-alerts.rules.yaml",
]


def test_production_runbook_has_expected_sections_and_commands() -> None:
    content = _RUNBOOK_PATH.read_text(encoding="utf-8")

    for section in _EXPECTED_SECTIONS:
        assert section in content, section

    for expected in _EXPECTED_STRINGS:
        assert expected in content, expected


def test_production_runbook_references_files_that_exist() -> None:
    content = _RUNBOOK_PATH.read_text(encoding="utf-8")

    for path in _REFERENCED_PATHS:
        assert path.exists(), path
        assert path.relative_to(_REPO_ROOT).as_posix() in content
