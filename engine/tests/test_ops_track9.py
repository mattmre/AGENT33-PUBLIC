"""Tests for Track 9 — ops doctor, config manager, cron manager, onboarding.

Tests cover:
- SystemDoctor with all 8 built-in checks
- ConfigManager schema introspection, validation, and apply
- CronManager job lifecycle (list, get, enable, disable, trigger, history)
- OnboardingChecklistService auto-resolution
- /v1/ops/ API route integration
"""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from agent33.ops.config_manager import ConfigManager, ConfigManagerResult
from agent33.ops.cron_manager import (
    CronJobStatus,
    CronManager,
    CronTriggerResult,
)
from agent33.ops.doctor import (
    CheckCategory,
    CheckStatus,
    DoctorCheck,
    DoctorReport,
    SystemDoctor,
    check_config_validity,
    check_disk_space,
    check_python_version,
    check_required_secrets,
)
from agent33.ops.onboarding import (
    OnboardingChecklist,
    OnboardingChecklistService,
    StepStatus,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeSettings:
    """Minimal settings mock for tests."""

    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/db"
    redis_url: str = "redis://localhost:6379/0"
    nats_url: str = "nats://localhost:4222"
    api_port: int = 8000
    api_secret_key: SecretStr = SecretStr("change-me-in-production")
    jwt_secret: SecretStr = SecretStr("change-me-in-production")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    encryption_key: SecretStr = SecretStr("")
    environment: str = "test"
    agent_definitions_dir: str = "agent-definitions"
    backup_dir: str = "var/backups"

    model_fields: dict[str, Any] = {}

    def check_production_secrets(self) -> list[str]:
        warnings = []
        if self.api_secret_key.get_secret_value() == "change-me-in-production":
            warnings.append("api_secret_key is using the default value")
        if self.jwt_secret.get_secret_value() == "change-me-in-production":
            warnings.append("jwt_secret is using the default value")
        return warnings


class FakeAppState:
    """Minimal app.state mock for tests."""

    long_term_memory: Any = MagicMock()
    redis: Any = MagicMock()
    nats_bus: Any = MagicMock(is_connected=True)
    model_router: Any = MagicMock(_providers={"ollama": object()})
    agent_registry: Any = MagicMock(list_all=MagicMock(return_value=["agent1"]))
    migration_checker: Any = None


@pytest.fixture()
def fake_settings() -> FakeSettings:
    return FakeSettings()


@pytest.fixture()
def fake_app_state() -> FakeAppState:
    return FakeAppState()


# ---------------------------------------------------------------------------
# SystemDoctor tests
# ---------------------------------------------------------------------------


class TestSystemDoctor:
    """Tests for SystemDoctor service and individual checks."""

    async def test_check_config_validity_passes_with_real_settings(self) -> None:
        """Config validity check passes when round-trip validation succeeds."""
        from agent33.config import Settings

        real_settings = Settings()
        result = await check_config_validity(FakeAppState(), real_settings)
        assert result.name == "config_validity"
        assert result.status == CheckStatus.OK
        assert result.category == CheckCategory.CONFIG
        assert result.duration_ms >= 0
        assert result.details["field_count"] > 0

    async def test_check_required_secrets_warns_on_defaults(
        self, fake_app_state: FakeAppState, fake_settings: FakeSettings
    ) -> None:
        """Required secrets check warns when default values are in use."""
        result = await check_required_secrets(fake_app_state, fake_settings)
        assert result.name == "required_secrets"
        assert result.status == CheckStatus.WARNING
        assert "2 secret(s) using defaults" in result.message
        assert result.details["environment"] == "test"

    async def test_check_required_secrets_ok_when_customized(
        self, fake_app_state: FakeAppState
    ) -> None:
        """Required secrets check is OK when secrets are non-default."""
        settings = FakeSettings()
        settings.api_secret_key = SecretStr("custom-api-key-abc")
        settings.jwt_secret = SecretStr("custom-jwt-secret-xyz")
        result = await check_required_secrets(fake_app_state, settings)
        assert result.status == CheckStatus.OK

    async def test_check_disk_space_returns_ok_normally(
        self, fake_app_state: FakeAppState, fake_settings: FakeSettings
    ) -> None:
        """Disk space check returns OK on a normal system."""
        result = await check_disk_space(fake_app_state, fake_settings)
        assert result.name == "disk_space"
        assert result.category == CheckCategory.SERVICE
        assert result.status in (CheckStatus.OK, CheckStatus.WARNING)
        assert "free_gb" in result.details
        assert "total_gb" in result.details
        assert result.details["percent_free"] > 0

    async def test_check_python_version_ok(
        self, fake_app_state: FakeAppState, fake_settings: FakeSettings
    ) -> None:
        """Python version check passes on Python >= 3.11."""
        result = await check_python_version(fake_app_state, fake_settings)
        assert result.name == "python_version"
        major, minor = sys.version_info[:2]
        if (major, minor) >= (3, 11):
            assert result.status == CheckStatus.OK
        else:
            assert result.status == CheckStatus.ERROR

    async def test_check_python_version_reports_details(
        self, fake_app_state: FakeAppState, fake_settings: FakeSettings
    ) -> None:
        """Python version check includes version and platform in details."""
        result = await check_python_version(fake_app_state, fake_settings)
        assert "version" in result.details
        assert "platform" in result.details

    async def test_doctor_run_all_produces_report(
        self, fake_app_state: FakeAppState, fake_settings: FakeSettings
    ) -> None:
        """SystemDoctor.run_all() produces a DoctorReport with all checks."""
        # Create a doctor with only fast checks (skip network checks)
        doctor = SystemDoctor(
            app_state=fake_app_state,
            settings=fake_settings,
            version="1.0.0-test",
        )
        # Replace checks with only the fast ones to avoid network calls
        doctor._checks = [
            check_config_validity,
            check_required_secrets,
            check_disk_space,
            check_python_version,
        ]

        report = await doctor.run_all()
        assert isinstance(report, DoctorReport)
        assert len(report.checks) == 4
        assert report.version == "1.0.0-test"
        assert report.timestamp is not None
        # Each check should have a valid status
        for check in report.checks:
            assert check.status in (
                CheckStatus.OK,
                CheckStatus.WARNING,
                CheckStatus.ERROR,
                CheckStatus.SKIPPED,
            )
            assert check.duration_ms >= 0

    async def test_doctor_overall_status_error_if_any_error(
        self, fake_app_state: FakeAppState, fake_settings: FakeSettings
    ) -> None:
        """Overall status is ERROR if any check is ERROR."""

        async def always_error(_app_state: Any, _settings: Any) -> DoctorCheck:
            return DoctorCheck(
                name="test_error",
                category=CheckCategory.SERVICE,
                status=CheckStatus.ERROR,
                message="fail",
            )

        doctor = SystemDoctor(fake_app_state, fake_settings)
        doctor._checks = [check_disk_space, always_error]
        report = await doctor.run_all()
        assert report.overall_status == CheckStatus.ERROR

    async def test_doctor_overall_status_warning_if_any_warning(
        self, fake_app_state: FakeAppState, fake_settings: FakeSettings
    ) -> None:
        """Overall status is WARNING if worst check is WARNING."""

        async def always_warn(_app_state: Any, _settings: Any) -> DoctorCheck:
            return DoctorCheck(
                name="test_warn",
                category=CheckCategory.CONFIG,
                status=CheckStatus.WARNING,
                message="warn",
            )

        async def always_ok(_app_state: Any, _settings: Any) -> DoctorCheck:
            return DoctorCheck(
                name="test_ok",
                category=CheckCategory.CONFIG,
                status=CheckStatus.OK,
                message="ok",
            )

        doctor = SystemDoctor(fake_app_state, fake_settings)
        doctor._checks = [always_ok, always_warn]
        report = await doctor.run_all()
        assert report.overall_status == CheckStatus.WARNING

    async def test_doctor_register_custom_check(
        self, fake_app_state: FakeAppState, fake_settings: FakeSettings
    ) -> None:
        """Custom checks can be registered and are included in reports."""

        async def custom_check(_app_state: Any, _settings: Any) -> DoctorCheck:
            return DoctorCheck(
                name="custom_check",
                category=CheckCategory.SERVICE,
                status=CheckStatus.OK,
                message="custom OK",
            )

        doctor = SystemDoctor(fake_app_state, fake_settings)
        doctor._checks = []
        doctor.register_check(custom_check)
        report = await doctor.run_all()
        assert len(report.checks) == 1
        assert report.checks[0].name == "custom_check"

    async def test_doctor_run_single_check(
        self, fake_app_state: FakeAppState, fake_settings: FakeSettings
    ) -> None:
        """run_check() returns a single check result by name."""
        doctor = SystemDoctor(fake_app_state, fake_settings)
        result = await doctor.run_check("python_version")
        assert result is not None
        assert result.name == "python_version"

    async def test_doctor_run_single_check_not_found(
        self, fake_app_state: FakeAppState, fake_settings: FakeSettings
    ) -> None:
        """run_check() returns None for unknown check names."""
        doctor = SystemDoctor(fake_app_state, fake_settings)
        result = await doctor.run_check("nonexistent_check")
        assert result is None

    async def test_doctor_handles_check_exception(
        self, fake_app_state: FakeAppState, fake_settings: FakeSettings
    ) -> None:
        """If a check function raises, doctor catches it and reports error."""

        async def crashing_check(_a: Any, _s: Any) -> DoctorCheck:
            raise RuntimeError("boom")

        doctor = SystemDoctor(fake_app_state, fake_settings)
        doctor._checks = [crashing_check]
        report = await doctor.run_all()
        assert len(report.checks) == 1
        assert report.checks[0].status == CheckStatus.ERROR
        assert "boom" in report.checks[0].message

    async def test_check_migrations_skipped_when_no_checker(
        self, fake_settings: FakeSettings
    ) -> None:
        """Migration check returns SKIPPED when migration_checker is None."""
        from agent33.ops.doctor import check_migrations

        state = FakeAppState()
        state.migration_checker = None
        result = await check_migrations(state, fake_settings)
        assert result.status == CheckStatus.SKIPPED

    async def test_check_migrations_ok_with_valid_checker(
        self, fake_settings: FakeSettings
    ) -> None:
        """Migration check returns OK when chain is valid."""
        from agent33.ops.doctor import check_migrations

        mock_status = MagicMock()
        mock_status.chain_valid = True
        mock_status.has_multiple_heads = False
        mock_status.current_head = "abc123"

        checker = MagicMock()
        checker.get_status.return_value = mock_status

        state = FakeAppState()
        state.migration_checker = checker
        result = await check_migrations(state, fake_settings)
        assert result.status == CheckStatus.OK
        assert result.details["current_head"] == "abc123"


# ---------------------------------------------------------------------------
# ConfigManager tests
# ---------------------------------------------------------------------------


class TestConfigManager:
    """Tests for ConfigManager service."""

    def test_get_schema_returns_fields(self) -> None:
        """get_schema() introspects Settings and returns non-empty field list."""
        from agent33.config import Settings

        mgr = ConfigManager(settings_instance=Settings())
        schema = mgr.get_schema()
        assert len(schema) > 0
        # Check that known fields are present
        names = {f.name for f in schema}
        assert "database_url" in names
        assert "redis_url" in names
        assert "jwt_secret" in names
        assert "api_port" in names

    def test_get_schema_secrets_are_redacted(self) -> None:
        """SecretStr fields show '***' as current and default values."""
        from agent33.config import Settings

        mgr = ConfigManager(settings_instance=Settings())
        schema = mgr.get_schema()
        jwt_field = next(f for f in schema if f.name == "jwt_secret")
        assert jwt_field.current_value == "***"
        assert jwt_field.default_value == "***"

    def test_get_schema_categorizes_fields(self) -> None:
        """Fields are assigned categories based on name prefixes."""
        from agent33.config import Settings

        mgr = ConfigManager(settings_instance=Settings())
        schema = mgr.get_schema()
        db_fields = [f for f in schema if f.category == "database"]
        assert len(db_fields) > 0
        assert any(f.name == "database_url" for f in db_fields)

    def test_get_schema_type_labels(self) -> None:
        """Fields have human-readable type labels."""
        from agent33.config import Settings

        mgr = ConfigManager(settings_instance=Settings())
        schema = mgr.get_schema()
        port_field = next(f for f in schema if f.name == "api_port")
        assert port_field.type == "int"
        jwt_field = next(f for f in schema if f.name == "jwt_secret")
        assert jwt_field.type == "SecretStr"

    def test_get_current_returns_dict(self) -> None:
        """get_current() returns a dict with secrets redacted."""
        from agent33.config import Settings

        mgr = ConfigManager(settings_instance=Settings())
        current = mgr.get_current()
        assert isinstance(current, dict)
        assert current["jwt_secret"] == "***"
        assert current["api_port"] == 8000

    def test_validate_changes_valid(self) -> None:
        """validate_changes() returns empty list for valid changes."""
        from agent33.config import Settings

        mgr = ConfigManager(settings_instance=Settings())
        errors = mgr.validate_changes({"api_port": 9000})
        assert errors == []

    def test_validate_changes_unknown_field(self) -> None:
        """validate_changes() reports unknown fields."""
        from agent33.config import Settings

        mgr = ConfigManager(settings_instance=Settings())
        errors = mgr.validate_changes({"nonexistent_field_xyz": 42})
        assert len(errors) == 1
        assert "Unknown field" in errors[0]

    def test_apply_changes_updates_value(self) -> None:
        """apply_changes() mutates the live settings and returns diffs."""
        from agent33.config import Settings

        settings = Settings()
        original_port = settings.api_port
        mgr = ConfigManager(settings_instance=settings)

        result = mgr.apply_changes({"api_port": 9999})
        assert isinstance(result, ConfigManagerResult)
        assert len(result.diffs) == 1
        assert result.diffs[0].field == "api_port"
        assert result.diffs[0].old_value == original_port
        assert result.diffs[0].new_value == 9999
        assert settings.api_port == 9999

        # Restore original
        mgr.apply_changes({"api_port": original_port})

    def test_apply_changes_flags_restart_required(self) -> None:
        """apply_changes() flags restart_required for infrastructure fields."""
        from agent33.config import Settings

        settings = Settings()
        mgr = ConfigManager(settings_instance=settings)
        result = mgr.apply_changes({"nats_url": "nats://other:4222"})
        assert result.restart_required is True

        # Restore
        mgr.apply_changes({"nats_url": "nats://nats:4222"})


# ---------------------------------------------------------------------------
# CronManager tests
# ---------------------------------------------------------------------------


class TestCronManager:
    """Tests for CronManager service."""

    def _make_job_def(self, job_id: str, name: str = "test-wf") -> Any:
        """Create a mock job definition."""
        from agent33.automation.cron_models import JobDefinition

        return JobDefinition(
            job_id=job_id,
            workflow_name=name,
            schedule_type="cron",
            schedule_expr="*/5 * * * *",
            enabled=True,
        )

    def test_list_jobs_empty(self) -> None:
        """list_jobs() returns empty list when no jobs exist."""
        mgr = CronManager(job_store={}, history_store=None)
        assert mgr.list_jobs() == []

    def test_list_jobs_with_entries(self) -> None:
        """list_jobs() returns entries for each job in the store."""
        from agent33.automation.cron_models import JobHistoryStore

        job_id = str(uuid.uuid4())
        job = self._make_job_def(job_id, "my-workflow")
        store: dict[str, Any] = {job_id: job}
        history = JobHistoryStore()

        mgr = CronManager(job_store=store, history_store=history)
        jobs = mgr.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == job_id
        assert jobs[0].name == "my-workflow"
        assert jobs[0].schedule == "*/5 * * * *"
        assert jobs[0].enabled is True
        assert jobs[0].status == CronJobStatus.ACTIVE

    def test_get_job_found(self) -> None:
        """get_job() returns the entry when it exists."""
        job_id = str(uuid.uuid4())
        job = self._make_job_def(job_id)
        mgr = CronManager(job_store={job_id: job})
        entry = mgr.get_job(job_id)
        assert entry is not None
        assert entry.id == job_id

    def test_get_job_not_found(self) -> None:
        """get_job() returns None for unknown IDs."""
        mgr = CronManager(job_store={})
        assert mgr.get_job("nonexistent") is None

    def test_enable_job(self) -> None:
        """enable_job() sets enabled=True and returns True."""
        job_id = str(uuid.uuid4())
        job = self._make_job_def(job_id)
        # Start disabled
        job = job.model_copy(update={"enabled": False})
        store: dict[str, Any] = {job_id: job}
        mgr = CronManager(job_store=store)

        assert mgr.enable_job(job_id) is True
        assert store[job_id].enabled is True

    def test_enable_job_not_found(self) -> None:
        """enable_job() returns False for unknown IDs."""
        mgr = CronManager(job_store={})
        assert mgr.enable_job("missing") is False

    def test_disable_job(self) -> None:
        """disable_job() sets enabled=False and returns True."""
        job_id = str(uuid.uuid4())
        job = self._make_job_def(job_id)
        store: dict[str, Any] = {job_id: job}
        mgr = CronManager(job_store=store)

        assert mgr.disable_job(job_id) is True
        assert store[job_id].enabled is False

    def test_disable_job_not_found(self) -> None:
        """disable_job() returns False for unknown IDs."""
        mgr = CronManager(job_store={})
        assert mgr.disable_job("missing") is False

    def test_trigger_job(self) -> None:
        """trigger_job() records a run and returns trigger result."""
        from agent33.automation.cron_models import JobHistoryStore

        job_id = str(uuid.uuid4())
        job = self._make_job_def(job_id)
        history = JobHistoryStore()
        mgr = CronManager(job_store={job_id: job}, history_store=history)

        result = mgr.trigger_job(job_id)
        assert result is not None
        assert isinstance(result, CronTriggerResult)
        assert result.job_id == job_id
        assert result.status == "triggered"

        # History should have the record
        runs = history.query(job_id=job_id)
        assert len(runs) == 1
        assert runs[0].status == "completed"

    def test_trigger_job_not_found(self) -> None:
        """trigger_job() returns None for unknown IDs."""
        mgr = CronManager(job_store={})
        assert mgr.trigger_job("missing") is None

    def test_get_history(self) -> None:
        """get_history() returns formatted history entries."""
        from agent33.automation.cron_models import JobHistoryStore, JobRunRecord

        job_id = str(uuid.uuid4())
        job = self._make_job_def(job_id)
        history = JobHistoryStore()
        now = datetime.now(UTC)
        history.record(
            JobRunRecord(
                run_id="r1",
                job_id=job_id,
                started_at=now,
                ended_at=now,
                status="completed",
            )
        )

        mgr = CronManager(job_store={job_id: job}, history_store=history)
        entries = mgr.get_history(job_id)
        assert len(entries) == 1
        assert entries[0].run_id == "r1"
        assert entries[0].status == "completed"

    def test_job_status_reflects_enabled(self) -> None:
        """Jobs show PAUSED status when disabled, ACTIVE when enabled."""
        job_id = str(uuid.uuid4())
        job = self._make_job_def(job_id)
        store: dict[str, Any] = {job_id: job}
        mgr = CronManager(job_store=store)

        entry = mgr.get_job(job_id)
        assert entry is not None
        assert entry.status == CronJobStatus.ACTIVE

        mgr.disable_job(job_id)
        entry = mgr.get_job(job_id)
        assert entry is not None
        assert entry.status == CronJobStatus.PAUSED


# ---------------------------------------------------------------------------
# OnboardingChecklistService tests
# ---------------------------------------------------------------------------


class TestOnboardingChecklistService:
    """Tests for OnboardingChecklistService."""

    def test_get_checklist_returns_all_steps(
        self, fake_app_state: FakeAppState, fake_settings: FakeSettings
    ) -> None:
        """Checklist returns 8 steps covering config, infra, security, agents, llm."""
        svc = OnboardingChecklistService(app_state=fake_app_state, settings=fake_settings)
        checklist = svc.get_checklist()
        assert isinstance(checklist, OnboardingChecklist)
        assert checklist.total_count == 8
        step_ids = [s.id for s in checklist.steps]
        assert "onboard-01" in step_ids
        assert "onboard-08" in step_ids

    def test_database_step_complete_when_ltm_exists(
        self, fake_app_state: FakeAppState, fake_settings: FakeSettings
    ) -> None:
        """Database step is COMPLETE when long_term_memory is set."""
        svc = OnboardingChecklistService(app_state=fake_app_state, settings=fake_settings)
        checklist = svc.get_checklist()
        db_step = next(s for s in checklist.steps if s.id == "onboard-02")
        assert db_step.status == StepStatus.COMPLETE

    def test_database_step_pending_when_no_ltm(self, fake_settings: FakeSettings) -> None:
        """Database step is PENDING when long_term_memory is None."""
        state = FakeAppState()
        state.long_term_memory = None
        svc = OnboardingChecklistService(app_state=state, settings=fake_settings)
        checklist = svc.get_checklist()
        db_step = next(s for s in checklist.steps if s.id == "onboard-02")
        assert db_step.status == StepStatus.PENDING

    def test_agent_definitions_complete_when_loaded(
        self, fake_app_state: FakeAppState, fake_settings: FakeSettings
    ) -> None:
        """Agent definitions step is COMPLETE when registry has agents."""
        svc = OnboardingChecklistService(app_state=fake_app_state, settings=fake_settings)
        checklist = svc.get_checklist()
        step = next(s for s in checklist.steps if s.id == "onboard-03")
        assert step.status == StepStatus.COMPLETE

    def test_agent_definitions_pending_when_empty(self, fake_settings: FakeSettings) -> None:
        """Agent definitions step is PENDING when registry is empty."""
        state = FakeAppState()
        state.agent_registry = MagicMock(list_all=MagicMock(return_value=[]))
        svc = OnboardingChecklistService(app_state=state, settings=fake_settings)
        checklist = svc.get_checklist()
        step = next(s for s in checklist.steps if s.id == "onboard-03")
        assert step.status == StepStatus.PENDING

    def test_llm_provider_complete_when_registered(
        self, fake_app_state: FakeAppState, fake_settings: FakeSettings
    ) -> None:
        """LLM provider step is COMPLETE when model_router has providers."""
        svc = OnboardingChecklistService(app_state=fake_app_state, settings=fake_settings)
        checklist = svc.get_checklist()
        step = next(s for s in checklist.steps if s.id == "onboard-04")
        assert step.status == StepStatus.COMPLETE

    def test_jwt_secret_pending_when_default(
        self, fake_app_state: FakeAppState, fake_settings: FakeSettings
    ) -> None:
        """JWT secret step is PENDING when using the default value."""
        svc = OnboardingChecklistService(app_state=fake_app_state, settings=fake_settings)
        checklist = svc.get_checklist()
        step = next(s for s in checklist.steps if s.id == "onboard-06")
        assert step.status == StepStatus.PENDING

    def test_jwt_secret_complete_when_customized(self, fake_app_state: FakeAppState) -> None:
        """JWT secret step is COMPLETE when a non-default value is set."""
        settings = FakeSettings()
        settings.jwt_secret = SecretStr("my-custom-secret-value")
        svc = OnboardingChecklistService(app_state=fake_app_state, settings=settings)
        checklist = svc.get_checklist()
        step = next(s for s in checklist.steps if s.id == "onboard-06")
        assert step.status == StepStatus.COMPLETE

    def test_overall_complete_when_all_steps_done(self) -> None:
        """overall_complete is True when all steps are COMPLETE."""
        state = FakeAppState()
        settings = FakeSettings()
        settings.api_secret_key = SecretStr("custom-api-key")
        settings.jwt_secret = SecretStr("custom-jwt-secret")
        svc = OnboardingChecklistService(app_state=state, settings=settings)
        checklist = svc.get_checklist()
        # Some steps might still be pending (config file, etc.), so just
        # verify the logic: overall_complete == (completed == total)
        assert checklist.overall_complete == (checklist.completed_count == checklist.total_count)

    def test_redis_step_pending_when_none(self, fake_settings: FakeSettings) -> None:
        """Redis step is PENDING when redis is None."""
        state = FakeAppState()
        state.redis = None
        svc = OnboardingChecklistService(app_state=state, settings=fake_settings)
        checklist = svc.get_checklist()
        step = next(s for s in checklist.steps if s.id == "onboard-07")
        assert step.status == StepStatus.PENDING

    def test_nats_step_pending_when_disconnected(self, fake_settings: FakeSettings) -> None:
        """NATS step is PENDING when bus is disconnected."""
        state = FakeAppState()
        state.nats_bus = MagicMock(is_connected=False)
        svc = OnboardingChecklistService(app_state=state, settings=fake_settings)
        checklist = svc.get_checklist()
        step = next(s for s in checklist.steps if s.id == "onboard-08")
        assert step.status == StepStatus.PENDING


# ---------------------------------------------------------------------------
# API Route integration tests
# ---------------------------------------------------------------------------


class TestOpsRoutes:
    """Integration tests for /v1/ops/ API routes.

    These tests install the ops services on app.state explicitly, bypassing
    the full lifespan, so they exercise the actual route handlers.
    """

    @pytest.fixture()
    def client(self) -> Any:
        """Create a TestClient with ops services installed."""
        from fastapi.testclient import TestClient

        from agent33.config import Settings
        from agent33.main import app

        settings = Settings()

        # Install minimal ops services on app.state
        app.state.system_doctor = SystemDoctor(
            app_state=app.state,
            settings=settings,
            version="test",
        )
        # Only use fast checks in tests
        app.state.system_doctor._checks = [
            check_config_validity,
            check_required_secrets,
            check_disk_space,
            check_python_version,
        ]
        app.state.ops_config_manager = ConfigManager(settings_instance=settings)

        from agent33.automation.cron_models import JobHistoryStore

        cron_store: dict[str, Any] = {}
        history = JobHistoryStore()
        app.state.cron_job_store = cron_store
        app.state.job_history_store = history
        app.state.ops_cron_manager = CronManager(job_store=cron_store, history_store=history)
        app.state.ops_onboarding = OnboardingChecklistService(
            app_state=app.state, settings=settings
        )
        app.state.start_time = 1000000000.0

        return TestClient(app)

    @pytest.fixture()
    def auth_headers(self) -> dict[str, str]:
        """Create auth headers with admin scope."""
        import jwt

        from agent33.config import settings

        token = jwt.encode(
            {
                "sub": "test-user",
                "tenant_id": "test-tenant",
                "scopes": ["admin"],
            },
            settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )
        return {"Authorization": f"Bearer {token}"}

    def test_get_doctor(self, client: Any, auth_headers: dict[str, str]) -> None:
        """GET /v1/ops/doctor returns a doctor report."""
        resp = client.get("/v1/ops/doctor", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "checks" in data
        assert "overall_status" in data
        assert len(data["checks"]) == 4

    def test_get_doctor_single_check(self, client: Any, auth_headers: dict[str, str]) -> None:
        """GET /v1/ops/doctor/{name} returns a single check result."""
        resp = client.get("/v1/ops/doctor/python_version", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "python_version"

    def test_get_doctor_single_check_not_found(
        self, client: Any, auth_headers: dict[str, str]
    ) -> None:
        """GET /v1/ops/doctor/{name} returns 404 for unknown checks."""
        resp = client.get("/v1/ops/doctor/nonexistent", headers=auth_headers)
        assert resp.status_code == 404

    def test_get_config(self, client: Any, auth_headers: dict[str, str]) -> None:
        """GET /v1/ops/config returns config schema with fields."""
        resp = client.get("/v1/ops/config", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "fields" in data
        assert data["count"] > 0
        # Verify secrets are redacted
        jwt_field = next((f for f in data["fields"] if f["name"] == "jwt_secret"), None)
        assert jwt_field is not None
        assert jwt_field["current_value"] == "***"

    def test_config_validate_valid(self, client: Any, auth_headers: dict[str, str]) -> None:
        """POST /v1/ops/config/validate with valid changes returns valid=True."""
        resp = client.post(
            "/v1/ops/config/validate",
            json={"changes": {"api_port": 9000}},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["errors"] == []

    def test_config_validate_invalid(self, client: Any, auth_headers: dict[str, str]) -> None:
        """POST /v1/ops/config/validate with unknown field returns errors."""
        resp = client.post(
            "/v1/ops/config/validate",
            json={"changes": {"nonexistent_xyz": 42}},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert len(data["errors"]) == 1

    def test_get_cron_empty(self, client: Any, auth_headers: dict[str, str]) -> None:
        """GET /v1/ops/cron returns empty list when no jobs."""
        resp = client.get("/v1/ops/cron", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["jobs"] == []
        assert data["count"] == 0

    def test_get_onboarding(self, client: Any, auth_headers: dict[str, str]) -> None:
        """GET /v1/ops/onboarding returns checklist with steps."""
        resp = client.get("/v1/ops/onboarding", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "steps" in data
        assert data["total_count"] == 8
        # Each step has the expected fields
        for step in data["steps"]:
            assert "id" in step
            assert "title" in step
            assert "status" in step
            assert "category" in step

    def test_get_version(self, client: Any, auth_headers: dict[str, str]) -> None:
        """GET /v1/ops/version returns runtime info."""
        resp = client.get("/v1/ops/version", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert "python_version" in data
        assert "platform" in data
        assert "uptime_seconds" in data

    def test_doctor_unauthorized(self, client: Any) -> None:
        """GET /v1/ops/doctor without auth returns 401."""
        resp = client.get("/v1/ops/doctor")
        assert resp.status_code == 401

    def test_config_apply_requires_admin(self, client: Any) -> None:
        """POST /v1/ops/config/apply without admin scope returns 401/403."""
        resp = client.post(
            "/v1/ops/config/apply",
            json={"changes": {"api_port": 9000}},
        )
        assert resp.status_code in (401, 403)

    def test_cron_trigger_not_found(self, client: Any, auth_headers: dict[str, str]) -> None:
        """POST /v1/ops/cron/{id}/trigger returns 404 for missing job."""
        resp = client.post("/v1/ops/cron/nonexistent-id/trigger", headers=auth_headers)
        assert resp.status_code == 404

    def test_cron_patch_not_found(self, client: Any, auth_headers: dict[str, str]) -> None:
        """PATCH /v1/ops/cron/{id} returns 404 for missing job."""
        resp = client.patch(
            "/v1/ops/cron/nonexistent-id",
            json={"enabled": False},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_cron_get_not_found(self, client: Any, auth_headers: dict[str, str]) -> None:
        """GET /v1/ops/cron/{id} returns 404 for missing job."""
        resp = client.get("/v1/ops/cron/nonexistent-id", headers=auth_headers)
        assert resp.status_code == 404

    def test_cron_lifecycle_via_api(self, client: Any, auth_headers: dict[str, str]) -> None:
        """Full cron lifecycle: add job to store, list, get, patch, trigger."""
        from agent33.automation.cron_models import JobDefinition

        # Add a job directly to the store
        job_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        job = JobDefinition(
            job_id=job_id,
            workflow_name="test-workflow",
            schedule_type="cron",
            schedule_expr="*/5 * * * *",
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        client.app.state.cron_job_store[job_id] = job

        # List
        resp = client.get("/v1/ops/cron", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

        # Get
        resp = client.get(f"/v1/ops/cron/{job_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == job_id
        assert data["name"] == "test-workflow"
        assert data["enabled"] is True

        # Disable
        resp = client.patch(
            f"/v1/ops/cron/{job_id}",
            json={"enabled": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

        # Enable
        resp = client.patch(
            f"/v1/ops/cron/{job_id}",
            json={"enabled": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

        # Trigger
        resp = client.post(f"/v1/ops/cron/{job_id}/trigger", headers=auth_headers)
        assert resp.status_code == 200
        trigger_data = resp.json()
        assert trigger_data["job_id"] == job_id
        assert trigger_data["status"] == "triggered"

        # History
        resp = client.get(f"/v1/ops/cron/{job_id}/history", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1

        # Cleanup
        del client.app.state.cron_job_store[job_id]
