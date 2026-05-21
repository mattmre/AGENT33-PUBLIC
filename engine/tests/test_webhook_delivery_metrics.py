"""Tests for webhook delivery and dead-letter metrics emission (P3.10)."""

from __future__ import annotations

from unittest.mock import patch

from agent33.automation.dead_letter import DeadLetterQueue
from agent33.automation.webhook_delivery import (
    DeliveryAttempt,
    WebhookDeliveryManager,
)
from agent33.observability.metrics import MetricsCollector


class TestWebhookDeliveryMetrics:
    """Verify WebhookDeliveryManager emits the correct metrics."""

    def setup_method(self) -> None:
        self.collector = MetricsCollector()
        self.manager = WebhookDeliveryManager(max_retries=3)

    def _enqueue_and_deliver(
        self,
        *,
        status_code: int = 200,
        duration_ms: float = 42.0,
    ) -> tuple[str, DeliveryAttempt]:
        """Helper: enqueue a webhook and build a delivery attempt."""
        delivery_id = self.manager.enqueue(
            webhook_id="hook-1",
            url="https://example.com/hook",
            payload={"event": "test"},
        )
        attempt = DeliveryAttempt(
            attempt_number=1,
            status_code=status_code,
            duration_ms=duration_ms,
        )
        return delivery_id, attempt

    def test_successful_delivery_increments_total_with_success_status(self) -> None:
        with patch("agent33.automation.webhook_delivery._metrics", self.collector):
            delivery_id, attempt = self._enqueue_and_deliver(status_code=200)
            self.manager.process_result(delivery_id, attempt)

        summary = self.collector.get_summary()
        # Counter keyed by label "status=success,webhook_id=hook-1"
        assert "webhook_delivery_total" in summary
        total_map = summary["webhook_delivery_total"]
        assert total_map["status=success,webhook_id=hook-1"] == 1

    def test_failed_delivery_increments_total_and_failures(self) -> None:
        with patch("agent33.automation.webhook_delivery._metrics", self.collector):
            delivery_id, attempt = self._enqueue_and_deliver(status_code=500)
            self.manager.process_result(delivery_id, attempt)

        summary = self.collector.get_summary()

        # Total counter with failure status
        total_map = summary["webhook_delivery_total"]
        assert total_map["status=failure,webhook_id=hook-1"] == 1

        # Failures counter
        failures_map = summary["webhook_delivery_failures_total"]
        assert failures_map["webhook_id=hook-1"] == 1

    def test_duration_observation_is_recorded(self) -> None:
        with patch("agent33.automation.webhook_delivery._metrics", self.collector):
            delivery_id, attempt = self._enqueue_and_deliver(status_code=200, duration_ms=150.0)
            self.manager.process_result(delivery_id, attempt)

        summary = self.collector.get_summary()
        # Duration is recorded in seconds (150ms -> 0.15s)
        obs_key = "webhook_delivery_duration_seconds(webhook_id=hook-1)"
        assert obs_key in summary
        assert summary[obs_key]["count"] == 1
        assert abs(summary[obs_key]["avg"] - 0.15) < 0.01

    def test_multiple_attempts_accumulate_counters(self) -> None:
        with patch("agent33.automation.webhook_delivery._metrics", self.collector):
            delivery_id = self.manager.enqueue(
                webhook_id="hook-2",
                url="https://example.com/hook",
                payload={},
            )

            # First attempt: failure
            attempt1 = DeliveryAttempt(attempt_number=1, status_code=500, duration_ms=10.0)
            self.manager.process_result(delivery_id, attempt1)

            # Second attempt: success
            attempt2 = DeliveryAttempt(attempt_number=2, status_code=200, duration_ms=20.0)
            self.manager.process_result(delivery_id, attempt2)

        summary = self.collector.get_summary()
        total_map = summary["webhook_delivery_total"]
        assert total_map["status=failure,webhook_id=hook-2"] == 1
        assert total_map["status=success,webhook_id=hook-2"] == 1

        failures_map = summary["webhook_delivery_failures_total"]
        assert failures_map["webhook_id=hook-2"] == 1

    def test_no_metrics_emitted_when_collector_not_set(self) -> None:
        """When _metrics is None, process_result still works without error."""
        with patch("agent33.automation.webhook_delivery._metrics", None):
            delivery_id, attempt = self._enqueue_and_deliver(status_code=200)
            self.manager.process_result(delivery_id, attempt)

        # Collector was not wired, so it should have no data
        summary = self.collector.get_summary()
        assert "webhook_delivery_total" not in summary

    def test_prometheus_rendering_includes_webhook_counters(self) -> None:
        with patch("agent33.automation.webhook_delivery._metrics", self.collector):
            delivery_id, attempt = self._enqueue_and_deliver(status_code=200)
            self.manager.process_result(delivery_id, attempt)

        output = self.collector.render_prometheus()
        assert "webhook_delivery_total" in output
        assert "webhook_delivery_duration_seconds" in output

    def test_prometheus_rendering_includes_failure_counter(self) -> None:
        with patch("agent33.automation.webhook_delivery._metrics", self.collector):
            delivery_id, attempt = self._enqueue_and_deliver(status_code=503)
            self.manager.process_result(delivery_id, attempt)

        output = self.collector.render_prometheus()
        assert "webhook_delivery_failures_total" in output


class TestDeadLetterQueueMetrics:
    """Verify DeadLetterQueue emits the correct metrics."""

    def setup_method(self) -> None:
        self.collector = MetricsCollector()
        self.dlq = DeadLetterQueue()

    def test_capture_increments_captures_total(self) -> None:
        with patch("agent33.automation.dead_letter._metrics", self.collector):
            self.dlq.capture(
                trigger_name="test-trigger",
                payload={"data": "value"},
                error="connection refused",
            )

        summary = self.collector.get_summary()
        assert summary["dead_letter_queue_captures_total"] == 1

    def test_capture_records_queue_depth(self) -> None:
        with patch("agent33.automation.dead_letter._metrics", self.collector):
            self.dlq.capture("trigger-a", {}, "err1")
            self.dlq.capture("trigger-b", {}, "err2")
            self.dlq.capture("trigger-c", {}, "err3")

        summary = self.collector.get_summary()
        assert summary["dead_letter_queue_captures_total"] == 3
        # The depth observation records the queue size after each capture
        assert "dead_letter_queue_depth" in summary
        depth_obs = summary["dead_letter_queue_depth"]
        assert depth_obs["count"] == 3
        # Depths should be 1.0, 2.0, 3.0 (queue grows with each capture)
        assert depth_obs["min"] == 1.0
        assert depth_obs["max"] == 3.0

    def test_no_metrics_emitted_when_collector_not_set(self) -> None:
        with patch("agent33.automation.dead_letter._metrics", None):
            item_id = self.dlq.capture("trigger", {}, "error")

        # Should still return a valid item_id
        assert item_id
        # Collector has no data
        summary = self.collector.get_summary()
        assert "dead_letter_queue_captures_total" not in summary

    def test_prometheus_rendering_includes_dead_letter_metrics(self) -> None:
        with patch("agent33.automation.dead_letter._metrics", self.collector):
            self.dlq.capture("trigger", {}, "err")

        output = self.collector.render_prometheus()
        assert "dead_letter_queue_captures_total" in output
        assert "dead_letter_queue_depth" in output
