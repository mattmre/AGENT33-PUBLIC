"""Prometheus metrics endpoint tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes import dashboard as dashboard_route
from agent33.main import app
from agent33.observability.metrics import MetricsCollector


@pytest.fixture
def isolated_metrics_collector() -> MetricsCollector:
    collector = MetricsCollector()
    dashboard_route.set_metrics(collector)
    yield collector
    dashboard_route.set_metrics(MetricsCollector())


def test_metrics_endpoint_is_public_and_not_rate_limited(
    isolated_metrics_collector: MetricsCollector,
) -> None:
    isolated_metrics_collector.increment(
        "effort_routing_decisions_total",
        labels={"effort": "high", "source": "policy"},
    )
    isolated_metrics_collector.increment("effort_routing_high_effort_total")
    isolated_metrics_collector.observe(
        "effort_routing_estimated_cost_usd",
        0.8,
        labels={"effort": "high", "source": "policy"},
    )

    unauthenticated_client = TestClient(app)
    response = unauthenticated_client.get("/metrics")
    unauthenticated_client.close()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert "X-RateLimit-Limit" not in response.headers
    assert "# TYPE effort_routing_decisions_total counter" in response.text
    assert 'effort_routing_decisions_total{effort="high",source="policy"} 1' in response.text
    assert "effort_routing_high_effort_total 1" in response.text
    assert 'effort_routing_estimated_cost_usd_count{effort="high",source="policy"} 1' in (
        response.text
    )


def test_dashboard_metrics_remains_json(
    client: TestClient,
    isolated_metrics_collector: MetricsCollector,
) -> None:
    isolated_metrics_collector.increment(
        "effort_routing_decisions_total",
        labels={"effort": "medium", "source": "policy"},
    )

    response = client.get("/v1/dashboard/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["effort_routing_decisions_total"]["effort=medium,source=policy"] == 1
