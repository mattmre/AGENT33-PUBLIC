"""Tests for scheduled evaluation gates (S45).

Covers:
- Config validation (cron vs interval mutual exclusion, defaults)
- Service CRUD (create, remove, list, get, max schedules)
- Execution (trigger creates run, computes metrics, checks gate, records history)
- Auto-baseline behavior
- Error handling (dead result on failure)
- History (bounded retention, ordering)
- API routes (all 6 endpoints + auth + 503 when disabled)
- Lifecycle (start/stop)
"""

from __future__ import annotations

import pytest

from agent33.evaluation.models import (
    GateResult,
    GateType,
    MetricId,
)
from agent33.evaluation.scheduled_gates import (
    ScheduledGateConfig,
    ScheduledGateHistory,
    ScheduledGateResult,
    ScheduledGateService,
    ScheduleType,
)
from agent33.evaluation.service import EvaluationService
from agent33.security.auth import create_access_token

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def eval_service() -> EvaluationService:
    """Fresh evaluation service for each test."""
    return EvaluationService()


@pytest.fixture()
def gate_service(eval_service: EvaluationService) -> ScheduledGateService:
    """Fresh scheduled gate service (not started) for each test."""
    return ScheduledGateService(
        evaluation_service=eval_service,
        max_schedules=5,
        history_retention=10,
    )


def _cron_config(**overrides: object) -> ScheduledGateConfig:
    """Helper to build a cron schedule config with sensible defaults."""
    defaults: dict[str, object] = {
        "schedule_type": ScheduleType.CRON,
        "cron_expr": "*/5 * * * *",
        "gate_type": GateType.G_MON,
    }
    defaults.update(overrides)
    return ScheduledGateConfig(**defaults)  # type: ignore[arg-type]


def _interval_config(**overrides: object) -> ScheduledGateConfig:
    """Helper to build an interval schedule config."""
    defaults: dict[str, object] = {
        "schedule_type": ScheduleType.INTERVAL,
        "interval_seconds": 300,
        "gate_type": GateType.G_MON,
    }
    defaults.update(overrides)
    return ScheduledGateConfig(**defaults)  # type: ignore[arg-type]


def _build_test_app():
    """Build a fresh FastAPI app with auth middleware and the scheduled gates router."""
    from fastapi import FastAPI

    from agent33.api.routes import scheduled_gates as routes_mod
    from agent33.security.middleware import AuthMiddleware

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(routes_mod.router)
    return app


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestScheduledGateModels:
    """Validate model defaults and behaviour."""

    def test_config_defaults(self) -> None:
        config = ScheduledGateConfig()
        assert config.gate_type == GateType.G_MON
        assert config.schedule_type == ScheduleType.CRON
        assert config.enabled is True
        assert config.auto_baseline is False
        assert config.schedule_id  # UUID was generated

    def test_config_custom_values(self) -> None:
        config = ScheduledGateConfig(
            gate_type=GateType.G_PR,
            schedule_type=ScheduleType.INTERVAL,
            interval_seconds=60,
            auto_baseline=True,
            enabled=False,
        )
        assert config.gate_type == GateType.G_PR
        assert config.schedule_type == ScheduleType.INTERVAL
        assert config.interval_seconds == 60
        assert config.auto_baseline is True
        assert config.enabled is False

    def test_result_defaults(self) -> None:
        result = ScheduledGateResult(schedule_id="test-123")
        assert result.schedule_id == "test-123"
        assert result.gate_result == GateResult.PASS
        assert result.regressions_found == 0
        assert result.error is None
        assert result.executed_at is not None

    def test_history_add_result(self) -> None:
        history = ScheduledGateHistory(schedule_id="test", max_history=3)
        for i in range(5):
            history.add_result(ScheduledGateResult(schedule_id="test", run_id=f"run-{i}"))
        assert len(history.results) == 3
        # Most recent 3 should survive
        assert history.results[0].run_id == "run-2"
        assert history.results[1].run_id == "run-3"
        assert history.results[2].run_id == "run-4"

    def test_history_bounded_retention(self) -> None:
        history = ScheduledGateHistory(schedule_id="test", max_history=2)
        history.add_result(ScheduledGateResult(schedule_id="test", run_id="a"))
        history.add_result(ScheduledGateResult(schedule_id="test", run_id="b"))
        history.add_result(ScheduledGateResult(schedule_id="test", run_id="c"))
        assert len(history.results) == 2
        assert history.results[-1].run_id == "c"


# ---------------------------------------------------------------------------
# Config validation tests
# ---------------------------------------------------------------------------


class TestConfigValidation:
    """Test that create_schedule enforces cron/interval mutual exclusion."""

    def test_cron_without_expr_rejected(self, gate_service: ScheduledGateService) -> None:
        config = ScheduledGateConfig(
            schedule_type=ScheduleType.CRON,
            cron_expr=None,
        )
        with pytest.raises(ValueError, match="cron_expr is required"):
            gate_service.create_schedule(config)

    def test_cron_with_interval_seconds_rejected(self, gate_service: ScheduledGateService) -> None:
        config = ScheduledGateConfig(
            schedule_type=ScheduleType.CRON,
            cron_expr="*/5 * * * *",
            interval_seconds=60,
        )
        with pytest.raises(ValueError, match="interval_seconds must not be set"):
            gate_service.create_schedule(config)

    def test_interval_without_seconds_rejected(self, gate_service: ScheduledGateService) -> None:
        config = ScheduledGateConfig(
            schedule_type=ScheduleType.INTERVAL,
            interval_seconds=None,
        )
        with pytest.raises(ValueError, match="interval_seconds must be a positive"):
            gate_service.create_schedule(config)

    def test_interval_with_zero_seconds_rejected(self, gate_service: ScheduledGateService) -> None:
        config = ScheduledGateConfig(
            schedule_type=ScheduleType.INTERVAL,
            interval_seconds=0,
        )
        with pytest.raises(ValueError, match="interval_seconds must be a positive"):
            gate_service.create_schedule(config)

    def test_interval_with_negative_seconds_rejected(
        self, gate_service: ScheduledGateService
    ) -> None:
        config = ScheduledGateConfig(
            schedule_type=ScheduleType.INTERVAL,
            interval_seconds=-10,
        )
        with pytest.raises(ValueError, match="interval_seconds must be a positive"):
            gate_service.create_schedule(config)

    def test_interval_with_cron_expr_rejected(self, gate_service: ScheduledGateService) -> None:
        config = ScheduledGateConfig(
            schedule_type=ScheduleType.INTERVAL,
            interval_seconds=60,
            cron_expr="*/5 * * * *",
        )
        with pytest.raises(ValueError, match="cron_expr must not be set"):
            gate_service.create_schedule(config)

    def test_valid_cron_accepted(self, gate_service: ScheduledGateService) -> None:
        config = _cron_config()
        created = gate_service.create_schedule(config)
        assert created.schedule_id == config.schedule_id
        assert created.cron_expr == "*/5 * * * *"

    def test_cron_with_wrong_field_count_rejected(
        self, gate_service: ScheduledGateService
    ) -> None:
        config = ScheduledGateConfig(
            schedule_type=ScheduleType.CRON,
            cron_expr="not a cron",
        )
        with pytest.raises(ValueError, match="Invalid cron_expr"):
            gate_service.create_schedule(config)

    def test_cron_with_out_of_range_value_rejected(
        self, gate_service: ScheduledGateService
    ) -> None:
        config = ScheduledGateConfig(
            schedule_type=ScheduleType.CRON,
            cron_expr="61 * * * *",
        )
        with pytest.raises(ValueError, match="Invalid cron_expr"):
            gate_service.create_schedule(config)

    def test_valid_interval_accepted(self, gate_service: ScheduledGateService) -> None:
        config = _interval_config()
        created = gate_service.create_schedule(config)
        assert created.schedule_id == config.schedule_id
        assert created.interval_seconds == 300


# ---------------------------------------------------------------------------
# CRUD tests
# ---------------------------------------------------------------------------


class TestServiceCRUD:
    """Test create, list, get, remove operations."""

    def test_create_and_get(self, gate_service: ScheduledGateService) -> None:
        config = _cron_config()
        gate_service.create_schedule(config)
        retrieved = gate_service.get_schedule(config.schedule_id)
        assert retrieved is not None
        assert retrieved.schedule_id == config.schedule_id
        assert retrieved.gate_type == GateType.G_MON

    def test_list_schedules(self, gate_service: ScheduledGateService) -> None:
        gate_service.create_schedule(_cron_config())
        gate_service.create_schedule(_interval_config())
        schedules = gate_service.list_schedules()
        assert len(schedules) == 2

    def test_remove_existing(self, gate_service: ScheduledGateService) -> None:
        config = _cron_config()
        gate_service.create_schedule(config)
        assert gate_service.remove_schedule(config.schedule_id) is True
        assert gate_service.get_schedule(config.schedule_id) is None
        assert gate_service.list_schedules() == []

    def test_remove_nonexistent(self, gate_service: ScheduledGateService) -> None:
        assert gate_service.remove_schedule("does-not-exist") is False

    def test_get_nonexistent(self, gate_service: ScheduledGateService) -> None:
        assert gate_service.get_schedule("does-not-exist") is None

    def test_max_schedules_enforced(self, gate_service: ScheduledGateService) -> None:
        # max_schedules is 5 in fixture
        for _ in range(5):
            gate_service.create_schedule(_cron_config())
        with pytest.raises(ValueError, match="Maximum number of schedules"):
            gate_service.create_schedule(_cron_config())

    def test_remove_frees_slot_for_new(self, gate_service: ScheduledGateService) -> None:
        configs = []
        for _ in range(5):
            c = _cron_config()
            gate_service.create_schedule(c)
            configs.append(c)
        gate_service.remove_schedule(configs[0].schedule_id)
        # Should now be able to create one more
        gate_service.create_schedule(_cron_config())
        assert len(gate_service.list_schedules()) == 5


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


class TestLifecycle:
    """Test start/stop lifecycle."""

    async def test_start_stop(self, gate_service: ScheduledGateService) -> None:
        assert gate_service.running is False
        await gate_service.start()
        assert gate_service.running is True
        await gate_service.stop()
        assert gate_service.running is False

    async def test_double_start_is_idempotent(self, gate_service: ScheduledGateService) -> None:
        await gate_service.start()
        await gate_service.start()  # should not raise
        assert gate_service.running is True
        await gate_service.stop()

    async def test_double_stop_is_idempotent(self, gate_service: ScheduledGateService) -> None:
        await gate_service.start()
        await gate_service.stop()
        await gate_service.stop()  # should not raise
        assert gate_service.running is False


# ---------------------------------------------------------------------------
# Execution tests
# ---------------------------------------------------------------------------


class TestExecution:
    """Test trigger_now and gate execution logic."""

    async def test_trigger_creates_run_and_computes_metrics(
        self, gate_service: ScheduledGateService
    ) -> None:
        config = _cron_config()
        gate_service.create_schedule(config)
        result = await gate_service.trigger_now(config.schedule_id)

        assert result.schedule_id == config.schedule_id
        assert result.run_id  # non-empty
        assert result.gate_result in (GateResult.PASS, GateResult.WARN, GateResult.FAIL)
        assert result.error is None
        # Metrics should contain at least M-01 (success rate)
        assert "M-01" in result.metrics or MetricId.M_01.value in result.metrics

    async def test_trigger_nonexistent_schedule_raises(
        self, gate_service: ScheduledGateService
    ) -> None:
        with pytest.raises(ValueError, match="Schedule not found"):
            await gate_service.trigger_now("no-such-id")

    async def test_trigger_records_history(self, gate_service: ScheduledGateService) -> None:
        config = _cron_config()
        gate_service.create_schedule(config)
        await gate_service.trigger_now(config.schedule_id)
        await gate_service.trigger_now(config.schedule_id)

        history = gate_service.get_history(config.schedule_id)
        assert len(history) == 2
        # History is newest first
        assert history[0].executed_at >= history[1].executed_at

    async def test_trigger_with_task_filter(self, gate_service: ScheduledGateService) -> None:
        config = _cron_config(task_filter=["GT-01"])
        gate_service.create_schedule(config)
        result = await gate_service.trigger_now(config.schedule_id)
        assert result.error is None
        # The result should reflect metrics from the filtered task set
        assert result.metrics  # should have some metrics

    async def test_trigger_with_g_pr_gate(self, gate_service: ScheduledGateService) -> None:
        """Verify a non-G-MON gate type also works through the pipeline."""
        config = _cron_config(gate_type=GateType.G_PR)
        gate_service.create_schedule(config)
        result = await gate_service.trigger_now(config.schedule_id)
        assert result.error is None
        assert result.gate_result in (GateResult.PASS, GateResult.WARN, GateResult.FAIL)

    async def test_metrics_include_expected_keys(self, gate_service: ScheduledGateService) -> None:
        """Verify that metrics dict includes the standard metric IDs."""
        config = _cron_config()
        gate_service.create_schedule(config)
        result = await gate_service.trigger_now(config.schedule_id)
        # MetricsCalculator computes M-01..M-05 for any non-empty result set
        expected_keys = {"M-01", "M-02", "M-03", "M-04", "M-05"}
        assert expected_keys.issubset(set(result.metrics.keys()))


# ---------------------------------------------------------------------------
# Auto-baseline tests
# ---------------------------------------------------------------------------


class TestAutoBaseline:
    """Test auto-baseline creation on passing gate."""

    async def test_auto_baseline_saves_on_pass(
        self, eval_service: EvaluationService, gate_service: ScheduledGateService
    ) -> None:
        # With auto_baseline=True, a passing gate should save a baseline
        config = _cron_config(auto_baseline=True, task_filter=["GT-01"])
        gate_service.create_schedule(config)
        result = await gate_service.trigger_now(config.schedule_id)

        baselines = eval_service.list_baselines()
        if result.gate_result == GateResult.PASS:
            assert len(baselines) >= 1
            assert baselines[0].commit_hash == "scheduled-gate"
        # If gate failed (deterministic evaluator), no baseline saved -- still valid

    async def test_no_baseline_when_disabled(
        self, eval_service: EvaluationService, gate_service: ScheduledGateService
    ) -> None:
        config = _cron_config(auto_baseline=False)
        gate_service.create_schedule(config)
        await gate_service.trigger_now(config.schedule_id)

        baselines = eval_service.list_baselines()
        assert len(baselines) == 0


# ---------------------------------------------------------------------------
# History tests
# ---------------------------------------------------------------------------


class TestHistory:
    """Test history retrieval and bounded retention."""

    async def test_get_history_empty(self, gate_service: ScheduledGateService) -> None:
        config = _cron_config()
        gate_service.create_schedule(config)
        history = gate_service.get_history(config.schedule_id)
        assert history == []

    async def test_get_history_nonexistent_schedule(
        self, gate_service: ScheduledGateService
    ) -> None:
        history = gate_service.get_history("does-not-exist")
        assert history == []

    async def test_history_respects_limit(self, gate_service: ScheduledGateService) -> None:
        config = _cron_config()
        gate_service.create_schedule(config)
        for _ in range(5):
            await gate_service.trigger_now(config.schedule_id)

        history = gate_service.get_history(config.schedule_id, limit=3)
        assert len(history) == 3

    async def test_history_newest_first(self, gate_service: ScheduledGateService) -> None:
        config = _cron_config()
        gate_service.create_schedule(config)
        for _ in range(3):
            await gate_service.trigger_now(config.schedule_id)

        history = gate_service.get_history(config.schedule_id)
        for i in range(len(history) - 1):
            assert history[i].executed_at >= history[i + 1].executed_at

    async def test_history_bounded_by_retention(
        self,
    ) -> None:
        """History retention=3 should keep only 3 most recent results."""
        eval_svc = EvaluationService()
        svc = ScheduledGateService(
            evaluation_service=eval_svc,
            max_schedules=10,
            history_retention=3,
        )
        config = _cron_config()
        svc.create_schedule(config)

        for _ in range(5):
            await svc.trigger_now(config.schedule_id)

        history = svc.get_history(config.schedule_id, limit=100)
        assert len(history) == 3

    async def test_history_removed_with_schedule(self, gate_service: ScheduledGateService) -> None:
        config = _cron_config()
        gate_service.create_schedule(config)
        await gate_service.trigger_now(config.schedule_id)
        gate_service.remove_schedule(config.schedule_id)
        # History should be gone
        history = gate_service.get_history(config.schedule_id)
        assert history == []


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Test that errors during execution produce proper error results."""

    async def test_execution_error_records_failed_result(
        self,
    ) -> None:
        """Simulate a failure in the evaluation service."""
        eval_svc = EvaluationService()

        svc = ScheduledGateService(
            evaluation_service=eval_svc,
            max_schedules=10,
            history_retention=10,
        )
        config = _cron_config()
        svc.create_schedule(config)

        # Monkey-patch the evaluation service to raise
        original_create_run = eval_svc.create_run

        def broken_create_run(*a: object, **kw: object) -> None:
            raise RuntimeError("database is down")

        eval_svc.create_run = broken_create_run  # type: ignore[assignment]

        result = await svc.trigger_now(config.schedule_id)
        assert result.gate_result == GateResult.FAIL
        assert result.error is not None
        assert "database is down" in result.error

        # Restore
        eval_svc.create_run = original_create_run  # type: ignore[assignment]

    async def test_execute_gate_with_missing_schedule(
        self,
    ) -> None:
        """_execute_gate with unknown schedule_id produces error result."""
        eval_svc = EvaluationService()
        svc = ScheduledGateService(
            evaluation_service=eval_svc,
            max_schedules=10,
            history_retention=10,
        )
        # Directly call internal method with bad ID
        result = await svc._execute_gate("nonexistent")
        assert result.gate_result == GateResult.FAIL
        assert result.error == "Schedule not found"


# ---------------------------------------------------------------------------
# G-MON threshold tests
# ---------------------------------------------------------------------------


class TestGMONThresholds:
    """Verify the G-MON thresholds were added to DEFAULT_THRESHOLDS."""

    def test_gmon_thresholds_exist(self) -> None:
        from agent33.evaluation.gates import GateEnforcer

        enforcer = GateEnforcer()
        gmon_thresholds = enforcer.get_thresholds_for_gate(GateType.G_MON)
        assert len(gmon_thresholds) == 2

        metric_ids = {t.metric_id for t in gmon_thresholds}
        assert MetricId.M_01 in metric_ids
        assert MetricId.M_03 in metric_ids

    def test_gmon_m01_threshold_value(self) -> None:
        from agent33.evaluation.gates import GateEnforcer

        enforcer = GateEnforcer()
        gmon_thresholds = enforcer.get_thresholds_for_gate(GateType.G_MON)
        m01 = next(t for t in gmon_thresholds if t.metric_id == MetricId.M_01)
        assert m01.value == 85.0
        assert m01.action.value == "warn"

    def test_gmon_m03_threshold_value(self) -> None:
        from agent33.evaluation.gates import GateEnforcer

        enforcer = GateEnforcer()
        gmon_thresholds = enforcer.get_thresholds_for_gate(GateType.G_MON)
        m03 = next(t for t in gmon_thresholds if t.metric_id == MetricId.M_03)
        assert m03.value == 25.0
        assert m03.action.value == "warn"

    def test_gmon_gate_check_passes_with_good_metrics(self) -> None:
        from agent33.evaluation.gates import GateEnforcer

        enforcer = GateEnforcer()
        report = enforcer.check_gate(
            GateType.G_MON,
            {MetricId.M_01: 90.0, MetricId.M_03: 10.0},
        )
        assert report.overall == GateResult.PASS

    def test_gmon_gate_check_warns_with_low_success(self) -> None:
        from agent33.evaluation.gates import GateEnforcer

        enforcer = GateEnforcer()
        report = enforcer.check_gate(
            GateType.G_MON,
            {MetricId.M_01: 80.0, MetricId.M_03: 10.0},
        )
        # M-01 < 85% should trigger WARN (not FAIL, since action=WARN)
        assert report.overall == GateResult.WARN

    def test_gmon_gate_check_warns_with_high_rework(self) -> None:
        from agent33.evaluation.gates import GateEnforcer

        enforcer = GateEnforcer()
        report = enforcer.check_gate(
            GateType.G_MON,
            {MetricId.M_01: 95.0, MetricId.M_03: 30.0},
        )
        assert report.overall == GateResult.WARN


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


class TestScheduledGatesAPI:
    """Test the FastAPI routes for scheduled gates."""

    @staticmethod
    def _auth_headers(*scopes: str) -> dict[str, str]:
        token = create_access_token(
            "scheduled-gates-test-user",
            scopes=list(scopes),
        )
        return {"Authorization": f"Bearer {token}"}

    @pytest.fixture()
    def _install_service(self, gate_service: ScheduledGateService) -> ScheduledGateService:
        """Install the service on the routes module."""
        from agent33.api.routes import scheduled_gates as routes_mod

        routes_mod.set_service(gate_service)
        yield gate_service
        routes_mod.set_service(None)

    @pytest.fixture()
    def scheduled_gates_test_app(self, _install_service: ScheduledGateService):  # noqa: ANN201
        """Create a fresh app instance for each API test."""
        return _build_test_app()

    @pytest.fixture()
    def read_client(self, scheduled_gates_test_app):  # noqa: ANN201
        """Create an httpx AsyncClient with auth headers."""
        import httpx

        transport = httpx.ASGITransport(app=scheduled_gates_test_app)
        return httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers=self._auth_headers("workflows:read"),
        )

    @pytest.fixture()
    def execute_client(self, scheduled_gates_test_app):  # noqa: ANN201
        """Create an httpx AsyncClient with write/execute auth headers."""
        import httpx

        transport = httpx.ASGITransport(app=scheduled_gates_test_app)
        return httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers=self._auth_headers("tools:execute"),
        )

    async def test_list_schedules_requires_auth(
        self,
        _install_service: ScheduledGateService,
    ) -> None:
        import httpx

        transport = httpx.ASGITransport(app=_build_test_app())

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as c:
            resp = await c.get("/v1/evaluations/schedules")

        assert resp.status_code == 401

    async def test_create_schedule_requires_tools_execute_scope(
        self,
        _install_service: ScheduledGateService,
    ) -> None:
        import httpx

        transport = httpx.ASGITransport(app=_build_test_app())

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers=self._auth_headers("workflows:read"),
        ) as c:
            resp = await c.post(
                "/v1/evaluations/schedules",
                json={
                    "gate_type": "G-MON",
                    "schedule_type": "cron",
                    "cron_expr": "0 * * * *",
                },
            )

        assert resp.status_code == 403

    async def test_503_when_service_not_set(self) -> None:
        """Routes should return 503 when the service is not initialized."""
        import httpx

        from agent33.api.routes import scheduled_gates as routes_mod

        # Ensure service is None
        routes_mod.set_service(None)
        transport = httpx.ASGITransport(app=_build_test_app())
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers=self._auth_headers("workflows:read"),
        ) as c:
            resp = await c.get("/v1/evaluations/schedules")
            assert resp.status_code == 503

    async def test_create_schedule_endpoint(
        self, execute_client: object, _install_service: ScheduledGateService
    ) -> None:
        async with execute_client as c:
            resp = await c.post(
                "/v1/evaluations/schedules",
                json={
                    "gate_type": "G-MON",
                    "schedule_type": "cron",
                    "cron_expr": "0 * * * *",
                },
            )
            assert resp.status_code == 201
            data = resp.json()
            assert "schedule_id" in data
            assert data["gate_type"] == "G-MON"
            assert data["schedule_type"] == "cron"

    async def test_list_schedules_endpoint(
        self,
        read_client: object,
        _install_service: ScheduledGateService,
    ) -> None:
        # Create a schedule via service first
        _install_service.create_schedule(_cron_config())

        async with read_client as c:
            resp = await c.get("/v1/evaluations/schedules")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) >= 1

    async def test_get_schedule_endpoint(
        self,
        read_client: object,
        _install_service: ScheduledGateService,
    ) -> None:
        config = _cron_config()
        _install_service.create_schedule(config)

        async with read_client as c:
            resp = await c.get(f"/v1/evaluations/schedules/{config.schedule_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["schedule_id"] == config.schedule_id

    async def test_get_schedule_not_found(
        self,
        read_client: object,
        _install_service: ScheduledGateService,
    ) -> None:
        async with read_client as c:
            resp = await c.get("/v1/evaluations/schedules/nonexistent")
            assert resp.status_code == 404

    async def test_delete_schedule_endpoint(
        self,
        execute_client: object,
        _install_service: ScheduledGateService,
    ) -> None:
        config = _cron_config()
        _install_service.create_schedule(config)

        async with execute_client as c:
            resp = await c.delete(f"/v1/evaluations/schedules/{config.schedule_id}")
            assert resp.status_code == 204

    async def test_delete_schedule_not_found(
        self,
        execute_client: object,
        _install_service: ScheduledGateService,
    ) -> None:
        async with execute_client as c:
            resp = await c.delete("/v1/evaluations/schedules/nonexistent")
            assert resp.status_code == 404

    async def test_trigger_endpoint(
        self,
        execute_client: object,
        _install_service: ScheduledGateService,
    ) -> None:
        config = _cron_config()
        _install_service.create_schedule(config)

        async with execute_client as c:
            resp = await c.post(f"/v1/evaluations/schedules/{config.schedule_id}/trigger")
            assert resp.status_code == 200
            data = resp.json()
            assert data["schedule_id"] == config.schedule_id
            assert "gate_result" in data
            assert "metrics" in data

    async def test_trigger_nonexistent_returns_404(
        self,
        execute_client: object,
        _install_service: ScheduledGateService,
    ) -> None:
        async with execute_client as c:
            resp = await c.post("/v1/evaluations/schedules/nonexistent/trigger")
            assert resp.status_code == 404

    async def test_history_endpoint(
        self,
        read_client: object,
        _install_service: ScheduledGateService,
    ) -> None:
        config = _cron_config()
        _install_service.create_schedule(config)
        await _install_service.trigger_now(config.schedule_id)

        async with read_client as c:
            resp = await c.get(f"/v1/evaluations/schedules/{config.schedule_id}/history")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) == 1

    async def test_history_nonexistent_returns_404(
        self,
        read_client: object,
        _install_service: ScheduledGateService,
    ) -> None:
        async with read_client as c:
            resp = await c.get("/v1/evaluations/schedules/nonexistent/history")
            assert resp.status_code == 404

    async def test_create_invalid_schedule_returns_422(
        self,
        execute_client: object,
        _install_service: ScheduledGateService,
    ) -> None:
        async with execute_client as c:
            resp = await c.post(
                "/v1/evaluations/schedules",
                json={
                    "schedule_type": "cron",
                    # missing cron_expr
                },
            )
            assert resp.status_code == 422

    async def test_create_invalid_cron_returns_422(
        self,
        execute_client: object,
        _install_service: ScheduledGateService,
    ) -> None:
        async with execute_client as c:
            resp = await c.post(
                "/v1/evaluations/schedules",
                json={
                    "schedule_type": "cron",
                    "cron_expr": "not a cron",
                },
            )
            assert resp.status_code == 422
            assert "Invalid cron_expr" in resp.json()["detail"]

    async def test_history_with_limit_param(
        self,
        read_client: object,
        _install_service: ScheduledGateService,
    ) -> None:
        config = _cron_config()
        _install_service.create_schedule(config)
        for _ in range(5):
            await _install_service.trigger_now(config.schedule_id)

        async with read_client as c:
            resp = await c.get(
                f"/v1/evaluations/schedules/{config.schedule_id}/history",
                params={"limit": 2},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2


# ---------------------------------------------------------------------------
# Config settings tests
# ---------------------------------------------------------------------------


class TestConfigSettings:
    """Verify the new config settings exist with correct defaults."""

    def test_scheduled_gates_defaults(self) -> None:
        from agent33.config import Settings

        s = Settings(
            environment="test",
            jwt_secret="test-secret",
        )
        assert s.scheduled_gates_enabled is False
        assert s.scheduled_gates_max_schedules == 50
        assert s.scheduled_gates_history_retention == 100

    def test_scheduled_gates_custom_values(self) -> None:
        from agent33.config import Settings

        s = Settings(
            environment="test",
            jwt_secret="test-secret",
            scheduled_gates_enabled=True,
            scheduled_gates_max_schedules=10,
            scheduled_gates_history_retention=50,
        )
        assert s.scheduled_gates_enabled is True
        assert s.scheduled_gates_max_schedules == 10
        assert s.scheduled_gates_history_retention == 50


# ---------------------------------------------------------------------------
# Integration tests (service + evaluation pipeline)
# ---------------------------------------------------------------------------


class TestIntegration:
    """End-to-end tests combining service, evaluation, and gate checking."""

    async def test_full_pipeline_creates_evaluation_run(
        self, eval_service: EvaluationService, gate_service: ScheduledGateService
    ) -> None:
        """A trigger should create a real evaluation run in the eval service."""
        config = _cron_config()
        gate_service.create_schedule(config)
        result = await gate_service.trigger_now(config.schedule_id)

        # The run should exist in the evaluation service
        run = eval_service.get_run(result.run_id)
        assert run is not None
        assert run.completed_at is not None
        assert run.gate == GateType.G_MON

    async def test_full_pipeline_metrics_match(
        self, eval_service: EvaluationService, gate_service: ScheduledGateService
    ) -> None:
        """Metrics in the result should match those in the evaluation run."""
        config = _cron_config()
        gate_service.create_schedule(config)
        result = await gate_service.trigger_now(config.schedule_id)

        run = eval_service.get_run(result.run_id)
        assert run is not None
        run_metrics = {m.metric_id.value: m.value for m in run.metrics}
        assert result.metrics == run_metrics

    async def test_full_pipeline_gate_report_matches(
        self, eval_service: EvaluationService, gate_service: ScheduledGateService
    ) -> None:
        """Gate result in the scheduled result should match the run's report."""
        config = _cron_config()
        gate_service.create_schedule(config)
        result = await gate_service.trigger_now(config.schedule_id)

        run = eval_service.get_run(result.run_id)
        assert run is not None
        assert run.gate_report is not None
        assert result.gate_result == run.gate_report.overall

    async def test_interval_schedule_creation(self, gate_service: ScheduledGateService) -> None:
        """Interval schedules should work identically for trigger_now."""
        config = _interval_config()
        gate_service.create_schedule(config)
        result = await gate_service.trigger_now(config.schedule_id)
        assert result.error is None
        assert result.metrics  # non-empty

    async def test_multiple_triggers_accumulate_history(
        self, gate_service: ScheduledGateService
    ) -> None:
        config = _cron_config()
        gate_service.create_schedule(config)

        run_ids = set()
        for _ in range(4):
            result = await gate_service.trigger_now(config.schedule_id)
            run_ids.add(result.run_id)

        # Each trigger should produce a unique run
        assert len(run_ids) == 4
        history = gate_service.get_history(config.schedule_id)
        assert len(history) == 4
