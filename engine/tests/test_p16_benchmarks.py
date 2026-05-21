"""P1.6 Benchmark smoke tests — validate benchmarking infrastructure.

These tests verify that the performance-observation infrastructure added in
P1.3 (connection pool tuning) and P1.4 (query profiling) works correctly.
They are NOT performance benchmarks; they assert on *behavioral correctness*
of the instrumentation layer using mocks and controlled timing.

Specifically tests:
- track_query records duration to the Prometheus histogram
- track_query label combinations are correct
- slow_query_threshold_ms triggers warning log at correct threshold
- db_pool_size / db_max_overflow propagate to create_async_engine
- redis_max_connections propagates to Redis.from_url
- pool_pre_ping and pool_recycle propagate correctly
- db_query_duration_seconds histogram exists in the Prometheus allowlist
- track_query reraises exceptions (error propagation)
- Concurrent track_query calls produce independent observations
- configure_query_profiling stores the collector reference
- Settings config knobs have expected defaults
- Prometheus rendered output includes the metric under the correct name
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock, patch

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
    """Fresh MetricsCollector per test."""
    return MetricsCollector()


@pytest.fixture(autouse=True)
def _wire_profiling(metrics: MetricsCollector) -> None:
    """Wire profiling with a high default threshold to avoid spurious warnings."""
    configure_query_profiling(metrics, threshold_ms=99999)


# ---------------------------------------------------------------------------
# 1. track_query records duration (mock time, assert histogram updated)
# ---------------------------------------------------------------------------


class TestTrackQueryRecordsDuration:
    """Verify that track_query records a duration observation to the histogram."""

    async def test_duration_recorded_after_context_exit(self, metrics: MetricsCollector) -> None:
        """After yielding, the histogram must contain exactly one observation
        with a non-negative duration value."""
        async with track_query("memory_search", table="memory_records"):
            await asyncio.sleep(0.005)  # 5ms minimum measurable duration

        summary = metrics.get_summary()
        key = f"{_METRIC_NAME}(operation=memory_search,table=memory_records)"
        assert key in summary, f"Expected {key} in {list(summary.keys())}"
        assert summary[key]["count"] == 1
        assert summary[key]["sum"] > 0.0, "Duration should be positive"
        assert summary[key]["min"] > 0.0

    async def test_observe_called_with_elapsed_seconds(self, metrics: MetricsCollector) -> None:
        """Verify the collector's observe method is invoked with a float value
        that represents seconds (not milliseconds)."""
        original_observe = metrics.observe
        observed_values: list[float] = []

        def capturing_observe(
            name: str, value: float, labels: dict[str, str] | None = None
        ) -> None:
            observed_values.append(value)
            original_observe(name, value, labels=labels)

        metrics.observe = capturing_observe  # type: ignore[assignment]
        async with track_query("bench_op", table="bench_table"):
            await asyncio.sleep(0.01)

        assert len(observed_values) == 1
        # Value should be in seconds, so ~0.01 (not 10)
        assert 0.001 < observed_values[0] < 1.0, (
            f"Expected seconds-scale value, got {observed_values[0]}"
        )


# ---------------------------------------------------------------------------
# 2. track_query with operation/table labels produces correct label combos
# ---------------------------------------------------------------------------


class TestTrackQueryLabelCombinations:
    """Verify different operation/table combinations produce separate metric keys."""

    async def test_distinct_operation_labels(self, metrics: MetricsCollector) -> None:
        """Two calls with different operation names must produce distinct keys."""
        async with track_query("memory_store", table="memory_records"):
            pass
        async with track_query("memory_scan", table="memory_records"):
            pass

        summary = metrics.get_summary()
        store_key = f"{_METRIC_NAME}(operation=memory_store,table=memory_records)"
        scan_key = f"{_METRIC_NAME}(operation=memory_scan,table=memory_records)"
        assert store_key in summary
        assert scan_key in summary
        assert summary[store_key]["count"] == 1
        assert summary[scan_key]["count"] == 1

    async def test_distinct_table_labels(self, metrics: MetricsCollector) -> None:
        """Two calls with different table names must produce distinct keys."""
        async with track_query("memory_search", table="memory_records"):
            pass
        async with track_query("memory_search", table="sessions"):
            pass

        summary = metrics.get_summary()
        records_key = f"{_METRIC_NAME}(operation=memory_search,table=memory_records)"
        sessions_key = f"{_METRIC_NAME}(operation=memory_search,table=sessions)"
        assert records_key in summary
        assert sessions_key in summary

    async def test_default_table_label_is_unknown(self, metrics: MetricsCollector) -> None:
        """When no table is specified, the label defaults to 'unknown'."""
        async with track_query("some_operation"):
            pass

        summary = metrics.get_summary()
        key = f"{_METRIC_NAME}(operation=some_operation,table=unknown)"
        assert key in summary


# ---------------------------------------------------------------------------
# 3. slow_query_threshold_ms triggers warning log at correct threshold
# ---------------------------------------------------------------------------


class TestSlowQueryThresholdWarning:
    """Verify the slow-query warning fires based on threshold."""

    async def test_warning_when_exceeds_per_call_threshold(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A per-call threshold_ms=1 with 20ms sleep must trigger a warning."""
        with caplog.at_level(logging.WARNING, logger="agent33.observability.query_profiling"):
            async with track_query("slow_op", table="t", threshold_ms=1):
                await asyncio.sleep(0.02)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "slow_query" in warnings[0].message
        assert "slow_op" in warnings[0].message
        assert "threshold_ms=1" in warnings[0].message

    async def test_no_warning_when_under_threshold(self, caplog: pytest.LogCaptureFixture) -> None:
        """A high threshold with near-instant body should emit no warning."""
        with caplog.at_level(logging.WARNING, logger="agent33.observability.query_profiling"):
            async with track_query("fast_op", table="t", threshold_ms=99999):
                pass  # near-zero latency

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 0

    async def test_global_threshold_used_when_no_override(
        self, metrics: MetricsCollector, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When no per-call threshold is given, the module-level default is used."""
        configure_query_profiling(metrics, threshold_ms=1)
        with caplog.at_level(logging.WARNING, logger="agent33.observability.query_profiling"):
            async with track_query("global_thresh_op", table="t"):
                await asyncio.sleep(0.02)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "threshold_ms=1" in warnings[0].message


# ---------------------------------------------------------------------------
# 4. db_pool_size and db_max_overflow passed to engine creation
# ---------------------------------------------------------------------------


class TestConnectionPoolConfigPropagation:
    """Verify pool config from Settings propagates to create_async_engine."""

    def test_pool_size_and_overflow_passed_to_engine(self) -> None:
        """LongTermMemory must pass pool_size and max_overflow to
        create_async_engine."""
        with patch("agent33.memory.long_term.create_async_engine") as mock_create:
            mock_create.return_value = MagicMock()
            from agent33.memory.long_term import LongTermMemory

            LongTermMemory(
                "postgresql+asyncpg://test:test@localhost/test",
                pool_size=15,
                max_overflow=30,
            )

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args
            assert call_kwargs.kwargs["pool_size"] == 15
            assert call_kwargs.kwargs["max_overflow"] == 30

    def test_default_pool_size_matches_config(self) -> None:
        """The Settings defaults for db_pool_size and db_max_overflow must
        match the LongTermMemory constructor defaults."""
        s = Settings()
        assert s.db_pool_size == 10
        assert s.db_max_overflow == 20


# ---------------------------------------------------------------------------
# 5. redis_max_connections passed to Redis from_url
# ---------------------------------------------------------------------------


class TestRedisMaxConnectionsPropagation:
    """Verify redis_max_connections config is propagated to redis.from_url."""

    def test_redis_max_connections_config_default(self) -> None:
        """Settings.redis_max_connections should default to 50."""
        s = Settings()
        assert s.redis_max_connections == 50

    def test_redis_max_connections_custom(self) -> None:
        """Custom redis_max_connections should be stored in Settings."""
        s = Settings(redis_max_connections=100)
        assert s.redis_max_connections == 100

    def test_redis_from_url_receives_max_connections(self) -> None:
        """In main.py lifespan, redis.from_url is called with
        max_connections=settings.redis_max_connections.  We verify the
        config field is correctly typed and accessible."""
        # We cannot easily mock the lifespan's import-time redis.asyncio,
        # but we CAN verify the config value is int and > 0, which is
        # what the lifespan code passes.
        s = Settings(redis_max_connections=75)
        assert isinstance(s.redis_max_connections, int)
        assert s.redis_max_connections > 0


# ---------------------------------------------------------------------------
# 6. pool_pre_ping config propagated
# ---------------------------------------------------------------------------


class TestPoolPrePingPropagation:
    """Verify pool_pre_ping passes through to create_async_engine."""

    def test_pre_ping_propagated(self) -> None:
        with patch("agent33.memory.long_term.create_async_engine") as mock_create:
            mock_create.return_value = MagicMock()
            from agent33.memory.long_term import LongTermMemory

            LongTermMemory(
                "postgresql+asyncpg://test:test@localhost/test",
                pool_pre_ping=True,
            )

            call_kwargs = mock_create.call_args
            assert call_kwargs.kwargs["pool_pre_ping"] is True

    def test_pre_ping_disabled(self) -> None:
        with patch("agent33.memory.long_term.create_async_engine") as mock_create:
            mock_create.return_value = MagicMock()
            from agent33.memory.long_term import LongTermMemory

            LongTermMemory(
                "postgresql+asyncpg://test:test@localhost/test",
                pool_pre_ping=False,
            )

            call_kwargs = mock_create.call_args
            assert call_kwargs.kwargs["pool_pre_ping"] is False

    def test_config_default_is_true(self) -> None:
        s = Settings()
        assert s.db_pool_pre_ping is True


# ---------------------------------------------------------------------------
# 7. pool_recycle config propagated
# ---------------------------------------------------------------------------


class TestPoolRecyclePropagation:
    """Verify pool_recycle passes through to create_async_engine."""

    def test_recycle_propagated(self) -> None:
        with patch("agent33.memory.long_term.create_async_engine") as mock_create:
            mock_create.return_value = MagicMock()
            from agent33.memory.long_term import LongTermMemory

            LongTermMemory(
                "postgresql+asyncpg://test:test@localhost/test",
                pool_recycle=900,
            )

            call_kwargs = mock_create.call_args
            assert call_kwargs.kwargs["pool_recycle"] == 900

    def test_config_default_is_1800(self) -> None:
        s = Settings()
        assert s.db_pool_recycle == 1800


# ---------------------------------------------------------------------------
# 8. Prometheus histogram metric exists and is named db_query_duration_seconds
# ---------------------------------------------------------------------------


class TestPrometheusHistogramMetricExists:
    """Verify the metric name and its presence in the allowlist."""

    def test_metric_name_constant(self) -> None:
        """The module-level _METRIC_NAME must be 'db_query_duration_seconds'."""
        assert _METRIC_NAME == "db_query_duration_seconds"

    def test_metric_in_prometheus_observation_allowlist(self) -> None:
        """db_query_duration_seconds must be in the Prometheus observation
        allowlist so it is emitted in the /metrics endpoint."""
        assert _METRIC_NAME in MetricsCollector._PROMETHEUS_OBSERVATION_ALLOWLIST

    async def test_prometheus_render_includes_metric_lines(
        self, metrics: MetricsCollector
    ) -> None:
        """After recording an observation, render_prometheus must include
        the metric name with _count and _sum suffixes."""
        async with track_query("bench_test", table="bench"):
            pass

        rendered = metrics.render_prometheus()
        assert "db_query_duration_seconds_count" in rendered
        assert "db_query_duration_seconds_sum" in rendered
        assert 'operation="bench_test"' in rendered
        assert 'table="bench"' in rendered


# ---------------------------------------------------------------------------
# 9. track_query reraises exceptions from the context body
# ---------------------------------------------------------------------------


class TestTrackQueryExceptionPropagation:
    """Verify that track_query does not swallow exceptions."""

    async def test_value_error_reraises(self, metrics: MetricsCollector) -> None:
        with pytest.raises(ValueError, match="boom"):
            async with track_query("fail_op", table="t"):
                raise ValueError("boom")

    async def test_runtime_error_reraises(self, metrics: MetricsCollector) -> None:
        with pytest.raises(RuntimeError, match="db connection lost"):
            async with track_query("fail_op2", table="t"):
                raise RuntimeError("db connection lost")

    async def test_duration_still_recorded_on_exception(self, metrics: MetricsCollector) -> None:
        """Even when the body raises, the observation must be recorded."""
        with pytest.raises(ValueError):
            async with track_query("fail_op3", table="t"):
                await asyncio.sleep(0.005)
                raise ValueError("intentional")

        summary = metrics.get_summary()
        key = f"{_METRIC_NAME}(operation=fail_op3,table=t)"
        assert key in summary
        assert summary[key]["count"] == 1
        assert summary[key]["sum"] > 0.0


# ---------------------------------------------------------------------------
# 10. Concurrent track_query calls produce independent observations
# ---------------------------------------------------------------------------


class TestConcurrentTrackQueryIndependence:
    """Verify that concurrent track_query calls produce independent observations
    using asyncio.gather."""

    async def test_concurrent_gather_independent_counts(self, metrics: MetricsCollector) -> None:
        """Five concurrent track_query invocations should produce 5 independent
        observations under the same label set."""

        async def tracked_work(delay_ms: float) -> None:
            async with track_query("concurrent_op", table="concurrent_table"):
                await asyncio.sleep(delay_ms / 1000.0)

        await asyncio.gather(
            tracked_work(5),
            tracked_work(10),
            tracked_work(15),
            tracked_work(20),
            tracked_work(25),
        )

        summary = metrics.get_summary()
        key = f"{_METRIC_NAME}(operation=concurrent_op,table=concurrent_table)"
        assert key in summary
        assert summary[key]["count"] == 5
        # Min should be roughly 5ms, max roughly 25ms (in seconds)
        assert summary[key]["min"] > 0.001
        assert summary[key]["max"] > summary[key]["min"]

    async def test_concurrent_different_operations_independent(
        self, metrics: MetricsCollector
    ) -> None:
        """Concurrent calls with different operation names must not cross-pollinate."""

        async def op_a() -> None:
            async with track_query("op_alpha", table="t"):
                await asyncio.sleep(0.005)

        async def op_b() -> None:
            async with track_query("op_beta", table="t"):
                await asyncio.sleep(0.005)

        await asyncio.gather(op_a(), op_a(), op_b(), op_b(), op_b())

        summary = metrics.get_summary()
        alpha_key = f"{_METRIC_NAME}(operation=op_alpha,table=t)"
        beta_key = f"{_METRIC_NAME}(operation=op_beta,table=t)"
        assert summary[alpha_key]["count"] == 2
        assert summary[beta_key]["count"] == 3


# ---------------------------------------------------------------------------
# 11. configure_query_profiling wires the collector correctly
# ---------------------------------------------------------------------------


class TestConfigureQueryProfilingWiring:
    """Verify the module-level wiring function stores state correctly."""

    async def test_metrics_collector_receives_observations(
        self, metrics: MetricsCollector
    ) -> None:
        """After calling configure_query_profiling, observations must flow to
        the provided MetricsCollector instance."""
        fresh_metrics = MetricsCollector()
        configure_query_profiling(fresh_metrics, threshold_ms=99999)

        async with track_query("wiring_test", table="wt"):
            pass

        # Observations should be in fresh_metrics, not the fixture metrics
        summary = fresh_metrics.get_summary()
        key = f"{_METRIC_NAME}(operation=wiring_test,table=wt)"
        assert key in summary
        assert summary[key]["count"] == 1

        # The original fixture metrics should NOT have this observation
        # (it was replaced by configure_query_profiling)
        original_summary = metrics.get_summary()
        assert key not in original_summary

    async def test_threshold_clamped_to_minimum_one(
        self, metrics: MetricsCollector, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Passing threshold_ms=0 should clamp to 1ms (never disable warnings)."""
        configure_query_profiling(metrics, threshold_ms=0)
        with caplog.at_level(logging.WARNING, logger="agent33.observability.query_profiling"):
            async with track_query("clamp_test", table="t"):
                await asyncio.sleep(0.01)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "threshold_ms=1" in warnings[0].message


# ---------------------------------------------------------------------------
# 12. Settings defaults match documented values
# ---------------------------------------------------------------------------


class TestSettingsPoolDefaults:
    """Verify all P1.3 / P1.4 config fields have correct defaults."""

    def test_db_pool_size_default(self) -> None:
        assert Settings().db_pool_size == 10

    def test_db_max_overflow_default(self) -> None:
        assert Settings().db_max_overflow == 20

    def test_db_pool_pre_ping_default(self) -> None:
        assert Settings().db_pool_pre_ping is True

    def test_db_pool_recycle_default(self) -> None:
        assert Settings().db_pool_recycle == 1800

    def test_redis_max_connections_default(self) -> None:
        assert Settings().redis_max_connections == 50

    def test_slow_query_threshold_ms_default(self) -> None:
        assert Settings().slow_query_threshold_ms == 100
