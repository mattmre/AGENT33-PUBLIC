"""Validation for the production incident-response playbooks."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLAYBOOK_PATH = _REPO_ROOT / "docs" / "operators" / "incident-response-playbooks.md"
_EXPECTED_SECTIONS = {
    "## Purpose",
    "## Severity Model",
    "## Shared Triage Workflow",
    "## Incident Matrix",
    "## Playbook 1: API Service Down",
    "## Playbook 2: Degraded Dependencies / Readiness Failure",
    "## Playbook 3: Evaluation Regression / Scheduled-Gate Failure",
    "## Playbook 4: Webhook Delivery Backlog Growth / Dead Letters",
    "## Dependency Map",
}
_EXPECTED_STRINGS = {
    "production-deployment-runbook.md",
    "deploy/monitoring/README.md",
    "deploy/monitoring/prometheus/agent33-alerts.rules.yaml",
    "deploy/k8s/overlays/production/README.md",
    "kubectl port-forward svc/agent33-api -n agent33 8000:8000",
    "/healthz",
    "/readyz",
    "/health",
    "/metrics",
    "/v1/dashboard/alerts",
    "/v1/operator/status",
    "/v1/operator/doctor",
    "/v1/operator/reset",
    "/v1/evaluations/regressions",
    "/v1/evaluations/schedules",
    "/v1/webhooks/deliveries/stats",
    "/v1/webhooks/deliveries/dead-letters",
    "/v1/webhooks/deliveries/$DELIVERY_ID/retry",
    "kubectl rollout undo deployment/agent33-api -n agent33",
    "kubectl exec -n agent33 deploy/ollama -- ollama pull llama3.2",
}
_REFERENCED_PATHS = [
    _REPO_ROOT / "docs" / "operators" / "production-deployment-runbook.md",
    _REPO_ROOT / "deploy" / "monitoring" / "README.md",
    _REPO_ROOT / "deploy" / "monitoring" / "prometheus" / "agent33-alerts.rules.yaml",
    _REPO_ROOT / "deploy" / "k8s" / "overlays" / "production" / "README.md",
]


def test_incident_playbooks_have_expected_sections_and_commands() -> None:
    content = _PLAYBOOK_PATH.read_text(encoding="utf-8")

    for section in _EXPECTED_SECTIONS:
        assert section in content, section

    for expected in _EXPECTED_STRINGS:
        assert expected in content, expected


def test_incident_playbooks_reference_files_that_exist() -> None:
    for path in _REFERENCED_PATHS:
        assert path.exists(), path
