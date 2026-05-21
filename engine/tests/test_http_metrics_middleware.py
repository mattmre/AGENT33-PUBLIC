"""Tests for HTTP request metrics middleware and path normalization."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent33.observability.http_metrics import HTTPMetricsMiddleware, normalize_path
from agent33.observability.metrics import MetricsCollector

# ---------------------------------------------------------------------------
# Path normalization unit tests
# ---------------------------------------------------------------------------


class TestNormalizePath:
    """Verify UUID and numeric segment collapsing."""

    def test_uuid_replaced(self) -> None:
        path = "/v1/agents/550e8400-e29b-41d4-a716-446655440000/invoke"
        assert normalize_path(path) == "/v1/agents/{id}/invoke"

    def test_multiple_uuids_replaced(self) -> None:
        path = (
            "/v1/workflows/550e8400-e29b-41d4-a716-446655440000"
            "/steps/660e8400-e29b-41d4-a716-446655440001"
        )
        assert normalize_path(path) == "/v1/workflows/{id}/steps/{id}"

    def test_numeric_segment_replaced(self) -> None:
        path = "/v1/items/12345/details"
        assert normalize_path(path) == "/v1/items/{id}/details"

    def test_numeric_segment_at_end(self) -> None:
        path = "/v1/items/42"
        assert normalize_path(path) == "/v1/items/{id}"

    def test_no_replacement_needed(self) -> None:
        path = "/health"
        assert normalize_path(path) == "/health"

    def test_mixed_uuid_and_numeric(self) -> None:
        path = "/v1/agents/550e8400-e29b-41d4-a716-446655440000/tasks/99"
        assert normalize_path(path) == "/v1/agents/{id}/tasks/{id}"

    def test_empty_path(self) -> None:
        assert normalize_path("") == ""

    def test_root_path(self) -> None:
        assert normalize_path("/") == "/"

    def test_text_segments_preserved(self) -> None:
        path = "/v1/dashboard/metrics"
        assert normalize_path(path) == "/v1/dashboard/metrics"


# ---------------------------------------------------------------------------
# Middleware integration tests
# ---------------------------------------------------------------------------


def _make_app(collector: MetricsCollector) -> FastAPI:
    """Create a minimal FastAPI app with the metrics middleware."""
    test_app = FastAPI()
    test_app.add_middleware(HTTPMetricsMiddleware, collector=collector)

    @test_app.get("/ok")
    async def ok_route() -> dict[str, str]:
        return {"status": "ok"}

    @test_app.get("/items/{item_id}")
    async def item_route(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    @test_app.get("/error")
    async def error_route() -> None:
        raise RuntimeError("deliberate error")

    return test_app


class TestHTTPMetricsMiddleware:
    """Verify the middleware records counters and observations correctly."""

    def test_records_request_total_counter(self) -> None:
        collector = MetricsCollector()
        app = _make_app(collector)
        client = TestClient(app, raise_server_exceptions=False)
        client.get("/ok")

        summary = collector.get_summary()
        # The counter key for http_requests_total should include method=GET, path=/ok, status=200
        counter_data = summary.get("http_requests_total")
        assert counter_data is not None
        # Find the specific label combination
        expected_key = "method=GET,path=/ok,status_code=200"
        assert counter_data[expected_key] == 1

    def test_records_duration_observation(self) -> None:
        collector = MetricsCollector()
        app = _make_app(collector)
        client = TestClient(app, raise_server_exceptions=False)
        client.get("/ok")

        summary = collector.get_summary()
        # Observation key format is "name(label_key)"
        duration_key = "http_request_duration_seconds(method=GET,path=/ok)"
        assert duration_key in summary
        obs = summary[duration_key]
        assert obs["count"] == 1
        assert obs["sum"] > 0
        assert obs["min"] > 0

    def test_5xx_counted_correctly(self) -> None:
        collector = MetricsCollector()
        app = _make_app(collector)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/error")

        assert resp.status_code == 500
        summary = collector.get_summary()
        counter_data = summary.get("http_requests_total")
        assert counter_data is not None
        expected_key = "method=GET,path=/error,status_code=500"
        assert counter_data[expected_key] == 1

    def test_path_normalization_in_labels(self) -> None:
        collector = MetricsCollector()
        app = _make_app(collector)
        client = TestClient(app, raise_server_exceptions=False)
        client.get("/items/42")

        summary = collector.get_summary()
        counter_data = summary.get("http_requests_total")
        assert counter_data is not None
        # Numeric segment should be normalized to {id}
        expected_key = "method=GET,path=/items/{id},status_code=200"
        assert counter_data[expected_key] == 1

    def test_multiple_requests_increment_counter(self) -> None:
        collector = MetricsCollector()
        app = _make_app(collector)
        client = TestClient(app, raise_server_exceptions=False)
        client.get("/ok")
        client.get("/ok")
        client.get("/ok")

        summary = collector.get_summary()
        counter_data = summary.get("http_requests_total")
        expected_key = "method=GET,path=/ok,status_code=200"
        assert counter_data is not None
        assert counter_data[expected_key] == 3

    def test_multiple_requests_accumulate_duration(self) -> None:
        collector = MetricsCollector()
        app = _make_app(collector)
        client = TestClient(app, raise_server_exceptions=False)
        client.get("/ok")
        client.get("/ok")

        summary = collector.get_summary()
        duration_key = "http_request_duration_seconds(method=GET,path=/ok)"
        obs = summary[duration_key]
        assert obs["count"] == 2

    def test_no_collector_passes_through(self) -> None:
        """When no collector is set, requests should still succeed."""
        test_app = FastAPI()
        test_app.add_middleware(HTTPMetricsMiddleware)

        @test_app.get("/ok")
        async def ok_route() -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(test_app, raise_server_exceptions=False)
        resp = client.get("/ok")
        assert resp.status_code == 200

    def test_prometheus_renders_http_metrics(self) -> None:
        """Verify the new metrics appear in Prometheus text output."""
        collector = MetricsCollector()
        app = _make_app(collector)
        client = TestClient(app, raise_server_exceptions=False)
        client.get("/ok")

        output = collector.render_prometheus()
        assert "http_requests_total" in output
        assert "http_request_duration_seconds" in output
        assert 'method="GET"' in output
        assert 'path="/ok"' in output
        assert 'status_code="200"' in output


# ---------------------------------------------------------------------------
# Health check metric emission test
# ---------------------------------------------------------------------------


class TestHealthCheckMetrics:
    """Verify health endpoint emits health_check_result observations."""

    def test_health_emits_metrics_when_collector_available(self) -> None:
        from agent33.main import app as real_app

        collector = MetricsCollector()
        # Install collector on app.state for the health route to find
        real_app.state.metrics_collector = collector

        client = TestClient(real_app, raise_server_exceptions=False)

        # The /health endpoint is public (no auth needed)
        resp = client.get("/health")
        assert resp.status_code == 200

        summary = collector.get_summary()
        # At minimum, the messaging channel loop and voice/status_line/connectors
        # checks should emit health_check_result observations.
        # Look for any health_check_result key in the summary.
        health_keys = [k for k in summary if k.startswith("health_check_result")]
        # There should be at least one health check observation
        assert len(health_keys) > 0

        # Verify the observation structure
        for key in health_keys:
            obs = summary[key]
            assert "count" in obs
            assert obs["count"] >= 1
            # Value should be 0.0 or 1.0
            assert obs["min"] >= 0.0
            assert obs["max"] <= 1.0


# ---------------------------------------------------------------------------
# Prometheus rendering for health metrics
# ---------------------------------------------------------------------------


class TestPrometheusHealthMetrics:
    """Verify health_check_result appears in Prometheus output."""

    def test_health_check_result_in_prometheus(self) -> None:
        collector = MetricsCollector()
        collector.observe("health_check_result", 1.0, {"service": "redis"})
        collector.observe("health_check_result", 0.0, {"service": "nats"})

        output = collector.render_prometheus()
        assert "health_check_result" in output
        assert 'service="redis"' in output
        assert 'service="nats"' in output
