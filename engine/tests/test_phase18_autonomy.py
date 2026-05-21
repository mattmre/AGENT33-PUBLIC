"""Phase 18 — Autonomy Budget Enforcement & Policy Automation.

Tests cover:
- Budget models (enums, defaults, ID generation)
- Preflight checker (PF-01..PF-10)
- Runtime enforcer (EF-01..EF-08, stop conditions, escalation)
- Autonomy service (CRUD, lifecycle, preflight, enforcement, escalations)
- API endpoints (REST lifecycle)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from starlette.testclient import TestClient

from agent33.autonomy.enforcement import RuntimeEnforcer
from agent33.autonomy.models import (
    AutonomyBudget,
    BudgetState,
    CommandPermission,
    EnforcementContext,
    EnforcementResult,
    EscalationRecord,
    EscalationTrigger,
    EscalationUrgency,
    FileScope,
    NetworkScope,
    PolicyAction,
    PreflightStatus,
    ResourceLimits,
    StopAction,
    StopCondition,
)
from agent33.autonomy.preflight import PreflightChecker
from agent33.autonomy.service import (
    AutonomyService,
    BudgetNotFoundError,
    InvalidStateTransitionError,
)

# ===================================================================
# Budget Models
# ===================================================================


class TestBudgetModels:
    """Test autonomy budget data models."""

    def test_budget_default_state_is_draft(self):
        budget = AutonomyBudget()
        assert budget.state == BudgetState.DRAFT

    def test_budget_id_has_prefix(self):
        budget = AutonomyBudget()
        assert budget.budget_id.startswith("BDG-")
        assert len(budget.budget_id) == 16  # "BDG-" + 12 hex chars

    def test_budget_unique_ids(self):
        b1 = AutonomyBudget()
        b2 = AutonomyBudget()
        assert b1.budget_id != b2.budget_id

    def test_file_scope_defaults(self):
        scope = FileScope()
        assert scope.read == []
        assert scope.write == []
        assert scope.deny == []

    def test_network_scope_defaults(self):
        net = NetworkScope()
        assert net.enabled is False
        assert net.allowed_domains == []
        assert net.denied_domains == []
        assert net.max_requests == 0

    def test_resource_limits_defaults(self):
        limits = ResourceLimits()
        assert limits.max_iterations == 100
        assert limits.max_duration_minutes == 60
        assert limits.max_files_modified == 50
        assert limits.max_lines_changed == 5000
        assert limits.max_tool_calls == 200

    def test_enforcement_context_tracking(self):
        ctx = EnforcementContext(budget_id="test")
        ctx.record_iteration()
        ctx.record_iteration()
        ctx.record_tool_call()
        ctx.record_file_modified(lines=10)
        ctx.record_network_request()
        assert ctx.iterations == 2
        assert ctx.tool_calls == 1
        assert ctx.files_modified == 1
        assert ctx.lines_changed == 10
        assert ctx.network_requests == 1

    def test_enforcement_context_warnings_violations(self):
        ctx = EnforcementContext(budget_id="test")
        ctx.add_warning("warn1")
        ctx.add_violation("viol1")
        assert ctx.warnings == ["warn1"]
        assert ctx.violations == ["viol1"]
        assert ctx.stopped is False

    def test_enforcement_context_mark_stopped(self):
        ctx = EnforcementContext(budget_id="test")
        ctx.mark_stopped("test reason")
        assert ctx.stopped is True
        assert ctx.stop_reason == "test reason"

    def test_escalation_record_id_prefix(self):
        record = EscalationRecord(budget_id="test")
        assert record.escalation_id.startswith("ESC-")

    def test_all_enums_have_values(self):
        assert len(BudgetState) == 7
        assert len(StopAction) == 3
        assert len(EscalationUrgency) == 3
        assert len(PolicyAction) == 5
        assert len(EnforcementResult) == 4
        assert len(PreflightStatus) == 3


# ===================================================================
# Preflight Checker
# ===================================================================


class TestPreflightChecker:
    """Test preflight checks PF-01..PF-10."""

    def _active_budget(self, **kwargs) -> AutonomyBudget:
        """Create an active budget with sensible defaults for preflight."""
        defaults = {
            "state": BudgetState.ACTIVE,
            "in_scope": ["test task"],
            "files": FileScope(read=["src/**"]),
            "allowed_commands": [CommandPermission(command="pytest")],
            "limits": ResourceLimits(max_iterations=10, max_duration_minutes=5),
            "stop_conditions": [StopCondition(description="Max iterations")],
            "escalation_triggers": [EscalationTrigger(description="Failure threshold")],
            "default_escalation_target": "orchestrator",
        }
        defaults.update(kwargs)
        return AutonomyBudget(**defaults)

    def test_pf01_budget_exists_pass(self):
        checker = PreflightChecker()
        budget = self._active_budget()
        report = checker.check(budget)
        pf01 = next(c for c in report.checks if c.check_id == "PF-01")
        assert pf01.status == PreflightStatus.PASS

    def test_pf02_budget_must_be_active(self):
        checker = PreflightChecker()
        budget = self._active_budget(state=BudgetState.DRAFT)
        report = checker.check(budget)
        pf02 = next(c for c in report.checks if c.check_id == "PF-02")
        assert pf02.status == PreflightStatus.FAIL
        assert "draft" in pf02.message.lower()

    def test_pf03_budget_not_expired(self):
        checker = PreflightChecker()
        budget = self._active_budget(expires_at=datetime.now(UTC) - timedelta(hours=1))
        report = checker.check(budget)
        pf03 = next(c for c in report.checks if c.check_id == "PF-03")
        assert pf03.status == PreflightStatus.FAIL

    def test_pf03_non_expired_passes(self):
        checker = PreflightChecker()
        budget = self._active_budget(expires_at=datetime.now(UTC) + timedelta(hours=1))
        report = checker.check(budget)
        pf03 = next(c for c in report.checks if c.check_id == "PF-03")
        assert pf03.status == PreflightStatus.PASS

    def test_pf04_scope_required(self):
        checker = PreflightChecker()
        budget = self._active_budget(in_scope=[])
        report = checker.check(budget)
        pf04 = next(c for c in report.checks if c.check_id == "PF-04")
        assert pf04.status == PreflightStatus.FAIL

    def test_pf05_files_warn_when_empty(self):
        checker = PreflightChecker()
        budget = self._active_budget(files=FileScope())
        report = checker.check(budget)
        pf05 = next(c for c in report.checks if c.check_id == "PF-05")
        assert pf05.status == PreflightStatus.WARN

    def test_pf06_commands_warn_when_empty(self):
        checker = PreflightChecker()
        budget = self._active_budget(allowed_commands=[])
        report = checker.check(budget)
        pf06 = next(c for c in report.checks if c.check_id == "PF-06")
        assert pf06.status == PreflightStatus.WARN

    def test_pf07_network_warn_when_open(self):
        checker = PreflightChecker()
        budget = self._active_budget(network=NetworkScope(enabled=True, allowed_domains=[]))
        report = checker.check(budget)
        pf07 = next(c for c in report.checks if c.check_id == "PF-07")
        assert pf07.status == PreflightStatus.WARN

    def test_pf07_network_pass_when_disabled(self):
        checker = PreflightChecker()
        budget = self._active_budget(network=NetworkScope(enabled=False))
        report = checker.check(budget)
        pf07 = next(c for c in report.checks if c.check_id == "PF-07")
        assert pf07.status == PreflightStatus.PASS

    def test_pf08_limits_warn_when_zero(self):
        checker = PreflightChecker()
        budget = self._active_budget(
            limits=ResourceLimits(max_iterations=0, max_duration_minutes=0)
        )
        report = checker.check(budget)
        pf08 = next(c for c in report.checks if c.check_id == "PF-08")
        assert pf08.status == PreflightStatus.WARN

    def test_pf09_stop_conditions_warn_when_empty(self):
        checker = PreflightChecker()
        budget = self._active_budget(stop_conditions=[])
        report = checker.check(budget)
        pf09 = next(c for c in report.checks if c.check_id == "PF-09")
        assert pf09.status == PreflightStatus.WARN

    def test_pf10_escalation_warn_when_no_path(self):
        checker = PreflightChecker()
        budget = self._active_budget(escalation_triggers=[], default_escalation_target="")
        report = checker.check(budget)
        pf10 = next(c for c in report.checks if c.check_id == "PF-10")
        assert pf10.status == PreflightStatus.WARN

    def test_all_pass_overall_pass(self):
        checker = PreflightChecker()
        budget = self._active_budget()
        report = checker.check(budget)
        assert report.overall == PreflightStatus.PASS
        assert len(report.checks) == 10

    def test_any_fail_overall_fail(self):
        checker = PreflightChecker()
        budget = self._active_budget(state=BudgetState.DRAFT)
        report = checker.check(budget)
        assert report.overall == PreflightStatus.FAIL

    def test_warn_only_overall_warn(self):
        checker = PreflightChecker()
        budget = self._active_budget(stop_conditions=[])
        report = checker.check(budget)
        assert report.overall == PreflightStatus.WARN


# ===================================================================
# Runtime Enforcer
# ===================================================================


class TestRuntimeEnforcer:
    """Test enforcement points EF-01..EF-08."""

    def _enforcer(self, **budget_kwargs) -> RuntimeEnforcer:
        defaults = {
            "state": BudgetState.ACTIVE,
            "files": FileScope(
                read=["src/**", "tests/**"],
                write=["src/**"],
                deny=["*.env", "secrets/*"],
            ),
            "allowed_commands": [
                CommandPermission(command="pytest"),
                CommandPermission(command="ruff", args_pattern=r"check.*"),
            ],
            "denied_commands": ["rm", "sudo"],
            "require_approval_commands": ["git"],
            "network": NetworkScope(
                enabled=True,
                allowed_domains=["api.example.com", "pypi.org"],
                denied_domains=["evil.com"],
                max_requests=5,
            ),
            "limits": ResourceLimits(
                max_iterations=10,
                max_duration_minutes=30,
                max_files_modified=3,
                max_lines_changed=100,
                max_tool_calls=5,
            ),
        }
        defaults.update(budget_kwargs)
        budget = AutonomyBudget(**defaults)
        return RuntimeEnforcer(budget)

    # EF-01: File read
    def test_ef01_file_read_allowed(self):
        e = self._enforcer()
        assert e.check_file_read("src/main.py") == EnforcementResult.ALLOWED

    def test_ef01_file_read_denied_by_pattern(self):
        e = self._enforcer()
        assert e.check_file_read("secrets/key.pem") == EnforcementResult.BLOCKED

    def test_ef01_file_read_denied_by_env(self):
        e = self._enforcer()
        assert e.check_file_read("config.env") == EnforcementResult.BLOCKED

    def test_ef01_file_read_not_in_allowlist(self):
        e = self._enforcer()
        assert e.check_file_read("docs/readme.md") == EnforcementResult.BLOCKED

    # EF-02: File write
    def test_ef02_file_write_allowed(self):
        e = self._enforcer()
        assert e.check_file_write("src/foo.py") == EnforcementResult.ALLOWED

    def test_ef02_file_write_denied_by_pattern(self):
        e = self._enforcer()
        assert e.check_file_write("app.env") == EnforcementResult.BLOCKED

    def test_ef02_file_write_not_in_allowlist(self):
        e = self._enforcer()
        assert e.check_file_write("tests/test.py") == EnforcementResult.BLOCKED

    def test_ef02_file_write_tracks_modified(self):
        e = self._enforcer()
        e.check_file_write("src/a.py", lines=10)
        e.check_file_write("src/b.py", lines=20)
        assert e.context.files_modified == 2
        assert e.context.lines_changed == 30

    # EF-03: Command execution
    def test_ef03_command_allowed(self):
        e = self._enforcer()
        assert e.check_command("pytest tests/") == EnforcementResult.ALLOWED

    def test_ef03_command_denied(self):
        e = self._enforcer()
        assert e.check_command("rm -rf /") == EnforcementResult.BLOCKED

    def test_ef03_command_requires_approval(self):
        e = self._enforcer()
        assert e.check_command("git push") == EnforcementResult.WARNED

    def test_ef03_command_not_in_allowlist(self):
        e = self._enforcer()
        assert e.check_command("curl http://x") == EnforcementResult.BLOCKED

    def test_ef03_command_args_pattern_match(self):
        e = self._enforcer()
        assert e.check_command("ruff check src/") == EnforcementResult.ALLOWED

    def test_ef03_command_args_pattern_no_match(self):
        e = self._enforcer()
        assert e.check_command("ruff format src/") == EnforcementResult.BLOCKED

    # EF-04: Network
    def test_ef04_network_allowed_domain(self):
        e = self._enforcer()
        assert e.check_network("api.example.com") == EnforcementResult.ALLOWED

    def test_ef04_network_denied_domain(self):
        e = self._enforcer()
        assert e.check_network("evil.com") == EnforcementResult.BLOCKED

    def test_ef04_network_subdomain_of_denied(self):
        e = self._enforcer()
        assert e.check_network("sub.evil.com") == EnforcementResult.BLOCKED

    def test_ef04_network_not_in_allowlist(self):
        e = self._enforcer()
        assert e.check_network("unknown.io") == EnforcementResult.BLOCKED

    def test_ef04_network_disabled(self):
        e = self._enforcer(network=NetworkScope(enabled=False))
        assert e.check_network("api.example.com") == EnforcementResult.BLOCKED

    def test_ef04_network_request_limit(self):
        e = self._enforcer()
        for _ in range(5):
            assert e.check_network("api.example.com") == EnforcementResult.ALLOWED
        assert e.check_network("api.example.com") == EnforcementResult.BLOCKED

    # EF-05: Iteration limit
    def test_ef05_iteration_within_limit(self):
        e = self._enforcer()
        for _ in range(10):
            assert e.record_iteration() == EnforcementResult.ALLOWED

    def test_ef05_iteration_exceeds_limit(self):
        e = self._enforcer()
        for _ in range(10):
            e.record_iteration()
        assert e.record_iteration() == EnforcementResult.BLOCKED
        assert e.context.stopped is True

    # EF-07: Files modified limit
    def test_ef07_files_modified_limit(self):
        e = self._enforcer()
        e.check_file_write("src/a.py")
        e.check_file_write("src/b.py")
        e.check_file_write("src/c.py")
        # 4th file exceeds limit of 3
        result = e.check_file_write("src/d.py")
        assert result == EnforcementResult.BLOCKED

    # EF-08: Lines changed limit
    def test_ef08_lines_changed_limit(self):
        e = self._enforcer()
        result = e.check_file_write("src/big.py", lines=101)
        assert result == EnforcementResult.BLOCKED

    # Stop conditions
    def test_stop_conditions_evaluation(self):
        e = self._enforcer(
            stop_conditions=[
                StopCondition(
                    description="Max iterations reached",
                    action=StopAction.STOP,
                ),
            ],
        )
        # Push past the iteration limit
        for _ in range(11):
            e.record_iteration()
        triggered = e.evaluate_stop_conditions()
        assert len(triggered) >= 1

    # Escalation
    def test_manual_escalation(self):
        e = self._enforcer()
        record = e.trigger_escalation("Test issue", target="admin")
        assert record.target == "admin"
        assert record.trigger_description == "Test issue"
        assert len(e.escalations) == 1

    def test_escalation_default_target(self):
        e = self._enforcer(default_escalation_target="lead")
        record = e.trigger_escalation("No target specified")
        assert record.target == "lead"


# ===================================================================
# Autonomy Service
# ===================================================================


class TestAutonomyService:
    """Test service-level CRUD, lifecycle, and orchestration."""

    def test_create_budget(self):
        svc = AutonomyService()
        budget = svc.create_budget(task_id="task-1", agent_id="agent-1")
        assert budget.state == BudgetState.DRAFT
        assert budget.task_id == "task-1"
        assert budget.agent_id == "agent-1"

    def test_get_budget(self):
        svc = AutonomyService()
        created = svc.create_budget()
        fetched = svc.get_budget(created.budget_id)
        assert fetched.budget_id == created.budget_id

    def test_get_budget_not_found(self):
        svc = AutonomyService()
        with pytest.raises(BudgetNotFoundError):
            svc.get_budget("nonexistent")

    def test_list_budgets_all(self):
        svc = AutonomyService()
        svc.create_budget(task_id="t1")
        svc.create_budget(task_id="t2")
        assert len(svc.list_budgets()) == 2

    def test_list_budgets_filter_by_state(self):
        svc = AutonomyService()
        svc.create_budget()
        svc.create_budget()
        assert len(svc.list_budgets(state=BudgetState.DRAFT)) == 2
        assert len(svc.list_budgets(state=BudgetState.ACTIVE)) == 0

    def test_list_budgets_filter_by_task(self):
        svc = AutonomyService()
        svc.create_budget(task_id="t1")
        svc.create_budget(task_id="t2")
        assert len(svc.list_budgets(task_id="t1")) == 1

    def test_list_budgets_limit(self):
        svc = AutonomyService()
        for i in range(5):
            svc.create_budget(task_id=f"t{i}")
        assert len(svc.list_budgets(limit=3)) == 3

    def test_delete_budget_draft(self):
        svc = AutonomyService()
        budget = svc.create_budget()
        svc.delete_budget(budget.budget_id)
        with pytest.raises(BudgetNotFoundError):
            svc.get_budget(budget.budget_id)

    def test_delete_budget_active_fails(self):
        svc = AutonomyService()
        budget = svc.create_budget()
        svc.activate(budget.budget_id)
        with pytest.raises(InvalidStateTransitionError):
            svc.delete_budget(budget.budget_id)

    # Lifecycle transitions
    def test_activate_from_draft(self):
        svc = AutonomyService()
        budget = svc.create_budget()
        result = svc.activate(budget.budget_id, approved_by="admin")
        assert result.state == BudgetState.ACTIVE
        assert result.approved_by == "admin"

    def test_suspend_active(self):
        svc = AutonomyService()
        budget = svc.create_budget()
        svc.activate(budget.budget_id)
        result = svc.suspend(budget.budget_id)
        assert result.state == BudgetState.SUSPENDED

    def test_complete_active(self):
        svc = AutonomyService()
        budget = svc.create_budget()
        svc.activate(budget.budget_id)
        result = svc.complete(budget.budget_id)
        assert result.state == BudgetState.COMPLETED

    def test_invalid_transition_raises(self):
        svc = AutonomyService()
        budget = svc.create_budget()
        with pytest.raises(InvalidStateTransitionError):
            svc.transition(budget.budget_id, BudgetState.COMPLETED)

    def test_transition_from_suspended_to_active(self):
        svc = AutonomyService()
        budget = svc.create_budget()
        svc.activate(budget.budget_id)
        svc.suspend(budget.budget_id)
        result = svc.transition(budget.budget_id, BudgetState.ACTIVE)
        assert result.state == BudgetState.ACTIVE

    def test_completed_is_terminal(self):
        svc = AutonomyService()
        budget = svc.create_budget()
        svc.activate(budget.budget_id)
        svc.complete(budget.budget_id)
        with pytest.raises(InvalidStateTransitionError):
            svc.transition(budget.budget_id, BudgetState.ACTIVE)

    # Preflight
    def test_run_preflight(self):
        svc = AutonomyService()
        budget = svc.create_budget(in_scope=["test"])
        svc.activate(budget.budget_id)
        report = svc.run_preflight(budget.budget_id)
        assert report.budget_id == budget.budget_id
        assert len(report.checks) == 10

    # Enforcer
    def test_create_enforcer_for_active(self):
        svc = AutonomyService()
        budget = svc.create_budget()
        svc.activate(budget.budget_id)
        enforcer = svc.create_enforcer(budget.budget_id)
        assert enforcer is not None
        assert svc.get_enforcer(budget.budget_id) is enforcer

    def test_create_enforcer_for_draft_fails(self):
        svc = AutonomyService()
        budget = svc.create_budget()
        with pytest.raises(InvalidStateTransitionError):
            svc.create_enforcer(budget.budget_id)

    def test_get_enforcer_none_when_missing(self):
        svc = AutonomyService()
        assert svc.get_enforcer("nonexistent") is None

    # Escalations
    def test_list_escalations_from_enforcer(self):
        svc = AutonomyService()
        budget = svc.create_budget()
        svc.activate(budget.budget_id)
        enforcer = svc.create_enforcer(budget.budget_id)
        enforcer.trigger_escalation("Test escalation")
        escalations = svc.list_escalations()
        assert len(escalations) == 1
        assert escalations[0].trigger_description == "Test escalation"

    def test_acknowledge_escalation(self):
        svc = AutonomyService()
        budget = svc.create_budget()
        svc.activate(budget.budget_id)
        enforcer = svc.create_enforcer(budget.budget_id)
        record = enforcer.trigger_escalation("Test")
        assert svc.acknowledge_escalation(record.escalation_id) is True

    def test_resolve_escalation(self):
        svc = AutonomyService()
        budget = svc.create_budget()
        svc.activate(budget.budget_id)
        enforcer = svc.create_enforcer(budget.budget_id)
        record = enforcer.trigger_escalation("Test")
        assert svc.resolve_escalation(record.escalation_id) is True

    def test_acknowledge_nonexistent_returns_false(self):
        svc = AutonomyService()
        assert svc.acknowledge_escalation("nonexistent") is False


# ===================================================================
# API Endpoints
# ===================================================================


class TestAutonomyAPI:
    """Test REST API endpoints for autonomy budgets."""

    @pytest.fixture()
    def client(self, auth_token: str) -> TestClient:
        from starlette.testclient import TestClient

        from agent33.api.routes.autonomy import _service
        from agent33.main import app

        # Reset service state for each test
        _service._budgets.clear()
        _service._enforcers.clear()
        _service._escalations.clear()

        return TestClient(app, headers={"Authorization": f"Bearer {auth_token}"})

    def test_create_budget(self, client: TestClient):
        resp = client.post(
            "/v1/autonomy/budgets",
            json={"task_id": "t1", "agent_id": "a1"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["state"] == "draft"
        assert data["task_id"] == "t1"
        assert data["budget_id"].startswith("BDG-")

    def test_list_budgets(self, client: TestClient):
        client.post("/v1/autonomy/budgets", json={"task_id": "t1"})
        client.post("/v1/autonomy/budgets", json={"task_id": "t2"})
        resp = client.get("/v1/autonomy/budgets")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_budget(self, client: TestClient):
        create_resp = client.post("/v1/autonomy/budgets", json={"task_id": "t1"})
        budget_id = create_resp.json()["budget_id"]
        resp = client.get(f"/v1/autonomy/budgets/{budget_id}")
        assert resp.status_code == 200
        assert resp.json()["budget_id"] == budget_id

    def test_get_budget_not_found(self, client: TestClient):
        resp = client.get("/v1/autonomy/budgets/nonexistent")
        assert resp.status_code == 404

    def test_delete_budget(self, client: TestClient):
        create_resp = client.post("/v1/autonomy/budgets", json={})
        budget_id = create_resp.json()["budget_id"]
        resp = client.delete(f"/v1/autonomy/budgets/{budget_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
        # Confirm deleted
        resp = client.get(f"/v1/autonomy/budgets/{budget_id}")
        assert resp.status_code == 404

    def test_activate_budget(self, client: TestClient):
        create_resp = client.post("/v1/autonomy/budgets", json={})
        budget_id = create_resp.json()["budget_id"]
        resp = client.post(f"/v1/autonomy/budgets/{budget_id}/activate")
        assert resp.status_code == 200
        assert resp.json()["state"] == "active"

    def test_suspend_budget(self, client: TestClient):
        create_resp = client.post("/v1/autonomy/budgets", json={})
        budget_id = create_resp.json()["budget_id"]
        client.post(f"/v1/autonomy/budgets/{budget_id}/activate")
        resp = client.post(f"/v1/autonomy/budgets/{budget_id}/suspend")
        assert resp.status_code == 200
        assert resp.json()["state"] == "suspended"

    def test_complete_budget(self, client: TestClient):
        create_resp = client.post("/v1/autonomy/budgets", json={})
        budget_id = create_resp.json()["budget_id"]
        client.post(f"/v1/autonomy/budgets/{budget_id}/activate")
        resp = client.post(f"/v1/autonomy/budgets/{budget_id}/complete")
        assert resp.status_code == 200
        assert resp.json()["state"] == "completed"

    def test_transition_invalid_returns_409(self, client: TestClient):
        create_resp = client.post("/v1/autonomy/budgets", json={})
        budget_id = create_resp.json()["budget_id"]
        resp = client.post(
            f"/v1/autonomy/budgets/{budget_id}/transition",
            json={"to_state": "completed"},
        )
        assert resp.status_code == 409

    def test_preflight_report(self, client: TestClient):
        create_resp = client.post(
            "/v1/autonomy/budgets",
            json={"in_scope": ["testing"]},
        )
        budget_id = create_resp.json()["budget_id"]
        client.post(f"/v1/autonomy/budgets/{budget_id}/activate")
        resp = client.get(f"/v1/autonomy/budgets/{budget_id}/preflight")
        assert resp.status_code == 200
        data = resp.json()
        assert data["budget_id"] == budget_id
        assert len(data["checks"]) == 10

    def test_create_enforcer(self, client: TestClient):
        create_resp = client.post("/v1/autonomy/budgets", json={})
        budget_id = create_resp.json()["budget_id"]
        client.post(f"/v1/autonomy/budgets/{budget_id}/activate")
        resp = client.post(f"/v1/autonomy/budgets/{budget_id}/enforcer")
        assert resp.status_code == 201
        assert resp.json()["status"] == "enforcer_created"

    def test_enforce_file_read(self, client: TestClient):
        create_resp = client.post("/v1/autonomy/budgets", json={})
        budget_id = create_resp.json()["budget_id"]
        client.post(f"/v1/autonomy/budgets/{budget_id}/activate")
        client.post(f"/v1/autonomy/budgets/{budget_id}/enforcer")
        resp = client.post(
            f"/v1/autonomy/budgets/{budget_id}/enforce/file",
            json={"path": "test.py", "mode": "read"},
        )
        assert resp.status_code == 200
        assert resp.json()["result"] in ("allowed", "blocked")

    def test_enforce_command(self, client: TestClient):
        create_resp = client.post("/v1/autonomy/budgets", json={})
        budget_id = create_resp.json()["budget_id"]
        client.post(f"/v1/autonomy/budgets/{budget_id}/activate")
        client.post(f"/v1/autonomy/budgets/{budget_id}/enforcer")
        resp = client.post(
            f"/v1/autonomy/budgets/{budget_id}/enforce/command",
            json={"command": "echo hello"},
        )
        assert resp.status_code == 200
        assert resp.json()["result"] in ("allowed", "blocked")

    def test_enforce_network(self, client: TestClient):
        create_resp = client.post("/v1/autonomy/budgets", json={})
        budget_id = create_resp.json()["budget_id"]
        client.post(f"/v1/autonomy/budgets/{budget_id}/activate")
        client.post(f"/v1/autonomy/budgets/{budget_id}/enforcer")
        resp = client.post(
            f"/v1/autonomy/budgets/{budget_id}/enforce/network",
            json={"domain": "example.com"},
        )
        assert resp.status_code == 200
        # Network disabled by default, so blocked
        assert resp.json()["result"] == "blocked"

    def test_enforce_no_enforcer_returns_404(self, client: TestClient):
        create_resp = client.post("/v1/autonomy/budgets", json={})
        budget_id = create_resp.json()["budget_id"]
        resp = client.post(
            f"/v1/autonomy/budgets/{budget_id}/enforce/file",
            json={"path": "test.py"},
        )
        assert resp.status_code == 404

    def test_escalation_lifecycle(self, client: TestClient):
        # Create budget → activate → enforcer → escalate → ack → resolve
        create_resp = client.post("/v1/autonomy/budgets", json={})
        budget_id = create_resp.json()["budget_id"]
        client.post(f"/v1/autonomy/budgets/{budget_id}/activate")
        client.post(f"/v1/autonomy/budgets/{budget_id}/enforcer")

        # Trigger escalation
        esc_resp = client.post(
            f"/v1/autonomy/budgets/{budget_id}/escalate",
            json={"description": "Test issue", "target": "admin"},
        )
        assert esc_resp.status_code == 201
        esc_id = esc_resp.json()["escalation_id"]

        # List escalations
        list_resp = client.get("/v1/autonomy/escalations")
        assert list_resp.status_code == 200
        assert len(list_resp.json()) >= 1

        # Acknowledge
        ack_resp = client.post(f"/v1/autonomy/escalations/{esc_id}/acknowledge")
        assert ack_resp.status_code == 200
        assert ack_resp.json()["acknowledged"] is True

        # Resolve
        resolve_resp = client.post(f"/v1/autonomy/escalations/{esc_id}/resolve")
        assert resolve_resp.status_code == 200
        assert resolve_resp.json()["resolved"] is True

    def test_escalation_not_found(self, client: TestClient):
        resp = client.post("/v1/autonomy/escalations/nonexistent/acknowledge")
        assert resp.status_code == 404

    def test_delete_active_budget_returns_409(self, client: TestClient):
        create_resp = client.post("/v1/autonomy/budgets", json={})
        budget_id = create_resp.json()["budget_id"]
        client.post(f"/v1/autonomy/budgets/{budget_id}/activate")
        resp = client.delete(f"/v1/autonomy/budgets/{budget_id}")
        assert resp.status_code == 409
