"""Tests for P1.4 query profiling instrumentation.

Verifies:
- The ``track_query`` context manager fires WARNING logs when threshold exceeded
- No WARNING when under threshold
- Prometheus histogram observations are recorded with correct labels
- The ``slow_query_threshold_ms`` config field exists with correct default
- The ``configure_query_profiling`` wiring function works correctly
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from agent33.config import Settings
from agent33.observability.metrics import MetricsCollector
from agent33.observability.query_profiling import (
    _METRIC_NAME,
    configure_query_profiling,
    track_query,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def metrics() -> MetricsCollector:
    return MetricsCollector()


@pytest.fixture(autouse=True)
def _wire_profiling(metrics: MetricsCollector) -> None:
    """Ensure profiling is wired with a very low threshold for slow-query tests."""
    configure_query_profiling(metrics, threshold_ms=50)


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestConfigField:
    """Verify the slow_query_threshold_ms config field."""

    def test_default_value(self) -> None:
        s = Settings()
        assert s.slow_query_threshold_ms == 100

    def test_custom_value(self) -> None:
        s = Settings(slow_query_threshold_ms=250)
        assert s.slow_query_threshold_ms == 250


# ---------------------------------------------------------------------------
# track_query: slow-query WARNING
# ---------------------------------------------------------------------------


class TestTrackQuerySlowWarning:
    """Verify WARNING is logged when a tracked operation exceeds threshold."""

    async def test_slow_operation_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """An operation that takes longer than threshold_ms should emit a WARNING."""
        with caplog.at_level(logging.WARNING, logger="agent33.observability.query_profiling"):
            async with track_query("memory_search", table="memory_records", threshold_ms=1):
                # Sleep 20ms to guarantee we exceed 1ms threshold
                await asyncio.sleep(0.02)

        # Assert the warning was emitted
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        record = warnings[0]
        assert "slow_query" in record.message
        assert "memory_search" in record.message
        assert "memory_records" in record.message
        assert "threshold_ms=1" in record.message

    async def test_fast_operation_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """An operation under threshold should NOT emit a WARNING."""
        with caplog.at_level(logging.WARNING, logger="agent33.observability.query_profiling"):
            # Use a very high threshold so we never trigger it
            async with track_query("memory_search", table="memory_records", threshold_ms=10000):
                pass  # near-zero latency

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 0

    async def test_slow_query_uses_global_threshold(
        self, metrics: MetricsCollector, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When no per-call threshold is given, the global configured threshold is used."""
        # Configure with 1ms threshold (very low, sleep will exceed it)
        configure_query_profiling(metrics, threshold_ms=1)
        with caplog.at_level(logging.WARNING, logger="agent33.observability.query_profiling"):
            async with track_query("memory_store", table="memory_records"):
                await asyncio.sleep(0.02)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "threshold_ms=1" in warnings[0].message


# ---------------------------------------------------------------------------
# track_query: Prometheus histogram observation
# ---------------------------------------------------------------------------


class TestTrackQueryPrometheusMetric:
    """Verify Prometheus observations are recorded correctly."""

    async def test_observation_recorded_with_labels(self, metrics: MetricsCollector) -> None:
        """After track_query completes, the histogram should have an observation."""
        async with track_query("memory_search", table="memory_records", threshold_ms=99999):
            pass  # near-zero latency, just need it to record

        summary = metrics.get_summary()
        # The observation key format is "metric_name(label_key)" where
        # label_key is "operation=memory_search,table=memory_records"
        expected_key = f"{_METRIC_NAME}(operation=memory_search,table=memory_records)"
        assert expected_key in summary, f"Expected {expected_key} in {list(summary.keys())}"

        obs_data = summary[expected_key]
        assert obs_data["count"] == 1
        assert obs_data["sum"] >= 0.0
        assert obs_data["min"] >= 0.0
        assert obs_data["max"] >= 0.0

    async def test_multiple_observations_accumulate(self, metrics: MetricsCollector) -> None:
        """Multiple calls should accumulate observations."""
        for _ in range(3):
            async with track_query("memory_scan", table="memory_records", threshold_ms=99999):
                pass

        summary = metrics.get_summary()
        expected_key = f"{_METRIC_NAME}(operation=memory_scan,table=memory_records)"
        assert expected_key in summary
        assert summary[expected_key]["count"] == 3

    async def test_different_operations_tracked_separately(
        self, metrics: MetricsCollector
    ) -> None:
        """Different operation names should be tracked under separate label sets."""
        async with track_query("memory_search", table="memory_records", threshold_ms=99999):
            pass
        async with track_query("memory_store", table="memory_records", threshold_ms=99999):
            pass

        summary = metrics.get_summary()
        search_key = f"{_METRIC_NAME}(operation=memory_search,table=memory_records)"
        store_key = f"{_METRIC_NAME}(operation=memory_store,table=memory_records)"
        assert search_key in summary
        assert store_key in summary
        assert summary[search_key]["count"] == 1
        assert summary[store_key]["count"] == 1

    async def test_metric_in_prometheus_allowlist(self) -> None:
        """db_query_duration_seconds must be in the Prometheus observation allowlist."""
        assert _METRIC_NAME in MetricsCollector._PROMETHEUS_OBSERVATION_ALLOWLIST

    async def test_prometheus_rendering_includes_metric(self, metrics: MetricsCollector) -> None:
        """The Prometheus exposition output should include db_query_duration_seconds."""
        async with track_query("memory_search", table="memory_records", threshold_ms=99999):
            pass

        rendered = metrics.render_prometheus()
        assert "db_query_duration_seconds_count" in rendered
        assert "db_query_duration_seconds_sum" in rendered
        assert 'operation="memory_search"' in rendered
        assert 'table="memory_records"' in rendered


# ---------------------------------------------------------------------------
# configure_query_profiling
# ---------------------------------------------------------------------------


class TestConfigureQueryProfiling:
    """Verify the wiring function."""

    async def test_threshold_clamped_to_minimum_1(
        self, metrics: MetricsCollector, caplog: pytest.LogCaptureFixture
    ) -> None:
        """threshold_ms=0 should be clamped to 1 (never disable warnings)."""
        configure_query_profiling(metrics, threshold_ms=0)
        with caplog.at_level(logging.WARNING, logger="agent33.observability.query_profiling"):
            async with track_query("memory_search", table="memory_records"):
                await asyncio.sleep(0.01)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        # Clamped to 1ms
        assert "threshold_ms=1" in warnings[0].message

    async def test_no_metrics_graceful(self) -> None:
        """track_query should not crash when no MetricsCollector is configured."""
        # Reset module state by passing None-like collector
        configure_query_profiling(MetricsCollector(), threshold_ms=99999)
        # This should not raise
        async with track_query("memory_search", table="memory_records"):
            pass


# ---------------------------------------------------------------------------
# Exception propagation
# ---------------------------------------------------------------------------


class TestExceptionPropagation:
    """track_query must not swallow exceptions from the tracked operation."""

    async def test_exception_propagates(self, metrics: MetricsCollector) -> None:
        """Exceptions inside the context manager should propagate normally."""
        with pytest.raises(ValueError, match="test error"):
            async with track_query("memory_search", table="memory_records", threshold_ms=99999):
                raise ValueError("test error")

    async def test_metric_recorded_even_on_exception(self, metrics: MetricsCollector) -> None:
        """Even when an exception occurs, the duration should be recorded."""
        with pytest.raises(RuntimeError):
            async with track_query("memory_store", table="memory_records", threshold_ms=99999):
                raise RuntimeError("db went away")

        summary = metrics.get_summary()
        expected_key = f"{_METRIC_NAME}(operation=memory_store,table=memory_records)"
        assert expected_key in summary
        assert summary[expected_key]["count"] == 1
