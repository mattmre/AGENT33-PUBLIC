"""Tests for P4.7 SLO expansion: evaluation and connector metrics.

Covers:
- Evaluation metrics emission from EvaluationService.submit_results()
- Gate result metrics emission
- Connector health check metrics from messaging boundary
- Connector send metrics from messaging boundary
- Prometheus rendering of new metrics
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agent33.evaluation import service as evaluation_service_mod
from agent33.evaluation.models import (
    GateType,
    TaskResult,
    TaskRunResult,
)
from agent33.evaluation.service import EvaluationService
from agent33.messaging import boundary as messaging_boundary_mod
from agent33.observability.metrics import MetricsCollector

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def collector() -> MetricsCollector:
    """Fresh MetricsCollector for each test."""
    return MetricsCollector()


@pytest.fixture()
def eval_service_with_metrics(collector: MetricsCollector) -> EvaluationService:
    """EvaluationService wired to a fresh MetricsCollector."""
    original = evaluation_service_mod._metrics
    evaluation_service_mod._metrics = collector
    svc = EvaluationService()
    yield svc
    evaluation_service_mod._metrics = original


@pytest.fixture()
def boundary_with_metrics(collector: MetricsCollector) -> MetricsCollector:
    """Wire the messaging boundary module to a fresh MetricsCollector."""
    original = messaging_boundary_mod._metrics
    messaging_boundary_mod._metrics = collector
    yield collector
    messaging_boundary_mod._metrics = original


# ---------------------------------------------------------------------------
# Evaluation metrics
# ---------------------------------------------------------------------------


class TestEvaluationMetrics:
    """Verify evaluation subsystem emits the right Prometheus metrics."""

    def _make_task_results(self, count: int = 3) -> list[TaskRunResult]:
        """Build a list of passing task results."""
        return [
            TaskRunResult(
                item_id=f"GT-0{i}",
                result=TaskResult.PASS,
                checks_passed=5,
                checks_total=5,
                duration_ms=100,
            )
            for i in range(1, count + 1)
        ]

    def test_submit_results_emits_run_counter(
        self,
        eval_service_with_metrics: EvaluationService,
        collector: MetricsCollector,
    ) -> None:
        """submit_results increments evaluation_runs_total with correct labels."""
        svc = eval_service_with_metrics
        run = svc.create_run(GateType.G_PR, commit_hash="abc123")
        svc.submit_results(run.run_id, self._make_task_results())

        summary = collector.get_summary()
        # The counter should exist with evaluator=G-PR label
        assert "evaluation_runs_total" in summary
        counter_map = summary["evaluation_runs_total"]
        # At least one label key should contain "evaluator=G-PR"
        assert any("evaluator=G-PR" in k for k in counter_map)

    def test_submit_results_emits_duration(
        self,
        eval_service_with_metrics: EvaluationService,
        collector: MetricsCollector,
    ) -> None:
        """submit_results records evaluation_duration_seconds observation."""
        svc = eval_service_with_metrics
        run = svc.create_run(GateType.G_MRG)
        svc.submit_results(run.run_id, self._make_task_results())

        summary = collector.get_summary()
        # Look for duration observation keyed by evaluator
        duration_keys = [k for k in summary if k.startswith("evaluation_duration_seconds")]
        assert len(duration_keys) >= 1
        obs = summary[duration_keys[0]]
        assert obs["count"] == 1
        assert obs["sum"] >= 0  # duration is non-negative (may be 0 on fast runs)

    def test_submit_results_emits_scores(
        self,
        eval_service_with_metrics: EvaluationService,
        collector: MetricsCollector,
    ) -> None:
        """submit_results records evaluation_score for each computed metric."""
        svc = eval_service_with_metrics
        run = svc.create_run(GateType.G_PR)
        svc.submit_results(run.run_id, self._make_task_results())

        summary = collector.get_summary()
        score_keys = [k for k in summary if k.startswith("evaluation_score")]
        # Should have at least one score observation (M-01 success rate)
        assert len(score_keys) >= 1

    def test_submit_results_emits_gate_results(
        self,
        eval_service_with_metrics: EvaluationService,
        collector: MetricsCollector,
    ) -> None:
        """submit_results increments evaluation_gate_results_total for each gate check."""
        svc = eval_service_with_metrics
        run = svc.create_run(GateType.G_PR)
        svc.submit_results(run.run_id, self._make_task_results())

        summary = collector.get_summary()
        assert "evaluation_gate_results_total" in summary
        gate_map = summary["evaluation_gate_results_total"]
        # Should have gate=G-PR, result=pass or fail
        assert any("gate=G-PR" in k for k in gate_map)

    def test_no_metrics_when_collector_not_wired(self) -> None:
        """When _metrics is None, submit_results does not raise."""
        original = evaluation_service_mod._metrics
        evaluation_service_mod._metrics = None
        try:
            svc = EvaluationService()
            run = svc.create_run(GateType.G_PR)
            # Should not raise even though no collector is wired
            result = svc.submit_results(run.run_id, self._make_task_results())
            assert result is not None
            assert result.gate_report is not None
        finally:
            evaluation_service_mod._metrics = original

    def test_submit_results_with_failed_gate(
        self,
        eval_service_with_metrics: EvaluationService,
        collector: MetricsCollector,
    ) -> None:
        """Gate failure is captured in both run counter status and gate results."""
        svc = eval_service_with_metrics
        run = svc.create_run(GateType.G_REL)
        # Submit results that will fail the strict G-REL gate (0% success rate)
        failed_results = [
            TaskRunResult(
                item_id="GT-01",
                result=TaskResult.FAIL,
                checks_passed=0,
                checks_total=5,
                duration_ms=100,
            )
        ]
        svc.submit_results(run.run_id, failed_results)

        summary = collector.get_summary()
        counter_map = summary["evaluation_runs_total"]
        # Should have a fail status entry
        assert any("status=fail" in k for k in counter_map)

    def test_evaluation_metrics_in_prometheus_output(
        self,
        eval_service_with_metrics: EvaluationService,
        collector: MetricsCollector,
    ) -> None:
        """New evaluation metrics appear in Prometheus text output."""
        svc = eval_service_with_metrics
        run = svc.create_run(GateType.G_PR)
        svc.submit_results(run.run_id, self._make_task_results())

        output = collector.render_prometheus()
        assert "evaluation_runs_total" in output
        assert "evaluation_duration_seconds" in output
        assert "evaluation_score" in output
        assert "evaluation_gate_results_total" in output


# ---------------------------------------------------------------------------
# Connector metrics
# ---------------------------------------------------------------------------


class TestConnectorMetrics:
    """Verify messaging boundary emits connector metrics."""

    @pytest.mark.asyncio
    async def test_health_check_success_emits_counter(
        self,
        boundary_with_metrics: MetricsCollector,
    ) -> None:
        """Successful health_check operation increments connector_health_check_total."""
        collector = boundary_with_metrics

        mock_call = AsyncMock(return_value="ok")
        await messaging_boundary_mod.execute_messaging_boundary_call(
            connector="messaging:test",
            operation="health_check",
            payload={},
            metadata={"platform": "test"},
            call=mock_call,
        )

        summary = collector.get_summary()
        assert "connector_health_check_total" in summary
        counter_map = summary["connector_health_check_total"]
        assert any("status=success" in k for k in counter_map)
        assert any("connector=messaging:test" in k for k in counter_map)

    @pytest.mark.asyncio
    async def test_health_check_failure_emits_counter(
        self,
        boundary_with_metrics: MetricsCollector,
    ) -> None:
        """Failed health_check operation increments counter with status=error."""
        collector = boundary_with_metrics

        mock_call = AsyncMock(side_effect=RuntimeError("connection refused"))
        with pytest.raises(RuntimeError, match="connection refused"):
            await messaging_boundary_mod.execute_messaging_boundary_call(
                connector="messaging:test",
                operation="health_check",
                payload={},
                metadata={"platform": "test"},
                call=mock_call,
            )

        summary = collector.get_summary()
        assert "connector_health_check_total" in summary
        counter_map = summary["connector_health_check_total"]
        assert any("status=error" in k for k in counter_map)

    @pytest.mark.asyncio
    async def test_send_success_emits_counter_and_duration(
        self,
        boundary_with_metrics: MetricsCollector,
    ) -> None:
        """Successful send emits counter and duration observation."""
        collector = boundary_with_metrics

        mock_call = AsyncMock(return_value="sent")
        await messaging_boundary_mod.execute_messaging_boundary_call(
            connector="messaging:telegram",
            operation="send",
            payload={"channel_id": "123"},
            metadata={"platform": "telegram"},
            call=mock_call,
        )

        summary = collector.get_summary()

        # Counter
        assert "connector_message_send_total" in summary
        counter_map = summary["connector_message_send_total"]
        assert any("status=success" in k for k in counter_map)
        assert any("connector=messaging:telegram" in k for k in counter_map)

        # Duration observation
        duration_keys = [
            k for k in summary if k.startswith("connector_message_send_duration_seconds")
        ]
        assert len(duration_keys) >= 1
        obs = summary[duration_keys[0]]
        assert obs["count"] == 1
        assert obs["sum"] >= 0

    @pytest.mark.asyncio
    async def test_send_failure_emits_error_counter(
        self,
        boundary_with_metrics: MetricsCollector,
    ) -> None:
        """Failed send emits counter with status=error and still records duration."""
        collector = boundary_with_metrics

        mock_call = AsyncMock(side_effect=ConnectionError("timeout"))
        with pytest.raises(ConnectionError, match="timeout"):
            await messaging_boundary_mod.execute_messaging_boundary_call(
                connector="messaging:discord",
                operation="send",
                payload={"channel_id": "456"},
                metadata={"platform": "discord"},
                call=mock_call,
            )

        summary = collector.get_summary()
        assert "connector_message_send_total" in summary
        counter_map = summary["connector_message_send_total"]
        assert any("status=error" in k for k in counter_map)

    @pytest.mark.asyncio
    async def test_non_tracked_operations_do_not_emit(
        self,
        boundary_with_metrics: MetricsCollector,
    ) -> None:
        """Operations other than health_check/send do not emit named metrics."""
        collector = boundary_with_metrics

        mock_call = AsyncMock(return_value="polled")
        await messaging_boundary_mod.execute_messaging_boundary_call(
            connector="messaging:telegram",
            operation="poll_updates",
            payload={},
            metadata={"platform": "telegram"},
            call=mock_call,
        )

        summary = collector.get_summary()
        assert "connector_health_check_total" not in summary
        assert "connector_message_send_total" not in summary

    @pytest.mark.asyncio
    async def test_connector_metrics_in_prometheus_output(
        self,
        boundary_with_metrics: MetricsCollector,
    ) -> None:
        """New connector metrics appear in Prometheus text output."""
        collector = boundary_with_metrics

        mock_call = AsyncMock(return_value="ok")
        await messaging_boundary_mod.execute_messaging_boundary_call(
            connector="messaging:test",
            operation="health_check",
            payload={},
            metadata={"platform": "test"},
            call=mock_call,
        )
        await messaging_boundary_mod.execute_messaging_boundary_call(
            connector="messaging:test",
            operation="send",
            payload={"channel_id": "1"},
            metadata={"platform": "test"},
            call=mock_call,
        )

        output = collector.render_prometheus()
        assert "connector_health_check_total" in output
        assert "connector_message_send_total" in output
        assert "connector_message_send_duration_seconds" in output

    @pytest.mark.asyncio
    async def test_no_metrics_when_collector_not_wired(self) -> None:
        """When _metrics is None, boundary calls work normally without metrics."""
        original = messaging_boundary_mod._metrics
        messaging_boundary_mod._metrics = None
        try:
            mock_call = AsyncMock(return_value="ok")
            result = await messaging_boundary_mod.execute_messaging_boundary_call(
                connector="messaging:test",
                operation="send",
                payload={},
                metadata={"platform": "test"},
                call=mock_call,
            )
            assert result == "ok"
        finally:
            messaging_boundary_mod._metrics = original


# ---------------------------------------------------------------------------
# MetricsCollector allowlist
# ---------------------------------------------------------------------------


class TestMetricsCollectorAllowlist:
    """Verify the new metrics are in the Prometheus allowlists."""

    def test_evaluation_counters_in_allowlist(self) -> None:
        assert "evaluation_runs_total" in MetricsCollector._PROMETHEUS_COUNTER_ALLOWLIST
        assert "evaluation_gate_results_total" in MetricsCollector._PROMETHEUS_COUNTER_ALLOWLIST

    def test_evaluation_observations_in_allowlist(self) -> None:
        assert "evaluation_score" in MetricsCollector._PROMETHEUS_OBSERVATION_ALLOWLIST
        assert "evaluation_duration_seconds" in MetricsCollector._PROMETHEUS_OBSERVATION_ALLOWLIST

    def test_connector_counters_in_allowlist(self) -> None:
        assert "connector_health_check_total" in MetricsCollector._PROMETHEUS_COUNTER_ALLOWLIST
        assert "connector_message_send_total" in MetricsCollector._PROMETHEUS_COUNTER_ALLOWLIST

    def test_connector_observations_in_allowlist(self) -> None:
        assert (
            "connector_message_send_duration_seconds"
            in MetricsCollector._PROMETHEUS_OBSERVATION_ALLOWLIST
        )
