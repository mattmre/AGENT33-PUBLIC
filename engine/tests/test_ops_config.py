"""Tests for Track 9: Operations, Config, and Doctor.

Covers: cron CRUD models, config schema introspection, config apply,
DOC-11 through DOC-16 diagnostics, onboarding checklist, and API routes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agent33.automation.cron_models import (
    DeliveryMode,
    JobDefinition,
    JobHistoryStore,
    JobRunRecord,
)
from agent33.config import Settings
from agent33.config_apply import ConfigApplyRequest, ConfigApplyService
from agent33.config_schema import ConfigSchemaResponse, introspect_settings_schema
from agent33.operator.diagnostics import (
    check_backup,
    check_hooks,
    check_mcp,
    check_scheduler,
    check_sessions,
    check_voice,
)
from agent33.operator.models import CheckStatus
from agent33.operator.onboarding import OnboardingService, OnboardingStatus

# ============================================================================
# JobHistoryStore unit tests
# ============================================================================


class TestJobHistoryStore:
    """Tests for in-memory job run history."""

    def test_record_and_query(self) -> None:
        """Records are stored and retrievable by job_id."""
        store = JobHistoryStore(max_records_per_job=10)
        run = JobRunRecord(
            run_id="r1",
            job_id="j1",
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            status="completed",
        )
        store.record(run)
        results = store.query("j1")
        assert len(results) == 1
        assert results[0].run_id == "r1"
        assert results[0].status == "completed"

    def test_query_returns_most_recent_first(self) -> None:
        """Most recent runs should be returned first."""
        store = JobHistoryStore()
        for i in range(5):
            store.record(
                JobRunRecord(
                    run_id=f"r{i}",
                    job_id="j1",
                    started_at=datetime.now(UTC),
                    status="completed",
                )
            )
        results = store.query("j1", limit=3)
        assert len(results) == 3
        # Most recent first
        assert results[0].run_id == "r4"
        assert results[1].run_id == "r3"
        assert results[2].run_id == "r2"

    def test_query_filter_by_status(self) -> None:
        """Filtering by status returns only matching records."""
        store = JobHistoryStore()
        store.record(
            JobRunRecord(
                run_id="r1",
                job_id="j1",
                started_at=datetime.now(UTC),
                status="completed",
            )
        )
        store.record(
            JobRunRecord(
                run_id="r2",
                job_id="j1",
                started_at=datetime.now(UTC),
                status="failed",
            )
        )
        store.record(
            JobRunRecord(
                run_id="r3",
                job_id="j1",
                started_at=datetime.now(UTC),
                status="completed",
            )
        )

        completed = store.query("j1", status="completed")
        assert len(completed) == 2
        assert all(r.status == "completed" for r in completed)

        failed = store.query("j1", status="failed")
        assert len(failed) == 1
        assert failed[0].run_id == "r2"

    def test_eviction_at_max_records(self) -> None:
        """Oldest records are evicted when max_records is exceeded."""
        store = JobHistoryStore(max_records_per_job=3)
        for i in range(5):
            store.record(
                JobRunRecord(
                    run_id=f"r{i}",
                    job_id="j1",
                    started_at=datetime.now(UTC),
                    status="completed",
                )
            )
        results = store.query("j1", limit=10)
        assert len(results) == 3
        # Only the last 3 should remain (r4, r3, r2 in most-recent-first order)
        run_ids = [r.run_id for r in results]
        assert run_ids == ["r4", "r3", "r2"]

    def test_query_nonexistent_job(self) -> None:
        """Querying a non-existent job returns empty list."""
        store = JobHistoryStore()
        results = store.query("nonexistent")
        assert results == []

    def test_all_job_ids(self) -> None:
        """all_job_ids returns IDs that have recorded history."""
        store = JobHistoryStore()
        store.record(
            JobRunRecord(
                run_id="r1",
                job_id="j1",
                started_at=datetime.now(UTC),
                status="completed",
            )
        )
        store.record(
            JobRunRecord(
                run_id="r2",
                job_id="j2",
                started_at=datetime.now(UTC),
                status="completed",
            )
        )
        assert sorted(store.all_job_ids) == ["j1", "j2"]


# ============================================================================
# JobDefinition model tests
# ============================================================================


class TestJobDefinition:
    """Tests for the JobDefinition model."""

    def test_defaults(self) -> None:
        """Default values are applied correctly."""
        job = JobDefinition(
            job_id="j1",
            workflow_name="test-workflow",
            schedule_type="cron",
            schedule_expr="*/5 * * * *",
        )
        assert job.delivery_mode == DeliveryMode.DIRECT
        assert job.enabled is True
        assert job.inputs == {}
        assert job.webhook_url == ""

    def test_webhook_delivery_mode(self) -> None:
        """Webhook delivery mode can be set."""
        job = JobDefinition(
            job_id="j1",
            workflow_name="test-workflow",
            schedule_type="cron",
            schedule_expr="0 * * * *",
            delivery_mode=DeliveryMode.WEBHOOK,
            webhook_url="https://example.com/hook",
        )
        assert job.delivery_mode == DeliveryMode.WEBHOOK
        assert job.webhook_url == "https://example.com/hook"


# ============================================================================
# Config schema introspection tests
# ============================================================================


class TestConfigSchemaIntrospection:
    """Tests for introspect_settings_schema."""

    def test_returns_grouped_fields(self) -> None:
        """Schema contains multiple groups corresponding to field prefixes."""
        schema = introspect_settings_schema(Settings)
        assert isinstance(schema, ConfigSchemaResponse)
        assert schema.total_fields > 0
        assert len(schema.groups) > 0

        # Check known groups exist
        assert "database" in schema.groups
        assert "security" in schema.groups
        assert "api" in schema.groups

    def test_database_group_contains_database_url(self) -> None:
        """The database group should contain database_url."""
        schema = introspect_settings_schema(Settings)
        db_fields = schema.groups.get("database", [])
        field_names = [f.name for f in db_fields]
        assert "database_url" in field_names

    def test_secret_fields_marked(self) -> None:
        """SecretStr fields should have is_secret=True."""
        schema = introspect_settings_schema(Settings)
        # Flatten all fields
        all_fields = [f for fields in schema.groups.values() for f in fields]
        secret_field_names = {f.name for f in all_fields if f.is_secret}

        # These are known SecretStr fields
        assert "jwt_secret" in secret_field_names
        assert "api_secret_key" in secret_field_names
        assert "encryption_key" in secret_field_names
        assert "openai_api_key" in secret_field_names

    def test_secret_fields_default_redacted(self) -> None:
        """SecretStr field defaults should be redacted to '***'."""
        schema = introspect_settings_schema(Settings)
        all_fields = [f for fields in schema.groups.values() for f in fields]
        jwt_field = next((f for f in all_fields if f.name == "jwt_secret"), None)
        assert jwt_field is not None
        assert jwt_field.default == "***"

    def test_env_var_is_uppercase(self) -> None:
        """Each field's env_var should be its name uppercased."""
        schema = introspect_settings_schema(Settings)
        all_fields = [f for fields in schema.groups.values() for f in fields]
        for field in all_fields:
            assert field.env_var == field.name.upper()

    def test_total_fields_matches_sum(self) -> None:
        """total_fields should equal the sum of all group field counts."""
        schema = introspect_settings_schema(Settings)
        computed_total = sum(len(fields) for fields in schema.groups.values())
        assert schema.total_fields == computed_total


# ============================================================================
# Config apply tests
# ============================================================================


class TestConfigApplyService:
    """Tests for ConfigApplyService."""

    def _make_settings(self) -> Settings:
        """Create a test Settings instance."""
        return Settings(
            environment="test",
            database_url="postgresql+asyncpg://test:test@localhost/test",
        )

    def test_validate_only_accepts_valid_changes(self) -> None:
        """Valid field changes produce no validation errors."""
        svc = ConfigApplyService(settings_cls=Settings)
        errors = svc.validate_only({"api_port": 9000, "training_enabled": False})
        assert errors == []

    def test_validate_only_rejects_unknown_fields(self) -> None:
        """Unknown fields produce validation errors."""
        svc = ConfigApplyService(settings_cls=Settings)
        errors = svc.validate_only({"nonexistent_field": "value"})
        assert len(errors) == 1
        assert "Unknown field" in errors[0]

    def test_apply_changes_to_live_settings(self) -> None:
        """Applied changes modify the settings instance."""
        svc = ConfigApplyService(settings_cls=Settings)
        test_settings = self._make_settings()

        result = svc.apply(
            ConfigApplyRequest(changes={"api_port": 9999}),
            settings_instance=test_settings,
        )
        assert "api_port" in result.applied
        assert test_settings.api_port == 9999

    def test_apply_rejects_invalid_type(self) -> None:
        """Invalid types produce validation errors without applying."""
        svc = ConfigApplyService(settings_cls=Settings)
        test_settings = self._make_settings()
        original_port = test_settings.api_port

        result = svc.apply(
            ConfigApplyRequest(changes={"api_port": "not-a-number"}),
            settings_instance=test_settings,
        )
        assert len(result.validation_errors) == 1
        assert "api_port" in result.validation_errors[0]
        assert test_settings.api_port == original_port

    def test_apply_unknown_field_rejected(self) -> None:
        """Unknown fields are rejected in apply, not just validate."""
        svc = ConfigApplyService(settings_cls=Settings)
        test_settings = self._make_settings()

        result = svc.apply(
            ConfigApplyRequest(changes={"unknown_field": "value"}),
            settings_instance=test_settings,
        )
        assert len(result.rejected) == 1
        assert result.rejected[0][0] == "unknown_field"
        assert "Unknown field" in result.rejected[0][1]

    def test_apply_infrastructure_fields_flag_restart(self) -> None:
        """Infrastructure fields like database_url flag restart_required."""
        svc = ConfigApplyService(settings_cls=Settings)
        test_settings = self._make_settings()

        result = svc.apply(
            ConfigApplyRequest(
                changes={"database_url": "postgresql+asyncpg://new:new@newhost/newdb"}
            ),
            settings_instance=test_settings,
        )
        assert "database_url" in result.applied
        assert result.restart_required is True

    def test_apply_non_infrastructure_no_restart(self) -> None:
        """Non-infrastructure fields do not set restart_required."""
        svc = ConfigApplyService(settings_cls=Settings)
        test_settings = self._make_settings()

        result = svc.apply(
            ConfigApplyRequest(changes={"training_enabled": False}),
            settings_instance=test_settings,
        )
        assert "training_enabled" in result.applied
        assert result.restart_required is False

    def test_apply_secret_str_field(self) -> None:
        """SecretStr fields are coerced correctly."""
        svc = ConfigApplyService(settings_cls=Settings)
        test_settings = self._make_settings()

        result = svc.apply(
            ConfigApplyRequest(changes={"jwt_secret": "new-super-secret"}),
            settings_instance=test_settings,
        )
        assert "jwt_secret" in result.applied
        assert test_settings.jwt_secret.get_secret_value() == "new-super-secret"

    def test_apply_bool_from_string(self) -> None:
        """Boolean fields accept string representations."""
        svc = ConfigApplyService(settings_cls=Settings)
        test_settings = self._make_settings()

        result = svc.apply(
            ConfigApplyRequest(changes={"training_enabled": "false"}),
            settings_instance=test_settings,
        )
        assert "training_enabled" in result.applied
        assert test_settings.training_enabled is False


# ============================================================================
# DOC-11 through DOC-16 diagnostic tests
# ============================================================================


class TestDiagnosticChecks:
    """Tests for the new DOC-11 through DOC-16 checks."""

    @pytest.mark.asyncio
    async def test_doc11_sessions_ok(self) -> None:
        """DOC-11: returns OK when operator_session_service exists."""
        state = SimpleNamespace(operator_session_service=MagicMock())
        result = await check_sessions(state)
        assert result.id == "DOC-11"
        assert result.status == CheckStatus.OK
        assert "available" in result.message

    @pytest.mark.asyncio
    async def test_doc11_sessions_missing(self) -> None:
        """DOC-11: returns WARNING when operator_session_service is absent."""
        state = SimpleNamespace()
        result = await check_sessions(state)
        assert result.id == "DOC-11"
        assert result.status == CheckStatus.WARNING
        assert "not initialized" in result.message

    @pytest.mark.asyncio
    async def test_doc12_hooks_ok_with_hooks(self) -> None:
        """DOC-12: returns OK when hook_registry has hooks."""
        mock_registry = MagicMock()
        mock_registry.count.return_value = 5
        state = SimpleNamespace(hook_registry=mock_registry)
        result = await check_hooks(state)
        assert result.id == "DOC-12"
        assert result.status == CheckStatus.OK
        assert "5 hook(s)" in result.message

    @pytest.mark.asyncio
    async def test_doc12_hooks_warning_empty(self) -> None:
        """DOC-12: returns WARNING when hook_registry has 0 hooks."""
        mock_registry = MagicMock()
        mock_registry.count.return_value = 0
        state = SimpleNamespace(hook_registry=mock_registry)
        result = await check_hooks(state)
        assert result.id == "DOC-12"
        assert result.status == CheckStatus.WARNING
        assert "0 hooks" in result.message

    @pytest.mark.asyncio
    async def test_doc12_hooks_missing(self) -> None:
        """DOC-12: returns WARNING when hook_registry is absent."""
        state = SimpleNamespace()
        result = await check_hooks(state)
        assert result.id == "DOC-12"
        assert result.status == CheckStatus.WARNING

    @pytest.mark.asyncio
    async def test_doc13_scheduler_ok(self) -> None:
        """DOC-13: returns OK when scheduler is running with jobs."""
        mock_scheduler = MagicMock()
        mock_scheduler.list_jobs.return_value = [MagicMock(), MagicMock()]
        mock_scheduler._scheduler.running = True
        state = SimpleNamespace(workflow_scheduler=mock_scheduler)
        result = await check_scheduler(state)
        assert result.id == "DOC-13"
        assert result.status == CheckStatus.OK
        assert "2 job(s)" in result.message

    @pytest.mark.asyncio
    async def test_doc13_scheduler_missing(self) -> None:
        """DOC-13: returns WARNING when scheduler not initialized."""
        state = SimpleNamespace()
        result = await check_scheduler(state)
        assert result.id == "DOC-13"
        assert result.status == CheckStatus.WARNING

    @pytest.mark.asyncio
    async def test_doc13_scheduler_not_running(self) -> None:
        """DOC-13: returns WARNING when scheduler exists but not running."""
        mock_scheduler = MagicMock()
        mock_scheduler.list_jobs.return_value = []
        mock_scheduler._scheduler.running = False
        state = SimpleNamespace(workflow_scheduler=mock_scheduler)
        result = await check_scheduler(state)
        assert result.id == "DOC-13"
        assert result.status == CheckStatus.WARNING
        assert "not running" in result.message

    @pytest.mark.asyncio
    async def test_doc14_mcp_disabled(self) -> None:
        """DOC-14: returns OK when MCP proxy is disabled."""
        mock_settings = MagicMock()
        mock_settings.mcp_proxy_enabled = False
        state = SimpleNamespace(
            proxy_manager=MagicMock(),
            settings=mock_settings,
        )
        result = await check_mcp(state)
        assert result.id == "DOC-14"
        assert result.status == CheckStatus.OK
        assert "disabled" in result.message

    @pytest.mark.asyncio
    async def test_doc14_mcp_missing(self) -> None:
        """DOC-14: returns WARNING when proxy_manager is absent."""
        state = SimpleNamespace()
        result = await check_mcp(state)
        assert result.id == "DOC-14"
        assert result.status == CheckStatus.WARNING

    @pytest.mark.asyncio
    async def test_doc15_voice_disabled(self) -> None:
        """DOC-15: returns OK when voice daemon is disabled."""
        mock_settings = MagicMock()
        mock_settings.voice_daemon_enabled = False
        state = SimpleNamespace(settings=mock_settings)
        result = await check_voice(state)
        assert result.id == "DOC-15"
        assert result.status == CheckStatus.OK
        assert "disabled" in result.message

    @pytest.mark.asyncio
    async def test_doc15_voice_stub(self) -> None:
        """DOC-15: returns OK when voice uses stub transport."""
        mock_settings = MagicMock()
        mock_settings.voice_daemon_enabled = True
        mock_settings.voice_daemon_transport = "stub"
        state = SimpleNamespace(settings=mock_settings)
        result = await check_voice(state)
        assert result.id == "DOC-15"
        assert result.status == CheckStatus.OK
        assert "stub" in result.message

    @pytest.mark.asyncio
    async def test_doc15_voice_sidecar_healthy(self) -> None:
        """DOC-15: returns OK when sidecar probe reports healthy."""
        mock_settings = MagicMock()
        mock_settings.voice_daemon_enabled = True
        mock_settings.voice_daemon_transport = "sidecar"
        mock_probe = AsyncMock()
        mock_probe.health_snapshot.return_value = {"status": "ok"}
        state = SimpleNamespace(
            settings=mock_settings,
            voice_sidecar_probe=mock_probe,
        )
        result = await check_voice(state)
        assert result.id == "DOC-15"
        assert result.status == CheckStatus.OK

    @pytest.mark.asyncio
    async def test_doc16_backup_ok(self) -> None:
        """DOC-16: returns OK when backup_service is present."""
        state = SimpleNamespace(backup_service=MagicMock())
        result = await check_backup(state)
        assert result.id == "DOC-16"
        assert result.status == CheckStatus.OK
        assert "available" in result.message

    @pytest.mark.asyncio
    async def test_doc16_backup_missing(self) -> None:
        """DOC-16: returns WARNING when backup_service is absent."""
        state = SimpleNamespace()
        result = await check_backup(state)
        assert result.id == "DOC-16"
        assert result.status == CheckStatus.WARNING


# ============================================================================
# Onboarding tests
# ============================================================================


class TestOnboardingService:
    """Tests for the OnboardingService."""

    def _make_settings(self, **overrides: Any) -> Settings:
        defaults: dict[str, Any] = {
            "environment": "test",
            "database_url": "postgresql+asyncpg://test:test@localhost/test",
        }
        defaults.update(overrides)
        return Settings(**defaults)

    def test_full_onboarding_with_all_services(self) -> None:
        """All steps complete when all services are initialized and secrets changed."""
        mock_providers = {"ollama": MagicMock()}
        mock_router = MagicMock()
        mock_router._providers = mock_providers
        mock_registry = MagicMock()
        mock_registry.list_all.return_value = [MagicMock()]
        mock_nats = MagicMock()
        mock_nats.is_connected = True

        state = SimpleNamespace(
            long_term_memory=MagicMock(),
            model_router=mock_router,
            agent_registry=mock_registry,
            redis=MagicMock(),
            nats_bus=mock_nats,
        )
        settings = self._make_settings(
            jwt_secret=SecretStr("non-default-secret"),
            api_secret_key=SecretStr("non-default-api-key"),
            backup_dir="var/backups",
        )

        svc = OnboardingService(app_state=state, settings=settings)
        result = svc.check()

        assert isinstance(result, OnboardingStatus)
        assert result.total_count == 8
        assert result.completed_count == 8
        assert result.overall_complete is True

    def test_partial_onboarding_default_secrets(self) -> None:
        """API secret step fails when using the default; JWT step is auto-generated.

        In dev/lite/test mode, jwt_secret is auto-generated by the config validator
        (P62 bootstrap), so OB-04 always shows completed=True.  OB-08 (api_secret_key)
        is NOT auto-generated, so it still fails when the default placeholder is used.
        """
        state = SimpleNamespace(
            long_term_memory=MagicMock(),
            model_router=MagicMock(_providers={"ollama": MagicMock()}),
            agent_registry=MagicMock(list_all=MagicMock(return_value=[MagicMock()])),
            redis=MagicMock(),
            nats_bus=MagicMock(is_connected=True),
        )
        # Default secrets (jwt_secret will be auto-generated in test environment)
        settings = self._make_settings(backup_dir="var/backups")

        svc = OnboardingService(app_state=state, settings=settings)
        result = svc.check()

        jwt_step = next(s for s in result.steps if s.step_id == "OB-04")
        api_step = next(s for s in result.steps if s.step_id == "OB-08")
        # JWT is auto-generated in test mode — OB-04 is satisfied.
        assert jwt_step.completed is True
        # API secret is NOT auto-generated — still using default, so incomplete.
        assert api_step.completed is False
        assert result.overall_complete is False

    def test_missing_database(self) -> None:
        """OB-01 fails when long_term_memory is absent."""
        state = SimpleNamespace()
        settings = self._make_settings()
        svc = OnboardingService(app_state=state, settings=settings)
        result = svc.check()

        db_step = next(s for s in result.steps if s.step_id == "OB-01")
        assert db_step.completed is False
        assert db_step.remediation != ""

    def test_missing_agent_definitions(self) -> None:
        """OB-03 fails when agent_registry returns empty list."""
        mock_registry = MagicMock()
        mock_registry.list_all.return_value = []
        state = SimpleNamespace(agent_registry=mock_registry)
        settings = self._make_settings()
        svc = OnboardingService(app_state=state, settings=settings)
        result = svc.check()

        agents_step = next(s for s in result.steps if s.step_id == "OB-03")
        assert agents_step.completed is False

    def test_nats_not_connected(self) -> None:
        """OB-07 fails when nats_bus is present but not connected."""
        mock_nats = MagicMock()
        mock_nats.is_connected = False
        state = SimpleNamespace(nats_bus=mock_nats)
        settings = self._make_settings()
        svc = OnboardingService(app_state=state, settings=settings)
        result = svc.check()

        nats_step = next(s for s in result.steps if s.step_id == "OB-07")
        assert nats_step.completed is False

    def test_remediation_present_on_incomplete_steps(self) -> None:
        """Incomplete steps must have non-empty remediation text."""
        state = SimpleNamespace()
        settings = self._make_settings()
        svc = OnboardingService(app_state=state, settings=settings)
        result = svc.check()

        for step in result.steps:
            if not step.completed:
                assert step.remediation != "", (
                    f"Step {step.step_id} is incomplete but has empty remediation"
                )


# ============================================================================
# API route tests (using httpx AsyncClient with ASGITransport)
# ============================================================================


@pytest.fixture(autouse=True)
def _install_services() -> Any:
    """Install Track 9 services on the global app.state for API tests."""
    from agent33.automation.cron_models import JobHistoryStore
    from agent33.automation.scheduler import WorkflowScheduler
    from agent33.config import Settings, settings
    from agent33.config_apply import ConfigApplyService
    from agent33.main import app
    from agent33.operator.onboarding import OnboardingService
    from agent33.operator.service import OperatorService

    cron_job_store: dict[str, JobDefinition] = {}
    job_history_store = JobHistoryStore()
    workflow_scheduler = WorkflowScheduler()
    config_apply_service = ConfigApplyService(settings_cls=Settings)

    app.state.cron_job_store = cron_job_store
    app.state.job_history_store = job_history_store
    app.state.workflow_scheduler = workflow_scheduler
    app.state.config_apply_service = config_apply_service

    # Ensure operator_service exists
    if not hasattr(app.state, "operator_service"):
        import time

        app.state.operator_service = OperatorService(
            app_state=app.state,
            settings=settings,
            start_time=time.time(),
        )

    # Onboarding
    app.state.onboarding_service = OnboardingService(
        app_state=app.state,
        settings=settings,
    )
    yield
    # Clean up
    for attr in (
        "cron_job_store",
        "job_history_store",
        "config_apply_service",
        "onboarding_service",
    ):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


def _admin_headers() -> dict[str, str]:
    """Create auth headers with admin scopes."""
    from agent33.security.auth import create_access_token

    token = create_access_token(
        "admin-user",
        scopes=[
            "admin",
            "operator:read",
            "operator:write",
            "cron:read",
            "cron:write",
        ],
    )
    return {"Authorization": f"Bearer {token}"}


class TestCronAPI:
    """API tests for cron CRUD endpoints."""

    def test_list_jobs_empty(self) -> None:
        """GET /v1/cron/jobs returns empty list initially."""
        from agent33.main import app

        client = TestClient(app, headers=_admin_headers())
        resp = client.get("/v1/cron/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["jobs"] == []
        assert data["count"] == 0

    def test_create_and_get_job(self) -> None:
        """POST + GET /v1/cron/jobs round-trip."""
        from agent33.main import app

        client = TestClient(app, headers=_admin_headers())
        create_resp = client.post(
            "/v1/cron/jobs",
            json={
                "workflow_name": "daily-report",
                "schedule_type": "cron",
                "schedule_expr": "0 9 * * *",
                "inputs": {"format": "pdf"},
            },
        )
        assert create_resp.status_code == 201
        job_data = create_resp.json()
        assert job_data["workflow_name"] == "daily-report"
        assert job_data["schedule_type"] == "cron"
        job_id = job_data["job_id"]

        get_resp = client.get(f"/v1/cron/jobs/{job_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["job_id"] == job_id

    def test_create_job_invalid_schedule_type(self) -> None:
        """POST /v1/cron/jobs with invalid schedule_type returns 422."""
        from agent33.main import app

        client = TestClient(app, headers=_admin_headers())
        resp = client.post(
            "/v1/cron/jobs",
            json={
                "workflow_name": "test",
                "schedule_type": "invalid",
                "schedule_expr": "* * * * *",
            },
        )
        assert resp.status_code == 422

    def test_update_job(self) -> None:
        """PUT /v1/cron/jobs/{job_id} updates fields."""
        from agent33.main import app

        client = TestClient(app, headers=_admin_headers())
        create_resp = client.post(
            "/v1/cron/jobs",
            json={
                "workflow_name": "updatable",
                "schedule_type": "cron",
                "schedule_expr": "0 * * * *",
            },
        )
        job_id = create_resp.json()["job_id"]

        update_resp = client.put(
            f"/v1/cron/jobs/{job_id}",
            json={"enabled": False, "webhook_url": "https://hook.example.com"},
        )
        assert update_resp.status_code == 200
        updated = update_resp.json()
        assert updated["enabled"] is False
        assert updated["webhook_url"] == "https://hook.example.com"

    def test_delete_job(self) -> None:
        """DELETE /v1/cron/jobs/{job_id} removes the job."""
        from agent33.main import app

        client = TestClient(app, headers=_admin_headers())
        create_resp = client.post(
            "/v1/cron/jobs",
            json={
                "workflow_name": "deletable",
                "schedule_type": "cron",
                "schedule_expr": "0 0 * * *",
            },
        )
        job_id = create_resp.json()["job_id"]

        del_resp = client.delete(f"/v1/cron/jobs/{job_id}")
        assert del_resp.status_code == 204

        get_resp = client.get(f"/v1/cron/jobs/{job_id}")
        assert get_resp.status_code == 404

    def test_get_nonexistent_job(self) -> None:
        """GET /v1/cron/jobs/{bad_id} returns 404."""
        from agent33.main import app

        client = TestClient(app, headers=_admin_headers())
        resp = client.get("/v1/cron/jobs/nonexistent-id")
        assert resp.status_code == 404

    def test_trigger_job(self) -> None:
        """POST /v1/cron/jobs/{job_id}/trigger creates a run record."""
        from agent33.main import app

        client = TestClient(app, headers=_admin_headers())
        create_resp = client.post(
            "/v1/cron/jobs",
            json={
                "workflow_name": "triggerable",
                "schedule_type": "cron",
                "schedule_expr": "0 0 * * *",
            },
        )
        job_id = create_resp.json()["job_id"]

        trigger_resp = client.post(f"/v1/cron/jobs/{job_id}/trigger")
        assert trigger_resp.status_code == 200
        trigger_data = trigger_resp.json()
        assert trigger_data["job_id"] == job_id
        assert trigger_data["status"] == "triggered"

        history_resp = client.get(f"/v1/cron/jobs/{job_id}/history")
        assert history_resp.status_code == 200
        assert history_resp.json()["count"] == 1


class TestConfigAPI:
    """API tests for config endpoints."""

    def test_config_schema(self) -> None:
        """GET /v1/config/schema returns grouped schema."""
        from agent33.main import app

        client = TestClient(app, headers=_admin_headers())
        resp = client.get("/v1/config/schema")
        assert resp.status_code == 200
        data = resp.json()
        assert "groups" in data
        assert data["total_fields"] > 0

    def test_config_schema_group(self) -> None:
        """GET /v1/config/schema/{group} returns fields for that group."""
        from agent33.main import app

        client = TestClient(app, headers=_admin_headers())
        resp = client.get("/v1/config/schema/database")
        assert resp.status_code == 200
        data = resp.json()
        assert "database" in data["groups"]

    def test_config_schema_group_not_found(self) -> None:
        """GET /v1/config/schema/{bad_group} returns 404."""
        from agent33.main import app

        client = TestClient(app, headers=_admin_headers())
        resp = client.get("/v1/config/schema/nonexistent-group")
        assert resp.status_code == 404

    def test_config_apply_validation(self) -> None:
        """POST /v1/config/apply rejects unknown fields."""
        from agent33.main import app

        client = TestClient(app, headers=_admin_headers())
        resp = client.post(
            "/v1/config/apply",
            json={"changes": {"totally_fake_field": 42}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["rejected"]) == 1


class TestOnboardingAPI:
    """API tests for the onboarding endpoint."""

    def test_onboarding_returns_steps(self) -> None:
        """GET /v1/operator/onboarding returns onboarding status with steps."""
        from agent33.main import app

        client = TestClient(app, headers=_admin_headers())
        resp = client.get("/v1/operator/onboarding")
        assert resp.status_code == 200
        data = resp.json()
        assert "steps" in data
        assert data["total_count"] == 8
        assert isinstance(data["completed_count"], int)
        assert isinstance(data["overall_complete"], bool)

        # Verify step structure
        for step in data["steps"]:
            assert "step_id" in step
            assert "title" in step
            assert "completed" in step
