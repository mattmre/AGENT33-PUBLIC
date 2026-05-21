"""Phase 19 — Release & Sync Automation.

Tests cover:
- Release models (enums, defaults, ID generation)
- Pre-release checklist (RL-01..RL-08, major vs minor)
- Sync engine (rule matching, dry-run, execution, validation)
- Rollback manager (decision matrix, lifecycle)
- Release service (CRUD, lifecycle, checklist, sync, rollback)
- API endpoints (REST lifecycle)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from starlette.testclient import TestClient

from agent33.component_security.models import FindingsSummary, SecurityGatePolicy
from agent33.release.checklist import ChecklistEvaluator, build_checklist
from agent33.release.models import (
    CheckStatus,
    Release,
    ReleaseStatus,
    ReleaseType,
    RollbackRecord,
    RollbackStatus,
    RollbackType,
    SyncExecution,
    SyncFrequency,
    SyncRule,
    SyncStatus,
    SyncStrategy,
)
from agent33.release.rollback import RollbackManager
from agent33.release.service import (
    InvalidReleaseTransitionError,
    ReleaseNotFoundError,
    ReleaseService,
)
from agent33.release.sync import SyncEngine

# ===================================================================
# Release Models
# ===================================================================


class TestReleaseModels:
    """Test release data models."""

    def test_release_default_status_planned(self):
        release = Release(version="1.0.0")
        assert release.status == ReleaseStatus.PLANNED

    def test_release_id_has_prefix(self):
        release = Release(version="1.0.0")
        assert release.release_id.startswith("REL-")

    def test_release_unique_ids(self):
        r1 = Release(version="1.0.0")
        r2 = Release(version="1.0.1")
        assert r1.release_id != r2.release_id

    def test_sync_rule_id_prefix(self):
        rule = SyncRule()
        assert rule.rule_id.startswith("SYN-")

    def test_rollback_record_id_prefix(self):
        record = RollbackRecord()
        assert record.rollback_id.startswith("RBK-")

    def test_sync_execution_id_prefix(self):
        exe = SyncExecution()
        assert exe.execution_id.startswith("SXE-")

    def test_all_enums_have_values(self):
        assert len(ReleaseType) == 3
        assert len(ReleaseStatus) == 7
        assert len(CheckStatus) == 5
        assert len(SyncStrategy) == 3
        assert len(SyncFrequency) == 3
        assert len(SyncStatus) == 5
        assert len(RollbackType) == 4
        assert len(RollbackStatus) == 4


# ===================================================================
# Pre-Release Checklist
# ===================================================================


class TestChecklist:
    """Test pre-release checklist (RL-01..RL-08)."""

    def test_build_checklist_minor(self):
        release = Release(version="1.1.0", release_type=ReleaseType.MINOR)
        checks = build_checklist(release)
        assert len(checks) == 8
        # RL-07 should NOT be required for minor
        rl07 = next(c for c in checks if c.check_id == "RL-07")
        assert rl07.required is False

    def test_build_checklist_major(self):
        release = Release(version="2.0.0", release_type=ReleaseType.MAJOR)
        checks = build_checklist(release)
        # RL-07 should be required for major
        rl07 = next(c for c in checks if c.check_id == "RL-07")
        assert rl07.required is True

    def test_build_checklist_patch(self):
        release = Release(version="1.0.1", release_type=ReleaseType.PATCH)
        checks = build_checklist(release)
        rl07 = next(c for c in checks if c.check_id == "RL-07")
        assert rl07.required is False

    def test_evaluate_all_pending_fails(self):
        release = Release(version="1.0.0")
        checks = build_checklist(release)
        evaluator = ChecklistEvaluator()
        passed, failures = evaluator.evaluate(checks)
        assert passed is False
        assert len(failures) >= 7  # All required checks fail

    def test_evaluate_all_pass(self):
        release = Release(version="1.0.0")
        checks = build_checklist(release)
        evaluator = ChecklistEvaluator()
        for c in checks:
            c.status = CheckStatus.PASS
        passed, failures = evaluator.evaluate(checks)
        assert passed is True
        assert failures == []

    def test_evaluate_na_counts_as_pass(self):
        release = Release(version="1.0.0")
        checks = build_checklist(release)
        evaluator = ChecklistEvaluator()
        for c in checks:
            c.status = CheckStatus.NA
        passed, _failures = evaluator.evaluate(checks)
        assert passed is True

    def test_update_check(self):
        release = Release(version="1.0.0")
        checks = build_checklist(release)
        evaluator = ChecklistEvaluator()
        result = evaluator.update_check(checks, "RL-01", CheckStatus.PASS, "All PRs merged")
        assert result is not None
        assert result.status == CheckStatus.PASS
        assert result.message == "All PRs merged"

    def test_update_check_not_found(self):
        evaluator = ChecklistEvaluator()
        result = evaluator.update_check([], "RL-99", CheckStatus.PASS)
        assert result is None


# ===================================================================
# Sync Engine
# ===================================================================


class TestSyncEngine:
    """Test sync engine with dry-run and execution."""

    def _engine_with_rule(self) -> tuple[SyncEngine, SyncRule]:
        engine = SyncEngine()
        rule = SyncRule(
            source_pattern="core/**/*.md",
            target_repo="org/webapp",
            target_path="docs/agent33",
            include_patterns=["core/orchestrator/*.md"],
            exclude_patterns=["core/orchestrator/distribution/**"],
        )
        engine.add_rule(rule)
        return engine, rule

    def test_add_and_list_rules(self):
        engine = SyncEngine()
        rule = SyncRule(target_repo="org/repo")
        engine.add_rule(rule)
        assert len(engine.list_rules()) == 1

    def test_remove_rule(self):
        engine = SyncEngine()
        rule = SyncRule()
        engine.add_rule(rule)
        assert engine.remove_rule(rule.rule_id) is True
        assert len(engine.list_rules()) == 0

    def test_remove_nonexistent_rule(self):
        engine = SyncEngine()
        assert engine.remove_rule("nonexistent") is False

    def test_match_files(self):
        engine, rule = self._engine_with_rule()
        files = [
            "core/orchestrator/RELEASE.md",
            "core/orchestrator/REVIEW.md",
            "core/orchestrator/distribution/sync.md",
            "core/arch/design.md",
            "README.md",
        ]
        matched = engine.match_files(rule, files)
        assert "core/orchestrator/RELEASE.md" in matched
        assert "core/orchestrator/REVIEW.md" in matched
        # Excluded by distribution pattern
        assert "core/orchestrator/distribution/sync.md" not in matched
        # Not in include patterns
        assert "core/arch/design.md" not in matched
        # Not matching source pattern
        assert "README.md" not in matched

    def test_dry_run(self):
        engine, rule = self._engine_with_rule()
        files = ["core/orchestrator/RELEASE.md", "core/orchestrator/REVIEW.md"]
        exe = engine.dry_run(rule.rule_id, files, release_version="1.0.0")
        assert exe.status == SyncStatus.DRY_RUN
        assert exe.dry_run is True
        assert exe.files_added == 2
        assert len(exe.file_results) == 2

    def test_dry_run_missing_rule(self):
        engine = SyncEngine()
        exe = engine.dry_run("nonexistent", [])
        assert exe.status == SyncStatus.FAILED
        assert len(exe.errors) == 1

    def test_execute(self):
        engine, rule = self._engine_with_rule()
        files = ["core/orchestrator/RELEASE.md"]
        exe = engine.execute(rule.rule_id, files, release_version="1.0.0")
        assert exe.status == SyncStatus.COMPLETED
        assert exe.dry_run is False
        assert exe.files_added == 1
        assert exe.completed_at is not None

    def test_execute_missing_rule(self):
        engine = SyncEngine()
        exe = engine.execute("nonexistent", [])
        assert exe.status == SyncStatus.FAILED

    def test_list_executions(self):
        engine, rule = self._engine_with_rule()
        engine.dry_run(rule.rule_id, ["core/orchestrator/A.md"])
        engine.execute(rule.rule_id, ["core/orchestrator/B.md"])
        exes = engine.list_executions()
        assert len(exes) == 2

    def test_list_executions_by_rule(self):
        engine, rule = self._engine_with_rule()
        engine.dry_run(rule.rule_id, [])
        other = SyncRule()
        engine.add_rule(other)
        engine.dry_run(other.rule_id, [])
        assert len(engine.list_executions(rule_id=rule.rule_id)) == 1

    def test_compute_checksum(self):
        checksum = SyncEngine.compute_checksum("hello")
        assert len(checksum) == 64  # SHA-256 hex

    def test_validate_execution(self):
        engine, rule = self._engine_with_rule()
        exe = engine.dry_run(rule.rule_id, ["core/orchestrator/A.md"])
        issues = engine.validate_execution(exe.execution_id)
        assert issues == []

    def test_validate_nonexistent_execution(self):
        engine = SyncEngine()
        issues = engine.validate_execution("nonexistent")
        assert len(issues) == 1


# ===================================================================
# Rollback Manager
# ===================================================================


class TestRollbackManager:
    """Test rollback tracking and decision matrix."""

    def test_recommend_critical_high(self):
        mgr = RollbackManager()
        rb_type, approval = mgr.recommend("critical", "high")
        assert rb_type == RollbackType.IMMEDIATE
        assert approval == "on-call"

    def test_recommend_low_low(self):
        mgr = RollbackManager()
        rb_type, approval = mgr.recommend("low", "low")
        assert rb_type == RollbackType.CONFIG
        assert approval == "engineer"

    def test_recommend_unknown_defaults(self):
        mgr = RollbackManager()
        rb_type, approval = mgr.recommend("unknown", "unknown")
        assert rb_type == RollbackType.PLANNED
        assert approval == "team-lead"

    def test_create_rollback(self):
        mgr = RollbackManager()
        record = mgr.create(
            release_id="REL-test",
            reason="Critical bug",
            rollback_type=RollbackType.IMMEDIATE,
            initiated_by="admin",
        )
        assert record.release_id == "REL-test"
        assert record.status == RollbackStatus.PENDING

    def test_approve_rollback(self):
        mgr = RollbackManager()
        record = mgr.create(release_id="REL-test", reason="bug")
        result = mgr.approve(record.rollback_id, approved_by="lead")
        assert result is not None
        assert result.status == RollbackStatus.IN_PROGRESS
        assert result.approved_by == "lead"

    def test_complete_step(self):
        mgr = RollbackManager()
        record = mgr.create(release_id="REL-test", reason="bug")
        mgr.approve(record.rollback_id, "lead")
        mgr.complete_step(record.rollback_id, "Reverted deployment")
        assert len(record.steps_completed) == 1

    def test_complete_rollback(self):
        mgr = RollbackManager()
        record = mgr.create(release_id="REL-test", reason="bug")
        mgr.approve(record.rollback_id, "lead")
        result = mgr.complete(record.rollback_id)
        assert result is not None
        assert result.status == RollbackStatus.COMPLETED
        assert result.completed_at is not None

    def test_fail_rollback(self):
        mgr = RollbackManager()
        record = mgr.create(release_id="REL-test", reason="bug")
        result = mgr.fail(record.rollback_id, "Network error")
        assert result is not None
        assert result.status == RollbackStatus.FAILED
        assert "Network error" in result.errors

    def test_list_rollbacks_by_release(self):
        mgr = RollbackManager()
        mgr.create(release_id="REL-1", reason="bug1")
        mgr.create(release_id="REL-2", reason="bug2")
        assert len(mgr.list_all(release_id="REL-1")) == 1

    def test_list_rollbacks_by_status(self):
        mgr = RollbackManager()
        r1 = mgr.create(release_id="REL-1", reason="bug1")
        mgr.create(release_id="REL-2", reason="bug2")
        mgr.approve(r1.rollback_id, "lead")
        assert len(mgr.list_all(status=RollbackStatus.IN_PROGRESS)) == 1
        assert len(mgr.list_all(status=RollbackStatus.PENDING)) == 1


# ===================================================================
# Release Service
# ===================================================================


class TestReleaseService:
    """Test release service lifecycle."""

    def test_create_release(self):
        svc = ReleaseService()
        release = svc.create_release(version="1.0.0", description="Initial release")
        assert release.status == ReleaseStatus.PLANNED
        assert len(release.evidence.checklist) == 8

    def test_get_release(self):
        svc = ReleaseService()
        created = svc.create_release(version="1.0.0")
        fetched = svc.get_release(created.release_id)
        assert fetched.version == "1.0.0"

    def test_get_release_not_found(self):
        svc = ReleaseService()
        with pytest.raises(ReleaseNotFoundError):
            svc.get_release("nonexistent")

    def test_list_releases(self):
        svc = ReleaseService()
        svc.create_release(version="1.0.0")
        svc.create_release(version="1.1.0")
        assert len(svc.list_releases()) == 2

    def test_list_releases_filter_by_status(self):
        svc = ReleaseService()
        svc.create_release(version="1.0.0")
        svc.create_release(version="1.1.0")
        assert len(svc.list_releases(status=ReleaseStatus.PLANNED)) == 2
        assert len(svc.list_releases(status=ReleaseStatus.RELEASED)) == 0

    def test_lifecycle_planned_to_released(self):
        svc = ReleaseService()
        release = svc.create_release(version="1.0.0")
        rid = release.release_id

        # PLANNED -> FROZEN
        svc.freeze(rid)
        assert svc.get_release(rid).status == ReleaseStatus.FROZEN

        # FROZEN -> RC
        svc.cut_rc(rid, rc_version="1.0.0-rc.1")
        r = svc.get_release(rid)
        assert r.status == ReleaseStatus.RC
        assert r.rc_version == "1.0.0-rc.1"

        # RC -> VALIDATING
        svc.start_validation(rid)
        assert svc.get_release(rid).status == ReleaseStatus.VALIDATING

        # Pass all checklist items
        for check in svc.get_release(rid).evidence.checklist:
            svc.update_check(rid, check.check_id, CheckStatus.PASS)

        # VALIDATING -> RELEASED
        svc.publish(rid, released_by="admin")
        r = svc.get_release(rid)
        assert r.status == ReleaseStatus.RELEASED
        assert r.released_by == "admin"
        assert r.released_at is not None

    def test_publish_fails_without_checklist(self):
        svc = ReleaseService()
        release = svc.create_release(version="1.0.0")
        rid = release.release_id
        svc.freeze(rid)
        svc.cut_rc(rid)
        svc.start_validation(rid)
        # Don't pass checklist items
        with pytest.raises(InvalidReleaseTransitionError):
            svc.publish(rid)

    def test_invalid_transition_raises(self):
        svc = ReleaseService()
        release = svc.create_release(version="1.0.0")
        with pytest.raises(InvalidReleaseTransitionError):
            svc.transition(release.release_id, ReleaseStatus.RELEASED)

    def test_update_check(self):
        svc = ReleaseService()
        release = svc.create_release(version="1.0.0")
        svc.update_check(release.release_id, "RL-01", CheckStatus.PASS)
        r = svc.get_release(release.release_id)
        rl01 = next(c for c in r.evidence.checklist if c.check_id == "RL-01")
        assert rl01.status == CheckStatus.PASS

    def test_evaluate_checklist(self):
        svc = ReleaseService()
        release = svc.create_release(version="1.0.0")
        passed, failures = svc.evaluate_checklist(release.release_id)
        assert passed is False
        assert len(failures) >= 7

    def test_apply_component_security_gate_pass(self):
        svc = ReleaseService()
        release = svc.create_release(version="1.0.0")
        result = svc.apply_component_security_gate(
            release.release_id,
            run_id="secrun-pass",
            summary=FindingsSummary(critical=0, high=0, medium=1, low=1, info=0),
            policy=SecurityGatePolicy(max_medium=5),
        )
        assert result.decision.value == "pass"
        rl06 = next(c for c in release.evidence.checklist if c.check_id == "RL-06")
        assert rl06.status == CheckStatus.PASS
        assert release.evidence.gate_passed is True

    def test_apply_component_security_gate_fail(self):
        svc = ReleaseService()
        release = svc.create_release(version="1.0.0")
        result = svc.apply_component_security_gate(
            release.release_id,
            run_id="secrun-fail",
            summary=FindingsSummary(critical=0, high=2, medium=0, low=0, info=0),
            policy=SecurityGatePolicy(max_high=0),
        )
        assert result.decision.value == "fail"
        rl06 = next(c for c in release.evidence.checklist if c.check_id == "RL-06")
        assert rl06.status == CheckStatus.FAIL
        assert release.evidence.gate_passed is False

    def test_add_sync_rule(self):
        svc = ReleaseService()
        rule = SyncRule(target_repo="org/repo")
        svc.add_sync_rule(rule)
        assert len(svc.list_sync_rules()) == 1

    def test_initiate_rollback(self):
        svc = ReleaseService()
        release = svc.create_release(version="1.0.0")
        rid = release.release_id
        # Go through full lifecycle to RELEASED
        svc.freeze(rid)
        svc.cut_rc(rid)
        svc.start_validation(rid)
        for check in svc.get_release(rid).evidence.checklist:
            svc.update_check(rid, check.check_id, CheckStatus.PASS)
        svc.publish(rid)

        # Now rollback
        result = svc.initiate_rollback(rid, reason="Critical bug", initiated_by="admin")
        assert result.status == ReleaseStatus.ROLLED_BACK
        rollbacks = svc.rollback_manager.list_all(release_id=rid)
        assert len(rollbacks) == 1


# ===================================================================
# API Endpoints
# ===================================================================


class TestReleaseAPI:
    """Test REST API endpoints for releases."""

    @pytest.fixture()
    def client(self, auth_token: str) -> TestClient:
        from starlette.testclient import TestClient

        from agent33.api.routes.releases import _service
        from agent33.main import app

        # Reset service state
        _service._releases.clear()
        _service._sync._rules.clear()
        _service._sync._executions.clear()
        _service._rollback._records.clear()

        return TestClient(app, headers={"Authorization": f"Bearer {auth_token}"})

    def test_create_release(self, client: TestClient):
        resp = client.post(
            "/v1/releases",
            json={"version": "1.0.0", "description": "Test release"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["version"] == "1.0.0"
        assert data["status"] == "planned"
        assert data["checklist_items"] == 8

    def test_list_releases(self, client: TestClient):
        client.post("/v1/releases", json={"version": "1.0.0"})
        client.post("/v1/releases", json={"version": "1.1.0"})
        resp = client.get("/v1/releases")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_release(self, client: TestClient):
        create_resp = client.post("/v1/releases", json={"version": "1.0.0"})
        rid = create_resp.json()["release_id"]
        resp = client.get(f"/v1/releases/{rid}")
        assert resp.status_code == 200
        assert resp.json()["version"] == "1.0.0"

    def test_get_release_not_found(self, client: TestClient):
        resp = client.get("/v1/releases/nonexistent")
        assert resp.status_code == 404

    def test_freeze_release(self, client: TestClient):
        create_resp = client.post("/v1/releases", json={"version": "1.0.0"})
        rid = create_resp.json()["release_id"]
        resp = client.post(f"/v1/releases/{rid}/freeze")
        assert resp.status_code == 200
        assert resp.json()["status"] == "frozen"

    def test_cut_rc(self, client: TestClient):
        create_resp = client.post("/v1/releases", json={"version": "1.0.0"})
        rid = create_resp.json()["release_id"]
        client.post(f"/v1/releases/{rid}/freeze")
        resp = client.post(
            f"/v1/releases/{rid}/rc",
            json={"rc_version": "1.0.0-rc.1"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rc"

    def test_validate_and_publish(self, client: TestClient):
        # Create -> Freeze -> RC -> Validate
        create_resp = client.post("/v1/releases", json={"version": "1.0.0"})
        rid = create_resp.json()["release_id"]
        client.post(f"/v1/releases/{rid}/freeze")
        client.post(f"/v1/releases/{rid}/rc", json={})
        client.post(f"/v1/releases/{rid}/validate")

        # Pass all checklist items
        for i in range(1, 9):
            check_id = f"RL-0{i}"
            client.patch(
                f"/v1/releases/{rid}/checklist",
                json={"check_id": check_id, "status": "pass"},
            )

        # Publish
        resp = client.post(
            f"/v1/releases/{rid}/publish",
            json={"released_by": "admin"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "released"

    def test_publish_fails_without_checks(self, client: TestClient):
        create_resp = client.post("/v1/releases", json={"version": "1.0.0"})
        rid = create_resp.json()["release_id"]
        client.post(f"/v1/releases/{rid}/freeze")
        client.post(f"/v1/releases/{rid}/rc", json={})
        client.post(f"/v1/releases/{rid}/validate")
        resp = client.post(f"/v1/releases/{rid}/publish", json={})
        assert resp.status_code == 409

    def test_invalid_transition_returns_409(self, client: TestClient):
        create_resp = client.post("/v1/releases", json={"version": "1.0.0"})
        rid = create_resp.json()["release_id"]
        # Can't go directly to RC from PLANNED
        resp = client.post(f"/v1/releases/{rid}/rc", json={})
        assert resp.status_code == 409

    def test_checklist_get(self, client: TestClient):
        create_resp = client.post("/v1/releases", json={"version": "1.0.0"})
        rid = create_resp.json()["release_id"]
        resp = client.get(f"/v1/releases/{rid}/checklist")
        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is False
        assert len(data["checks"]) == 8

    def test_checklist_update(self, client: TestClient):
        create_resp = client.post("/v1/releases", json={"version": "1.0.0"})
        rid = create_resp.json()["release_id"]
        resp = client.patch(
            f"/v1/releases/{rid}/checklist",
            json={
                "check_id": "RL-01",
                "status": "pass",
                "message": "All merged",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pass"

    def test_apply_security_gate_endpoint(self, client: TestClient):
        create_resp = client.post("/v1/releases", json={"version": "1.0.0"})
        rid = create_resp.json()["release_id"]
        resp = client.post(
            f"/v1/releases/{rid}/security-gate",
            json={
                "run_id": "secrun-123",
                "summary": {
                    "critical": 0,
                    "high": 0,
                    "medium": 0,
                    "low": 1,
                    "info": 0,
                },
            },
        )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "pass"

        checklist_resp = client.get(f"/v1/releases/{rid}/checklist")
        checks = checklist_resp.json()["checks"]
        rl06 = next(check for check in checks if check["check_id"] == "RL-06")
        assert rl06["status"] == "pass"

    def test_sync_rule_crud(self, client: TestClient):
        resp = client.post(
            "/v1/releases/sync/rules",
            json={
                "target_repo": "org/webapp",
                "target_path": "docs/",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["target_repo"] == "org/webapp"

        list_resp = client.get("/v1/releases/sync/rules")
        assert len(list_resp.json()) == 1

    def test_sync_dry_run(self, client: TestClient):
        # Create rule
        rule_resp = client.post(
            "/v1/releases/sync/rules",
            json={
                "source_pattern": "core/**/*.md",
                "target_repo": "org/webapp",
                "target_path": "docs/",
            },
        )
        rule_id = rule_resp.json()["rule_id"]

        # Dry run
        resp = client.post(
            f"/v1/releases/sync/rules/{rule_id}/dry-run",
            json={
                "available_files": [
                    "core/orchestrator/RELEASE.md",
                    "core/orchestrator/REVIEW.md",
                ],
                "release_version": "1.0.0",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["files_added"] == 2

    def test_sync_execute(self, client: TestClient):
        rule_resp = client.post(
            "/v1/releases/sync/rules",
            json={
                "source_pattern": "core/**/*.md",
                "target_repo": "org/webapp",
            },
        )
        rule_id = rule_resp.json()["rule_id"]

        resp = client.post(
            f"/v1/releases/sync/rules/{rule_id}/execute",
            json={
                "available_files": ["core/orchestrator/A.md"],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["dry_run"] is False
        assert resp.json()["status"] == "completed"

    def test_rollback_lifecycle(self, client: TestClient):
        # Create and publish a release
        create_resp = client.post("/v1/releases", json={"version": "1.0.0"})
        rid = create_resp.json()["release_id"]
        client.post(f"/v1/releases/{rid}/freeze")
        client.post(f"/v1/releases/{rid}/rc", json={})
        client.post(f"/v1/releases/{rid}/validate")
        for i in range(1, 9):
            client.patch(
                f"/v1/releases/{rid}/checklist",
                json={"check_id": f"RL-0{i}", "status": "pass"},
            )
        client.post(f"/v1/releases/{rid}/publish", json={})

        # Initiate rollback
        rb_resp = client.post(
            f"/v1/releases/{rid}/rollback",
            json={"reason": "Critical bug", "initiated_by": "admin"},
        )
        assert rb_resp.status_code == 201
        assert rb_resp.json()["status"] == "rolled_back"

        # List rollbacks
        list_resp = client.get("/v1/releases/rollbacks")
        assert len(list_resp.json()) >= 1

    def test_rollback_recommend(self, client: TestClient):
        resp = client.post(
            "/v1/releases/rollback/recommend",
            json={"severity": "critical", "impact": "high"},
        )
        assert resp.status_code == 200
        assert resp.json()["rollback_type"] == "immediate"
        assert resp.json()["approval_level"] == "on-call"
