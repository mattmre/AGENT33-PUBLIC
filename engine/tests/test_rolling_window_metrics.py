"""Tests for rolling-window observation tracking in MetricsCollector."""

from __future__ import annotations

import time
from unittest.mock import patch

from agent33.observability.metrics import MetricsCollector


class TestRollingWindowObservations:
    """Verify that observations within the window are included and older ones are not."""

    def test_observations_within_window_appear_in_window_avg(self) -> None:
        collector = MetricsCollector(window_seconds=300)
        collector.observe("latency", 1.0)
        collector.observe("latency", 3.0)

        summary = collector.get_summary()

        assert summary["latency"]["window_count"] == 2
        assert summary["latency"]["window_avg"] == 2.0
        assert summary["latency"]["window_min"] == 1.0
        assert summary["latency"]["window_max"] == 3.0
        assert summary["latency"]["window_sum"] == 4.0

    def test_observations_outside_window_excluded_from_window_stats(self) -> None:
        collector = MetricsCollector(window_seconds=60)

        # Inject an observation that appears to be 120 seconds old
        old_ts = time.time() - 120
        from agent33.observability.metrics import _TimestampedValue

        obs = collector._observations["latency"][""]
        obs.values.append(_TimestampedValue(timestamp=old_ts, value=10.0))

        # Add a recent observation normally
        collector.observe("latency", 2.0)

        summary = collector.get_summary()

        # Lifetime includes both
        assert summary["latency"]["count"] == 2
        assert summary["latency"]["avg"] == 6.0  # (10 + 2) / 2

        # Window includes only the recent one
        assert summary["latency"]["window_count"] == 1
        assert summary["latency"]["window_avg"] == 2.0
        assert summary["latency"]["window_min"] == 2.0
        assert summary["latency"]["window_max"] == 2.0

    def test_lifetime_stats_always_include_all_observations(self) -> None:
        collector = MetricsCollector(window_seconds=10)

        from agent33.observability.metrics import _TimestampedValue

        obs = collector._observations["cost"][""]
        # Add 3 old observations
        old_ts = time.time() - 100
        for v in [1.0, 2.0, 3.0]:
            obs.values.append(_TimestampedValue(timestamp=old_ts, value=v))

        # Add 1 recent
        collector.observe("cost", 4.0)

        summary = collector.get_summary()

        assert summary["cost"]["count"] == 4
        assert summary["cost"]["sum"] == 10.0
        assert summary["cost"]["avg"] == 2.5
        assert summary["cost"]["min"] == 1.0
        assert summary["cost"]["max"] == 4.0

    def test_zero_observations_in_window(self) -> None:
        collector = MetricsCollector(window_seconds=10)

        from agent33.observability.metrics import _TimestampedValue

        obs = collector._observations["cost"][""]
        old_ts = time.time() - 100
        obs.values.append(_TimestampedValue(timestamp=old_ts, value=5.0))

        summary = collector.get_summary()

        # Lifetime has the observation
        assert summary["cost"]["count"] == 1
        assert summary["cost"]["avg"] == 5.0

        # Window is empty
        assert summary["cost"]["window_count"] == 0
        assert summary["cost"]["window_avg"] == 0.0
        assert summary["cost"]["window_min"] == 0.0
        assert summary["cost"]["window_max"] == 0.0
        assert summary["cost"]["window_sum"] == 0.0


class TestRollingWindowConfig:
    """Verify configurable window_seconds."""

    def test_default_window_is_300_seconds(self) -> None:
        collector = MetricsCollector()
        assert collector.window_seconds == 300

    def test_custom_window_seconds(self) -> None:
        collector = MetricsCollector(window_seconds=60)
        assert collector.window_seconds == 60

    def test_window_boundary_uses_configured_value(self) -> None:
        """An observation exactly at the window edge should be included."""
        collector = MetricsCollector(window_seconds=30)

        from agent33.observability.metrics import _TimestampedValue

        obs = collector._observations["metric"][""]
        # Observation at exactly 29 seconds ago (inside 30s window)
        inside_ts = time.time() - 29
        obs.values.append(_TimestampedValue(timestamp=inside_ts, value=7.0))

        # Observation at 31 seconds ago (outside 30s window)
        outside_ts = time.time() - 31
        obs.values.append(_TimestampedValue(timestamp=outside_ts, value=99.0))

        summary = collector.get_summary()
        assert summary["metric"]["window_count"] == 1
        assert summary["metric"]["window_avg"] == 7.0


class TestCountersUnaffected:
    """Verify counters are not changed by the rolling-window feature."""

    def test_counters_remain_simple_integers(self) -> None:
        collector = MetricsCollector(window_seconds=60)
        collector.increment("my_counter")
        collector.increment("my_counter")
        collector.increment("my_counter")

        summary = collector.get_summary()
        assert summary["my_counter"] == 3

    def test_labelled_counters_remain_dict(self) -> None:
        collector = MetricsCollector(window_seconds=60)
        collector.increment("requests", labels={"method": "GET"})
        collector.increment("requests", labels={"method": "POST"})
        collector.increment("requests", labels={"method": "GET"})

        summary = collector.get_summary()
        assert summary["requests"] == {"method=GET": 2, "method=POST": 1}


class TestWindowMinMax:
    """Verify window_min and window_max are computed correctly."""

    def test_window_min_max_with_multiple_values(self) -> None:
        collector = MetricsCollector(window_seconds=300)
        for v in [5.0, 1.0, 8.0, 3.0]:
            collector.observe("score", v)

        summary = collector.get_summary()
        assert summary["score"]["window_min"] == 1.0
        assert summary["score"]["window_max"] == 8.0
        assert summary["score"]["window_count"] == 4

    def test_window_sum_matches_individual_values(self) -> None:
        collector = MetricsCollector(window_seconds=300)
        collector.observe("val", 2.5)
        collector.observe("val", 3.5)

        summary = collector.get_summary()
        assert summary["val"]["window_sum"] == 6.0


class TestPrometheusRenderingWithWindow:
    """Verify Prometheus exposition includes rolling-window gauges."""

    def test_prometheus_includes_window_gauges(self) -> None:
        collector = MetricsCollector(window_seconds=300)
        collector.observe("effort_routing_estimated_cost_usd", 0.5)

        output = collector.render_prometheus()

        # Lifetime gauges
        assert "effort_routing_estimated_cost_usd_avg " in output
        assert "effort_routing_estimated_cost_usd_count " in output

        # Window gauges
        assert "effort_routing_estimated_cost_usd_window_avg " in output
        assert "effort_routing_estimated_cost_usd_window_count " in output
        assert "effort_routing_estimated_cost_usd_window_min " in output
        assert "effort_routing_estimated_cost_usd_window_max " in output

    def test_prometheus_window_type_declarations(self) -> None:
        collector = MetricsCollector(window_seconds=300)
        collector.observe("effort_routing_estimated_cost_usd", 1.0)

        output = collector.render_prometheus()

        assert "# TYPE effort_routing_estimated_cost_usd_window_count gauge" in output
        assert "# TYPE effort_routing_estimated_cost_usd_window_avg gauge" in output
        assert "# TYPE effort_routing_estimated_cost_usd_window_min gauge" in output
        assert "# TYPE effort_routing_estimated_cost_usd_window_max gauge" in output

    def test_prometheus_window_values_exclude_old_observations(self) -> None:
        collector = MetricsCollector(window_seconds=60)

        from agent33.observability.metrics import _TimestampedValue

        obs = collector._observations["effort_routing_estimated_cost_usd"][""]
        old_ts = time.time() - 120
        obs.values.append(_TimestampedValue(timestamp=old_ts, value=10.0))
        collector.observe("effort_routing_estimated_cost_usd", 2.0)

        output = collector.render_prometheus()

        # Lifetime count should be 2
        assert "effort_routing_estimated_cost_usd_count 2" in output
        # Window count should be 1 (only the recent observation)
        assert "effort_routing_estimated_cost_usd_window_count 1" in output

    def test_prometheus_non_allowlisted_metric_excluded(self) -> None:
        collector = MetricsCollector(window_seconds=300)
        collector.observe("custom_metric", 1.0)

        output = collector.render_prometheus()

        assert "custom_metric" not in output

    def test_counters_unaffected_in_prometheus(self) -> None:
        collector = MetricsCollector(window_seconds=300)
        collector.increment("effort_routing_decisions_total")

        output = collector.render_prometheus()

        assert "# TYPE effort_routing_decisions_total counter" in output
        assert "effort_routing_decisions_total 1" in output
        # No window gauges for counters
        assert "effort_routing_decisions_total_window" not in output


class TestPruneWindow:
    """Verify the _prune_window method works correctly."""

    def test_prune_removes_old_entries(self) -> None:
        collector = MetricsCollector(window_seconds=60)

        from agent33.observability.metrics import _Observation, _TimestampedValue

        obs = _Observation()
        now = time.time()
        obs.values = [
            _TimestampedValue(timestamp=now - 120, value=1.0),
            _TimestampedValue(timestamp=now - 90, value=2.0),
            _TimestampedValue(timestamp=now - 30, value=3.0),
            _TimestampedValue(timestamp=now - 10, value=4.0),
        ]

        surviving = collector._prune_window(obs)

        assert len(surviving) == 2
        assert surviving[0].value == 3.0
        assert surviving[1].value == 4.0
        # Also modified in-place
        assert len(obs.values) == 2

    def test_prune_empty_observation(self) -> None:
        collector = MetricsCollector(window_seconds=60)

        from agent33.observability.metrics import _Observation

        obs = _Observation()
        surviving = collector._prune_window(obs)
        assert surviving == []
        assert obs.values == []


class TestLabelledObservationsWithWindow:
    """Verify rolling-window works correctly with labelled observations."""

    def test_labelled_observations_have_window_stats(self) -> None:
        collector = MetricsCollector(window_seconds=300)
        collector.observe("latency", 1.0, labels={"method": "GET"})
        collector.observe("latency", 5.0, labels={"method": "GET"})
        collector.observe("latency", 2.0, labels={"method": "POST"})

        summary = collector.get_summary()

        get_stats = summary["latency(method=GET)"]
        assert get_stats["count"] == 2
        assert get_stats["window_count"] == 2
        assert get_stats["window_avg"] == 3.0

        post_stats = summary["latency(method=POST)"]
        assert post_stats["count"] == 1
        assert post_stats["window_count"] == 1
        assert post_stats["window_avg"] == 2.0


class TestBackwardsCompatibility:
    """Ensure the summary shape is backwards-compatible with AlertManager."""

    def test_summary_retains_all_legacy_keys(self) -> None:
        collector = MetricsCollector(window_seconds=300)
        collector.observe("effort_routing_estimated_cost_usd", 0.5)
        collector.observe("effort_routing_estimated_cost_usd", 1.5)

        summary = collector.get_summary()
        entry = summary["effort_routing_estimated_cost_usd"]

        # Legacy keys that AlertManager._extract_value depends on
        assert "count" in entry
        assert "sum" in entry
        assert "avg" in entry
        assert "min" in entry
        assert "max" in entry

        assert entry["count"] == 2
        assert entry["sum"] == 2.0
        assert entry["avg"] == 1.0
        assert entry["min"] == 0.5
        assert entry["max"] == 1.5

    def test_alert_manager_still_works_with_new_summary_shape(self) -> None:
        """Integration check: AlertManager can read the updated summary."""
        from agent33.observability.alerts import AlertManager

        collector = MetricsCollector(window_seconds=300)
        collector.observe("effort_routing_estimated_cost_usd", 10.0)

        manager = AlertManager(collector)
        manager.add_rule(
            name="cost_spike",
            metric="effort_routing_estimated_cost_usd",
            threshold=5.0,
            comparator="gt",
            statistic="max",
        )

        alerts = manager.check_all()
        assert len(alerts) == 1
        assert alerts[0].rule_name == "cost_spike"
        assert alerts[0].current_value == 10.0


class TestTimestampedObserve:
    """Verify observe() stores timestamped values."""

    def test_observe_stores_timestamp(self) -> None:
        collector = MetricsCollector()
        before = time.time()
        collector.observe("metric", 42.0)
        after = time.time()

        obs = collector._observations["metric"][""]
        assert len(obs.values) == 1
        assert before <= obs.values[0].timestamp <= after
        assert obs.values[0].value == 42.0

    def test_observe_with_mocked_time(self) -> None:
        collector = MetricsCollector()
        fixed_time = 1000000.0
        with patch("agent33.observability.metrics.time") as mock_time:
            mock_time.time.return_value = fixed_time
            collector.observe("metric", 7.0)

        obs = collector._observations["metric"][""]
        assert obs.values[0].timestamp == fixed_time
        assert obs.values[0].value == 7.0
