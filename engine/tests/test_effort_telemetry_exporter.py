"""Tests for effort-routing telemetry export behavior."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from agent33.api.routes import agents as agents_route
from agent33.config import settings
from agent33.observability.effort_telemetry import (
    EffortTelemetryExportError,
    FileEffortTelemetryExporter,
    NoopEffortTelemetryExporter,
)
from agent33.observability.metrics import MetricsCollector


def test_file_exporter_writes_jsonl_with_routing_payload(tmp_path) -> None:
    export_path = tmp_path / "telemetry" / "effort.jsonl"
    exporter = FileEffortTelemetryExporter(str(export_path))
    event = {
        "timestamp": "2026-01-01T00:00:00+00:00",
        "routing": {"effort": "high", "source": "policy"},
    }

    exporter.export(event)

    lines = export_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["routing"]["effort"] == "high"
    assert payload["routing"]["source"] == "policy"


def test_effort_export_fail_open_increments_failure_metric(monkeypatch) -> None:
    class FailingExporter:
        def export(self, event: dict[str, object]) -> None:
            raise EffortTelemetryExportError("boom")

    metrics = MetricsCollector()
    agents_route.set_metrics(metrics)
    try:
        agents_route.set_effort_telemetry_exporter(FailingExporter())
        monkeypatch.setattr(settings, "observability_effort_export_fail_closed", False)
        agents_route._record_effort_routing_metrics({"effort": "high", "source": "policy"})
        summary = metrics.get_summary()
        assert summary["effort_routing_export_failures_total"] == 1
    finally:
        agents_route.set_effort_telemetry_exporter(NoopEffortTelemetryExporter())


def test_effort_export_fail_closed_raises_503(monkeypatch) -> None:
    class FailingExporter:
        def export(self, event: dict[str, object]) -> None:
            raise EffortTelemetryExportError("boom")

    metrics = MetricsCollector()
    agents_route.set_metrics(metrics)
    try:
        agents_route.set_effort_telemetry_exporter(FailingExporter())
        monkeypatch.setattr(settings, "observability_effort_export_fail_closed", True)
        with pytest.raises(HTTPException) as exc_info:
            agents_route._record_effort_routing_metrics({"effort": "high", "source": "policy"})
        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "Effort telemetry export failed"
        assert metrics.get_summary()["effort_routing_export_failures_total"] == 1
    finally:
        agents_route.set_effort_telemetry_exporter(NoopEffortTelemetryExporter())
