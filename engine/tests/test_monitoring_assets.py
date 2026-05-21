"""Validation for checked-in monitoring assets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GRAFANA_DASHBOARD_PATH = (
    _REPO_ROOT / "deploy" / "monitoring" / "grafana" / "agent33-production-overview.dashboard.json"
)
_PROMETHEUS_RULES_PATH = (
    _REPO_ROOT / "deploy" / "monitoring" / "prometheus" / "agent33-alerts.rules.yaml"
)
_EXPECTED_METRICS = {
    "effort_routing_decisions_total",
    "effort_routing_high_effort_total",
    "effort_routing_export_failures_total",
    "effort_routing_estimated_cost_usd_avg",
    "effort_routing_estimated_token_budget_avg",
    "evaluation_runs_total",
    "connector_health_check_total",
}
# Metrics referenced in the Grafana dashboard but not in Prometheus recording/alert
# rules.  Checked only against the dashboard, not against rule expressions.
_DASHBOARD_ONLY_METRICS = {
    "evaluation_score",
    "evaluation_gate_results_total",
    "evaluation_duration_seconds",
    "connector_message_send_total",
    "connector_message_send_duration_seconds",
}
# HTTP and webhook metrics only appear in Prometheus rules, not yet in Grafana dashboard
_PROMETHEUS_ONLY_METRICS = {
    "http_requests_total",
    "http_request_duration_seconds",
    "webhook_delivery_total",
    "webhook_delivery_failures_total",
    "dead_letter_queue_depth",
}
# Rolling-window metrics are exported by Prometheus but not yet referenced in
# the Grafana dashboard, so they are checked separately.
_EXPECTED_PROMETHEUS_WINDOW_METRICS = {
    "effort_routing_estimated_cost_usd_window_avg",
    "effort_routing_estimated_token_budget_window_avg",
}
_EXPECTED_RECORDS = {
    "agent33:sli:effort_telemetry_export_failures:count_15m",
    "agent33:sli:effort_telemetry_export_failures:count_28d",
    "agent33:sli:high_effort_routing_ratio:ratio_15m",
    "agent33:sli:estimated_cost_usd_avg:max",
    "agent33:sli:estimated_cost_usd_window_avg:max",
    "agent33:sli:estimated_token_budget_avg:max",
    "agent33:sli:estimated_token_budget_window_avg:max",
    "agent33:http_requests:error_rate_5m",
    "agent33:http_request_duration_seconds:p99_5m",
    "agent33:webhook_delivery:failure_rate_5m",
    "agent33:evaluation:gate_error_rate_5m",
    "agent33:connector:health_check_failure_rate_5m",
}
_EXPECTED_ALERTS = {
    "Agent33EffortTelemetryExportFailures",
    "Agent33HighEffortRoutingRatio",
    "Agent33EstimatedCostDrift",
    "Agent33HighErrorRate",
    "Agent33HighLatency",
    "Agent33WebhookDeliveryFailures",
    "Agent33DeadLetterQueueGrowing",
    "Agent33EvaluationGateErrors",
    "Agent33ConnectorUnhealthy",
}
_UNSUPPORTED_PROMQL_TOKENS = {
    "probe_success",
    "readyz",
    "healthz",
}


def _walk_strings(value: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(value, str):
        strings.append(value)
    elif isinstance(value, list):
        for item in value:
            strings.extend(_walk_strings(item))
    elif isinstance(value, dict):
        for item in value.values():
            strings.extend(_walk_strings(item))
    return strings


def test_grafana_dashboard_is_parseable_and_references_expected_metrics() -> None:
    dashboard = json.loads(_GRAFANA_DASHBOARD_PATH.read_text(encoding="utf-8"))

    assert dashboard["title"] == "AGENT-33 Production Overview"
    assert dashboard["uid"] == "agent33-production-overview"
    assert dashboard["schemaVersion"] >= 39
    assert len(dashboard["panels"]) >= 5

    strings = _walk_strings(dashboard)
    for metric in _EXPECTED_METRICS | _DASHBOARD_ONLY_METRICS:
        assert any(metric in item for item in strings), metric


def test_prometheus_rules_are_parseable_and_reference_expected_metrics() -> None:
    payload = yaml.safe_load(_PROMETHEUS_RULES_PATH.read_text(encoding="utf-8"))

    assert isinstance(payload, dict)
    groups = payload.get("groups")
    assert isinstance(groups, list) and groups
    assert groups[0]["name"] == "agent33-observability"

    rules = groups[0].get("rules")
    assert isinstance(rules, list) and len(rules) == 21

    record_names = {rule["record"] for rule in rules if "record" in rule}
    alert_names = {rule["alert"] for rule in rules if "alert" in rule}
    expressions = [rule["expr"] for rule in rules]
    records_by_name = {rule["record"]: rule["expr"] for rule in rules if "record" in rule}
    alerts_by_name = {rule["alert"]: rule["expr"] for rule in rules if "alert" in rule}
    alert_annotations = {
        rule["alert"]: rule.get("annotations", {}) for rule in rules if "alert" in rule
    }

    assert record_names == _EXPECTED_RECORDS
    assert alert_names == _EXPECTED_ALERTS

    all_prom_metrics = (
        _EXPECTED_METRICS | _PROMETHEUS_ONLY_METRICS | _EXPECTED_PROMETHEUS_WINDOW_METRICS
    )
    for metric in all_prom_metrics:
        assert any(metric in expr for expr in expressions), metric

    for token in _UNSUPPORTED_PROMQL_TOKENS:
        assert all(token not in expr for expr in expressions), token

    assert (
        "increase(effort_routing_export_failures_total[15m])"
        in records_by_name["agent33:sli:effort_telemetry_export_failures:count_15m"]
    )
    assert (
        "increase(effort_routing_export_failures_total[28d])"
        in records_by_name["agent33:sli:effort_telemetry_export_failures:count_28d"]
    )
    assert (
        "increase(effort_routing_high_effort_total[15m])"
        in records_by_name["agent33:sli:high_effort_routing_ratio:ratio_15m"]
    )
    assert (
        "increase(effort_routing_decisions_total[15m])"
        in records_by_name["agent33:sli:high_effort_routing_ratio:ratio_15m"]
    )
    assert records_by_name["agent33:sli:estimated_cost_usd_avg:max"] == (
        "max(effort_routing_estimated_cost_usd_avg)"
    )
    assert records_by_name["agent33:sli:estimated_cost_usd_window_avg:max"] == (
        "max(effort_routing_estimated_cost_usd_window_avg)"
    )
    assert records_by_name["agent33:sli:estimated_token_budget_avg:max"] == (
        "max(effort_routing_estimated_token_budget_avg)"
    )
    assert records_by_name["agent33:sli:estimated_token_budget_window_avg:max"] == (
        "max(effort_routing_estimated_token_budget_window_avg)"
    )
    assert "count_15m > 0" in alerts_by_name["Agent33EffortTelemetryExportFailures"]
    assert "ratio_15m > 0.5" in alerts_by_name["Agent33HighEffortRoutingRatio"]
    assert (
        "estimated_cost_usd_window_avg:max > 0.25" in alerts_by_name["Agent33EstimatedCostDrift"]
    )
    assert "rolling-window" in alert_annotations["Agent33EstimatedCostDrift"]["summary"].lower()

    # P3.10: Webhook delivery recording rule and alerts
    assert (
        "webhook_delivery_failures_total"
        in records_by_name["agent33:webhook_delivery:failure_rate_5m"]
    )
    assert "webhook_delivery_total" in records_by_name["agent33:webhook_delivery:failure_rate_5m"]
    assert "failure_rate_5m > 0.05" in alerts_by_name["Agent33WebhookDeliveryFailures"]
    assert "dead_letter_queue_depth > 100" in alerts_by_name["Agent33DeadLetterQueueGrowing"]
    assert "failure rate" in alert_annotations["Agent33WebhookDeliveryFailures"]["summary"].lower()
    assert "dead-letter" in alert_annotations["Agent33DeadLetterQueueGrowing"]["summary"].lower()

    # P4.7: Evaluation gate recording rule and alert
    assert "evaluation_runs_total" in records_by_name["agent33:evaluation:gate_error_rate_5m"]
    assert "gate_error_rate_5m > 0.01" in alerts_by_name["Agent33EvaluationGateErrors"]
    assert "evaluation gate" in alert_annotations["Agent33EvaluationGateErrors"]["summary"].lower()

    # P4.7: Connector health recording rule and alert
    assert (
        "connector_health_check_total"
        in records_by_name["agent33:connector:health_check_failure_rate_5m"]
    )
    assert "health_check_failure_rate_5m > 0.05" in alerts_by_name["Agent33ConnectorUnhealthy"]
    assert "connector" in alert_annotations["Agent33ConnectorUnhealthy"]["summary"].lower()
