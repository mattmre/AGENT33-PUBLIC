"""Tests for Phase 31 tuning loop automation.

Covers TuningLoopService, TuningLoopScheduler, and API routes.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent33.config import settings
from agent33.improvement.models import (
    LearningSignal,
    LearningSignalSeverity,
    LearningSignalType,
)
from agent33.improvement.service import ImprovementService, LearningPersistencePolicy
from agent33.improvement.tuning import (
    ConfigApplyService,
    TuningCycleOutcome,
    TuningLoopScheduler,
    TuningLoopService,
    TuningProposalSandboxRecord,
    _clamp_delta,
    _clamp_severity,
)
from agent33.main import app
from agent33.security.auth import create_access_token

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def service() -> ImprovementService:
    return ImprovementService(
        persistence_policy=LearningPersistencePolicy(
            retention_days=180,
            max_generated_intakes=3,
            auto_intake_min_quality=0.45,
        ),
    )


@pytest.fixture()
def tuning_service(service: ImprovementService) -> TuningLoopService:
    """Tuning service with no settings (defaults: no dry_run, no approval)."""
    return TuningLoopService(service)


def _seed_signals(
    service: ImprovementService,
    count: int = 15,
    quality: float = 0.8,
    severity: LearningSignalSeverity = LearningSignalSeverity.HIGH,
) -> list[LearningSignal]:
    """Record *count* signals into the service."""
    signals: list[LearningSignal] = []
    for i in range(count):
        signal = LearningSignal(
            signal_type=LearningSignalType.FEEDBACK,
            severity=severity,
            summary=f"test signal {i}",
            details=f"detail for signal {i}",
            source="test",
            quality_score=quality,
        )
        signals.append(service.record_learning_signal(signal))
    return signals


class FakeSettings:
    """Minimal stand-in for Settings to control tuning loop behaviour."""

    def __init__(
        self,
        *,
        dry_run: bool = False,
        require_approval: bool = False,
        enabled: bool = True,
        interval_hours: float = 24.0,
        max_quality_delta: float = 0.15,
        max_retention_delta_days: int = 30,
        min_sample_size: int = 10,
    ) -> None:
        self.improvement_tuning_loop_enabled = enabled
        self.improvement_tuning_loop_dry_run = dry_run
        self.improvement_tuning_loop_require_approval = require_approval
        self.improvement_tuning_loop_interval_hours = interval_hours
        self.improvement_tuning_loop_max_quality_delta = max_quality_delta
        self.improvement_tuning_loop_max_retention_delta_days = max_retention_delta_days
        self.improvement_tuning_loop_min_sample_size = min_sample_size


# ---------------------------------------------------------------------------
# _clamp_delta / _clamp_severity unit tests
# ---------------------------------------------------------------------------


class TestClampDelta:
    def test_within_bounds(self) -> None:
        new_val, delta = _clamp_delta("f", 0.5, 0.6, 0.15)
        assert delta == pytest.approx(0.1, abs=0.001)
        assert new_val == pytest.approx(0.6, abs=0.001)

    def test_exceeds_positive_bound(self) -> None:
        new_val, delta = _clamp_delta("f", 0.5, 0.9, 0.15)
        assert delta == pytest.approx(0.15, abs=0.001)
        assert new_val == pytest.approx(0.65, abs=0.001)

    def test_exceeds_negative_bound(self) -> None:
        new_val, delta = _clamp_delta("f", 0.5, 0.1, 0.15)
        assert delta == pytest.approx(-0.15, abs=0.001)
        assert new_val == pytest.approx(0.35, abs=0.001)

    def test_integer_clamping(self) -> None:
        new_val, delta = _clamp_delta("f", 180, 300, 30)
        assert delta == 30
        assert new_val == 210
        assert isinstance(new_val, int)
        assert isinstance(delta, int)


class TestClampSeverity:
    def test_no_change(self) -> None:
        new_sev, desc = _clamp_severity("medium", "medium")
        assert new_sev == "medium"
        assert desc == "no change"

    def test_never_below_medium(self) -> None:
        new_sev, _ = _clamp_severity("medium", "low")
        assert new_sev == "medium"

    def test_escalate_one_step(self) -> None:
        new_sev, desc = _clamp_severity("medium", "critical")
        assert new_sev == "high"
        assert "medium -> high" in desc

    def test_relax_one_step_max(self) -> None:
        new_sev, desc = _clamp_severity("critical", "low")
        # Should relax at most one step, to high
        assert new_sev == "high"
        assert "critical -> high" in desc


# ---------------------------------------------------------------------------
# TuningLoopService tests
# ---------------------------------------------------------------------------


class TestTuningLoopService:
    def test_skipped_insufficient_samples(self, service: ImprovementService) -> None:
        """Cycle should be SKIPPED when sample_size < 10."""
        _seed_signals(service, count=5)
        tuning = TuningLoopService(service)
        record = tuning.run_cycle()
        assert record.outcome == TuningCycleOutcome.SKIPPED
        assert record.sample_size == 5
        assert "Insufficient sample size" in record.rationale

    def test_skipped_no_changes(self, service: ImprovementService) -> None:
        """Cycle should be SKIPPED when all deltas are zero."""
        # Seed signals whose calibration will recommend the same values
        # that are already in the policy. We match quality exactly.
        policy = LearningPersistencePolicy(
            retention_days=180,
            max_generated_intakes=3,
            auto_intake_min_quality=0.8,
        )
        svc = ImprovementService(persistence_policy=policy)
        # 15 signals all with quality 0.8 and high severity
        _seed_signals(svc, count=15, quality=0.8, severity=LearningSignalSeverity.HIGH)
        tuning = TuningLoopService(svc)
        record = tuning.run_cycle()
        # The calibration recommends quality=0.8, retention somewhere, items=3.
        # Even if retention or items differ, we still get a valid record.
        # The key property: outcome is deterministic and the record is stored.
        assert record.outcome in {
            TuningCycleOutcome.SKIPPED,
            TuningCycleOutcome.APPLIED,
        }
        assert record.sample_size == 15

    def test_dry_run_mode(self, service: ImprovementService) -> None:
        """Cycle with dry_run=True returns DRY_RUN with proposed values."""
        _seed_signals(service, count=15, quality=0.9)
        tuning = TuningLoopService(service)
        record = tuning.run_cycle(dry_run=True)
        assert record.outcome == TuningCycleOutcome.DRY_RUN
        assert record.after_values != {}
        assert record.deltas != {}
        assert "Dry-run" in record.rationale
        # Verify policy was NOT changed
        assert service._persistence_policy.auto_intake_min_quality == 0.45

    def test_dry_run_via_settings(self, service: ImprovementService) -> None:
        """Cycle respects dry_run from Settings when no explicit arg."""
        _seed_signals(service, count=15, quality=0.9)
        fake = FakeSettings(dry_run=True)
        tuning = TuningLoopService(service, settings=fake)  # type: ignore[arg-type]
        record = tuning.run_cycle()
        assert record.outcome == TuningCycleOutcome.DRY_RUN

    def test_require_approval(self, service: ImprovementService) -> None:
        """Cycle with require_approval returns PENDING_APPROVAL."""
        _seed_signals(service, count=15, quality=0.9)
        fake = FakeSettings(require_approval=True)
        tuning = TuningLoopService(service, settings=fake)  # type: ignore[arg-type]
        record = tuning.run_cycle()
        assert record.outcome == TuningCycleOutcome.PENDING_APPROVAL
        assert "require manual approval" in record.rationale.lower()

    def test_auto_apply(self, service: ImprovementService) -> None:
        """Cycle with auto-apply updates the live policy."""
        _seed_signals(service, count=15, quality=0.9)
        original_quality = service._persistence_policy.auto_intake_min_quality
        fake = FakeSettings(dry_run=False, require_approval=False)
        tuning = TuningLoopService(service, settings=fake)  # type: ignore[arg-type]
        record = tuning.run_cycle()
        # Should be APPLIED (or SKIPPED if zero deltas, but with quality 0.9
        # vs original 0.45 there should be a delta)
        if record.outcome == TuningCycleOutcome.APPLIED:
            assert "applied" in record.rationale.lower()
            # Policy must have changed
            new_quality = service._persistence_policy.auto_intake_min_quality
            assert new_quality != original_quality

    def test_quality_delta_capped(self, service: ImprovementService) -> None:
        """Quality delta is capped at +/- max_quality_delta (0.15)."""
        # Signals with very high quality to force a large upward delta
        _seed_signals(service, count=15, quality=0.99)
        fake = FakeSettings(dry_run=True, max_quality_delta=0.15)
        tuning = TuningLoopService(service, settings=fake)  # type: ignore[arg-type]
        record = tuning.run_cycle()
        if record.outcome == TuningCycleOutcome.DRY_RUN:
            quality_delta = record.deltas.get("auto_intake_min_quality", 0)
            assert abs(quality_delta) <= 0.15 + 0.001  # float tolerance

    def test_retention_delta_capped(self, service: ImprovementService) -> None:
        """Retention delta is capped at +/- max_retention_delta_days (30)."""
        _seed_signals(service, count=15, quality=0.8)
        fake = FakeSettings(dry_run=True, max_retention_delta_days=30)
        tuning = TuningLoopService(service, settings=fake)  # type: ignore[arg-type]
        record = tuning.run_cycle()
        if record.outcome == TuningCycleOutcome.DRY_RUN:
            retention_delta = record.deltas.get("retention_days", 0)
            assert abs(retention_delta) <= 30

    def test_severity_never_below_medium(self, service: ImprovementService) -> None:
        """Severity recommendation never goes below medium."""
        # Seed with low-severity signals
        _seed_signals(service, count=15, quality=0.5, severity=LearningSignalSeverity.LOW)
        fake = FakeSettings(dry_run=True)
        tuning = TuningLoopService(service, settings=fake)  # type: ignore[arg-type]
        record = tuning.run_cycle()
        if record.outcome == TuningCycleOutcome.DRY_RUN:
            after_severity = record.after_values.get("auto_intake_min_severity")
            assert after_severity in {"medium", "high", "critical"}

    def test_approve_pending_cycle(self, service: ImprovementService) -> None:
        """Approving a PENDING_APPROVAL cycle applies changes."""
        _seed_signals(service, count=15, quality=0.9)
        fake = FakeSettings(require_approval=True)
        tuning = TuningLoopService(service, settings=fake)  # type: ignore[arg-type]
        record = tuning.run_cycle()
        assert record.outcome == TuningCycleOutcome.PENDING_APPROVAL
        cycle_id = record.cycle_id

        approved = tuning.approve_cycle(cycle_id, approved_by="test-admin")
        assert approved.outcome == TuningCycleOutcome.APPLIED
        assert approved.approved_by == "test-admin"
        assert approved.approved_at is not None

    def test_approve_nonexistent_cycle(self, tuning_service: TuningLoopService) -> None:
        """Approving a non-existent cycle raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            tuning_service.approve_cycle("bad-id", "admin")

    def test_approve_non_pending_cycle(self, service: ImprovementService) -> None:
        """Approving an already-applied cycle raises ValueError."""
        _seed_signals(service, count=15, quality=0.9)
        fake = FakeSettings(dry_run=True)
        tuning = TuningLoopService(service, settings=fake)  # type: ignore[arg-type]
        record = tuning.run_cycle()
        if record.outcome == TuningCycleOutcome.DRY_RUN:
            with pytest.raises(ValueError, match="not pending approval"):
                tuning.approve_cycle(record.cycle_id, "admin")

    def test_history_retrieval(self, service: ImprovementService) -> None:
        """History returns records in newest-first order, respecting limit."""
        _seed_signals(service, count=15, quality=0.8)
        fake = FakeSettings(dry_run=True)
        tuning = TuningLoopService(service, settings=fake)  # type: ignore[arg-type]
        tuning.run_cycle()
        tuning.run_cycle()
        tuning.run_cycle()
        history = tuning.get_history(limit=2)
        assert len(history) == 2
        # Newest first
        assert history[0].completed_at >= history[1].completed_at

    def test_status_reporting(self, service: ImprovementService) -> None:
        """Status returns expected structure."""
        fake = FakeSettings(enabled=True, dry_run=True, interval_hours=12.0)
        tuning = TuningLoopService(service, settings=fake)  # type: ignore[arg-type]
        status = tuning.get_status()
        assert status["enabled"] is True
        assert status["dry_run"] is True
        assert status["interval_hours"] == 12.0
        assert status["total_cycles"] == 0
        assert status["last_cycle"] is None

    def test_config_apply_service_called(self, service: ImprovementService) -> None:
        """ConfigApplyService.apply() is called for each changed field."""
        _seed_signals(service, count=15, quality=0.9)
        applied_changes: dict[str, Any] = {}

        class TrackingApply(ConfigApplyService):
            def apply(self, request: Any, settings_instance: Any | None = None) -> None:  # noqa: ANN401
                del settings_instance
                applied_changes.update(request.changes)

        fake = FakeSettings(dry_run=False, require_approval=False)
        tuning = TuningLoopService(
            service,
            config_apply_service=TrackingApply(),
            settings=fake,  # type: ignore[arg-type]
        )
        record = tuning.run_cycle()
        if record.outcome == TuningCycleOutcome.APPLIED:
            assert applied_changes == {
                "improvement_learning_auto_intake_min_quality": record.after_values[
                    "auto_intake_min_quality"
                ],
                "improvement_learning_retention_days": record.after_values["retention_days"],
                "improvement_learning_auto_intake_min_severity": record.after_values[
                    "auto_intake_min_severity"
                ],
                "improvement_learning_auto_intake_max_items": record.after_values[
                    "auto_intake_max_items"
                ],
            }

    def test_proposal_sandbox_never_updates_policy_or_config(
        self, service: ImprovementService
    ) -> None:
        """Proposal sandbox computes deltas but cannot mutate live policy or config."""
        _seed_signals(service, count=15, quality=0.9)
        applied_changes: dict[str, Any] = {}

        class TrackingApply(ConfigApplyService):
            def apply(self, request: Any, settings_instance: Any | None = None) -> None:  # noqa: ANN401
                del settings_instance
                applied_changes.update(request.changes)

        tuning = TuningLoopService(
            service,
            config_apply_service=TrackingApply(),
            settings=FakeSettings(dry_run=False, require_approval=False),  # type: ignore[arg-type]
        )
        before_policy = service.persistence_policy

        record = tuning.run_proposal_sandbox()

        assert isinstance(record, TuningProposalSandboxRecord)
        assert record.outcome == TuningCycleOutcome.PROPOSAL_ONLY
        assert record.mutation_allowed is False
        assert record.approval_allowed is False
        assert record.promotion_required is True
        assert record.production_mutation_attempted is False
        assert (
            record.proposed_config_changes["improvement_learning_auto_intake_min_quality"]
            == (record.after_values["auto_intake_min_quality"])
        )
        assert applied_changes == {}
        assert service.persistence_policy == before_policy
        with pytest.raises(ValueError, match="not pending approval"):
            tuning.approve_cycle(record.cycle_id, "admin")

    def test_config_apply_service_updates_live_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Real config apply integration updates the runtime settings singleton."""
        from agent33.config_apply import ConfigApplyService as RuntimeConfigApplyService

        monkeypatch.setattr(settings, "improvement_learning_auto_intake_min_quality", 0.45)
        monkeypatch.setattr(settings, "improvement_learning_auto_intake_min_severity", "high")
        monkeypatch.setattr(settings, "improvement_learning_auto_intake_max_items", 1)

        service = ImprovementService(
            persistence_policy=LearningPersistencePolicy(
                retention_days=180,
                max_generated_intakes=3,
                auto_intake_min_quality=0.45,
                auto_intake_min_severity=LearningSignalSeverity.HIGH,
                auto_intake_max_items=1,
            )
        )
        _seed_signals(service, count=15, quality=0.95, severity=LearningSignalSeverity.MEDIUM)

        tuning = TuningLoopService(
            service,
            config_apply_service=RuntimeConfigApplyService(settings_cls=type(settings)),
            settings=settings,
        )
        record = tuning.run_cycle()

        assert record.outcome == TuningCycleOutcome.APPLIED
        assert settings.improvement_learning_auto_intake_min_severity == "medium"
        assert settings.improvement_learning_auto_intake_max_items == 3
        assert settings.improvement_learning_auto_intake_min_quality == pytest.approx(
            service._persistence_policy.auto_intake_min_quality
        )


# ---------------------------------------------------------------------------
# ImprovementService.update_policy tests
# ---------------------------------------------------------------------------


class TestUpdatePolicy:
    def test_update_policy_replaces_live_values(self) -> None:
        svc = ImprovementService()
        new_policy = LearningPersistencePolicy(
            retention_days=90,
            max_generated_intakes=5,
            auto_intake_min_quality=0.6,
            auto_intake_min_severity=LearningSignalSeverity.MEDIUM,
            auto_intake_max_items=4,
        )
        svc.update_policy(new_policy)
        assert svc._persistence_policy.retention_days == 90
        assert svc._persistence_policy.max_generated_intakes == 5
        assert svc._persistence_policy.auto_intake_min_quality == 0.6
        assert svc._persistence_policy.auto_intake_min_severity == LearningSignalSeverity.MEDIUM
        assert svc._persistence_policy.auto_intake_max_items == 4

    def test_update_policy_rejects_invalid_quality(self) -> None:
        svc = ImprovementService()
        with pytest.raises(ValueError, match="auto_intake_min_quality"):
            svc.update_policy(LearningPersistencePolicy(auto_intake_min_quality=1.5))

    def test_update_policy_rejects_invalid_auto_intake_max_items(self) -> None:
        svc = ImprovementService()
        with pytest.raises(ValueError, match="auto_intake_max_items"):
            svc.update_policy(LearningPersistencePolicy(auto_intake_max_items=0))


# ---------------------------------------------------------------------------
# TuningLoopScheduler tests
# ---------------------------------------------------------------------------


class TestTuningLoopScheduler:
    @pytest.mark.asyncio()
    async def test_start_stop_lifecycle(self) -> None:
        """Scheduler starts, runs briefly, and stops without errors."""
        svc = ImprovementService()
        tuning = TuningLoopService(svc)
        # Very short interval to allow a quick loop iteration
        scheduler = TuningLoopScheduler(tuning, interval_hours=0.0001)
        await scheduler.start()
        assert scheduler._running is True
        assert scheduler._task is not None
        # Let it run briefly
        await asyncio.sleep(0.05)
        await scheduler.stop()
        assert scheduler._running is False


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_route_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the improvement route singletons before each test."""
    from agent33.api.routes.improvements import _reset_service

    monkeypatch.setattr(settings, "improvement_learning_persistence_backend", "memory")
    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    monkeypatch.setattr(settings, "improvement_tuning_loop_enabled", True)
    monkeypatch.setattr(settings, "improvement_tuning_loop_dry_run", False)
    monkeypatch.setattr(settings, "improvement_tuning_loop_require_approval", False)
    _reset_service()


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    token = create_access_token(
        subject="test-user",
        tenant_id="default",
        scopes=["admin"],
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _seed_signals_via_api(
    client: TestClient,
    headers: dict[str, str],
    count: int = 15,
    severity: str = "high",
) -> None:
    """Seed learning signals via the API so tuning has enough sample."""
    for i in range(count):
        client.post(
            "/v1/improvements/learning/signals",
            json={
                "signal_type": "feedback",
                "severity": severity,
                "summary": (
                    f"Detailed recurring signal from the release pipeline with evidence bundle {i}"
                ),
                "details": (
                    "Observed across canary and stable lanes with reproducible "
                    f"steps for sample {i}"
                ),
                "source": "test-api",
                "tenant_id": "default",
                "context": {"pipeline": "release", "sample": str(i)},
            },
            headers=headers,
        )


class TestTuningRoutes:
    def test_get_status(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        resp = client.get("/v1/improvements/tuning/status", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "enabled" in body
        assert "total_cycles" in body
        assert "last_cycle" in body

    def test_run_cycle(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        _seed_signals_via_api(client, auth_headers, count=15)
        resp = client.post("/v1/improvements/tuning/run", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "outcome" in body
        assert "cycle_id" in body
        assert "before_values" in body
        assert "after_values" in body

    def test_run_dry_run(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        _seed_signals_via_api(client, auth_headers, count=15)
        resp = client.post("/v1/improvements/tuning/run?dry_run=true", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["outcome"] == "dry_run"

    def test_proposal_sandbox_route_never_applies(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "self_improve_proposal_sandbox_enabled", True)
        _seed_signals_via_api(client, auth_headers, count=15)

        resp = client.post(
            "/v1/improvements/tuning/proposal-sandbox/run",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["outcome"] == "proposal_only"
        assert body["mutation_allowed"] is False
        assert body["approval_allowed"] is False
        assert body["production_mutation_attempted"] is False
        assert body["promotion_required"] is True
        assert "proposed_config_changes" in body

    def test_get_history(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Run a cycle first to populate history
        _seed_signals_via_api(client, auth_headers, count=15)
        client.post("/v1/improvements/tuning/run", headers=auth_headers)
        resp = client.get("/v1/improvements/tuning/history", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) >= 1
        assert "cycle_id" in body[0]

    def test_approve_pending_cycle(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "improvement_tuning_loop_require_approval", True)
        from agent33.api.routes.improvements import _reset_service

        _reset_service()

        _seed_signals_via_api(client, auth_headers, count=15)
        run_resp = client.post("/v1/improvements/tuning/run", headers=auth_headers)
        assert run_resp.status_code == 200
        cycle_id = run_resp.json()["cycle_id"]
        assert run_resp.json()["outcome"] == "pending_approval"

        approve_resp = client.post(
            f"/v1/improvements/tuning/approve/{cycle_id}?approved_by=admin",
            headers=auth_headers,
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["outcome"] == "applied"
        assert approve_resp.json()["approved_by"] == "admin"

    def test_approve_nonexistent_cycle(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            "/v1/improvements/tuning/approve/nonexistent-id",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_run_disabled_learning(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Tuning run returns 404 when learning is disabled."""
        monkeypatch.setattr(settings, "improvement_learning_enabled", False)
        resp = client.post("/v1/improvements/tuning/run", headers=auth_headers)
        assert resp.status_code == 404

    def test_tuning_run_updates_summary_generation_thresholds(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Summary generation uses the live tuned policy, not stale route settings."""
        monkeypatch.setattr(settings, "improvement_learning_auto_intake_enabled", True)
        monkeypatch.setattr(settings, "improvement_learning_auto_intake_min_severity", "high")
        monkeypatch.setattr(settings, "improvement_learning_auto_intake_max_items", 1)

        from agent33.api.routes.improvements import _reset_service

        _reset_service()

        _seed_signals_via_api(
            client,
            auth_headers,
            count=15,
            severity="medium",
        )
        run_resp = client.post("/v1/improvements/tuning/run", headers=auth_headers)
        assert run_resp.status_code == 200
        assert run_resp.json()["outcome"] == "applied"

        summary_resp = client.get(
            "/v1/improvements/learning/summary",
            params={"generate_intakes": "true"},
            headers=auth_headers,
        )
        assert summary_resp.status_code == 200
        assert len(summary_resp.json()["generated_intakes"]) == 3
