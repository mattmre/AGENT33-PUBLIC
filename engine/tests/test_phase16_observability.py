"""Phase 16 tests: observability, trace pipeline, failure taxonomy, retention.

Covers:
1. Trace models and defaults
2. Failure taxonomy models and classification
3. Trace collector service (lifecycle, steps, actions, failures)
4. Artifact retention policies
5. Trace API routes (start, get, actions, complete, failures)
6. Error paths (not-found, invalid filters)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent33.main import app
from agent33.observability.failure import (
    FailureCategory,
    FailureRecord,
    FailureSeverity,
    escalate_after,
    is_retryable,
)
from agent33.observability.retention import (
    ArtifactType,
    get_retention_policy,
    get_storage_path,
    is_permanent,
)
from agent33.observability.trace_collector import (
    TraceCollector,
    TraceNotFoundError,
)
from agent33.observability.trace_models import (
    ActionStatus,
    TraceAction,
    TraceRecord,
    TraceStatus,
    TraceStep,
)
from agent33.security.auth import create_access_token

# ===================================================================
# 1. Trace models
# ===================================================================


class TestTraceModels:
    """Test TraceRecord defaults and structure."""

    def test_new_trace_defaults(self):
        trace = TraceRecord(task_id="T-001")
        assert trace.trace_id.startswith("TRC-")
        assert trace.outcome.status == TraceStatus.RUNNING
        assert trace.duration_ms == 0
        assert trace.completed_at is None
        assert trace.execution == []

    def test_trace_ids_are_unique(self):
        t1 = TraceRecord(task_id="T-001")
        t2 = TraceRecord(task_id="T-002")
        assert t1.trace_id != t2.trace_id

    def test_trace_complete(self):
        trace = TraceRecord(task_id="T-001")
        trace.complete(TraceStatus.COMPLETED)
        assert trace.outcome.status == TraceStatus.COMPLETED
        assert trace.completed_at is not None
        assert trace.duration_ms >= 0

    def test_trace_complete_with_failure(self):
        trace = TraceRecord(task_id="T-001")
        trace.complete(
            TraceStatus.FAILED,
            failure_code="F-EXE",
            failure_message="Runtime error",
        )
        assert trace.outcome.status == TraceStatus.FAILED
        assert trace.outcome.failure_code == "F-EXE"
        assert trace.outcome.failure_message == "Runtime error"

    def test_trace_step_model(self):
        step = TraceStep(step_id="STP-001")
        assert step.step_id == "STP-001"
        assert step.actions == []

    def test_trace_action_model(self):
        action = TraceAction(
            action_id="ACT-001",
            tool="shell",
            input="ls -la",
            output="total 42",
            exit_code=0,
            duration_ms=150,
            status=ActionStatus.SUCCESS,
        )
        assert action.tool == "shell"
        assert action.exit_code == 0
        assert action.status == ActionStatus.SUCCESS


# ===================================================================
# 2. Failure taxonomy
# ===================================================================


class TestFailureTaxonomy:
    """Test failure models and classification helpers."""

    def test_failure_record_defaults(self):
        failure = FailureRecord(trace_id="TRC-001", message="Something broke")
        assert failure.failure_id.startswith("FLR-")
        assert failure.classification.category == FailureCategory.UNKNOWN
        assert failure.classification.severity == FailureSeverity.MEDIUM

    def test_from_exception(self):
        try:
            raise ValueError("test error")
        except ValueError as exc:
            failure = FailureRecord.from_exception(
                exc,
                trace_id="TRC-X",
                category=FailureCategory.INPUT,
                severity=FailureSeverity.HIGH,
            )
        assert failure.message == "test error"
        assert failure.classification.category == FailureCategory.INPUT
        assert failure.classification.severity == FailureSeverity.HIGH
        assert failure.stack_trace != ""
        assert failure.resolution.retryable is False

    def test_execution_is_retryable(self):
        assert is_retryable(FailureCategory.EXECUTION) is True

    def test_input_is_not_retryable(self):
        assert is_retryable(FailureCategory.INPUT) is False

    def test_security_is_not_retryable(self):
        assert is_retryable(FailureCategory.SECURITY) is False

    def test_dependency_is_retryable(self):
        assert is_retryable(FailureCategory.DEPENDENCY) is True

    def test_escalate_after_env(self):
        assert escalate_after(FailureCategory.ENVIRONMENT) == 2

    def test_escalate_after_execution(self):
        assert escalate_after(FailureCategory.EXECUTION) == 1

    def test_escalate_after_dependency(self):
        assert escalate_after(FailureCategory.DEPENDENCY) == 3

    def test_escalate_after_input(self):
        assert escalate_after(FailureCategory.INPUT) == 0

    def test_all_failure_categories_have_metadata(self):
        """Every category should have retryable/escalate_after defined."""
        for cat in FailureCategory:
            assert isinstance(is_retryable(cat), bool)
            assert isinstance(escalate_after(cat), int)


# ===================================================================
# 3. Trace collector
# ===================================================================


class TestTraceCollector:
    """Test TraceCollector lifecycle."""

    def setup_method(self):
        self.collector = TraceCollector()

    def test_start_trace(self):
        trace = self.collector.start_trace(
            task_id="T-100",
            agent_id="AGT-006",
            agent_role="implementer",
        )
        assert trace.task_id == "T-100"
        assert trace.context.agent_id == "AGT-006"
        assert trace.outcome.status == TraceStatus.RUNNING

    def test_get_trace(self):
        trace = self.collector.start_trace(task_id="T-101")
        retrieved = self.collector.get_trace(trace.trace_id)
        assert retrieved.task_id == "T-101"

    def test_get_nonexistent_raises(self):
        with pytest.raises(TraceNotFoundError):
            self.collector.get_trace("TRC-doesnotexist")

    def test_list_traces(self):
        self.collector.start_trace(task_id="T-200")
        self.collector.start_trace(task_id="T-201")
        traces = self.collector.list_traces()
        assert len(traces) == 2

    def test_list_traces_filter_by_status(self):
        t1 = self.collector.start_trace(task_id="T-300")
        self.collector.start_trace(task_id="T-301")
        self.collector.complete_trace(t1.trace_id)

        running = self.collector.list_traces(status=TraceStatus.RUNNING)
        assert len(running) == 1
        completed = self.collector.list_traces(status=TraceStatus.COMPLETED)
        assert len(completed) == 1

    def test_list_traces_filter_by_tenant(self):
        self.collector.start_trace(task_id="T-400", tenant_id="tenant-a")
        self.collector.start_trace(task_id="T-401", tenant_id="tenant-b")

        a_traces = self.collector.list_traces(tenant_id="tenant-a")
        assert len(a_traces) == 1
        assert a_traces[0].tenant_id == "tenant-a"

    def test_list_traces_filter_by_task(self):
        self.collector.start_trace(task_id="T-500")
        self.collector.start_trace(task_id="T-501")
        self.collector.start_trace(task_id="T-500")

        results = self.collector.list_traces(task_id="T-500")
        assert len(results) == 2

    def test_add_step(self):
        trace = self.collector.start_trace(task_id="T-600")
        step = self.collector.add_step(trace.trace_id, "STP-001")
        assert step.step_id == "STP-001"
        assert len(trace.execution) == 1

    def test_add_action(self):
        trace = self.collector.start_trace(task_id="T-700")
        action = self.collector.add_action(
            trace.trace_id,
            step_id="STP-001",
            action_id="ACT-001",
            tool="shell",
            input_data="echo hello",
            output_data="hello",
            exit_code=0,
            duration_ms=50,
        )
        assert action.tool == "shell"
        assert len(trace.execution) == 1  # step auto-created
        assert len(trace.execution[0].actions) == 1

    def test_add_action_to_existing_step(self):
        trace = self.collector.start_trace(task_id="T-701")
        self.collector.add_step(trace.trace_id, "STP-001")
        self.collector.add_action(
            trace.trace_id,
            step_id="STP-001",
            action_id="ACT-001",
            tool="shell",
        )
        self.collector.add_action(
            trace.trace_id,
            step_id="STP-001",
            action_id="ACT-002",
            tool="file_ops",
        )
        assert len(trace.execution) == 1  # same step
        assert len(trace.execution[0].actions) == 2

    def test_complete_trace(self):
        trace = self.collector.start_trace(task_id="T-800")
        self.collector.add_step(trace.trace_id, "STP-001")
        completed = self.collector.complete_trace(trace.trace_id)
        assert completed.outcome.status == TraceStatus.COMPLETED
        assert completed.completed_at is not None
        assert completed.duration_ms >= 0
        # Open steps should be completed
        assert completed.execution[0].completed_at is not None

    def test_complete_trace_with_failure(self):
        trace = self.collector.start_trace(task_id="T-801")
        completed = self.collector.complete_trace(
            trace.trace_id,
            status=TraceStatus.FAILED,
            failure_code="F-EXE-001",
            failure_message="Command failed",
        )
        assert completed.outcome.status == TraceStatus.FAILED
        assert completed.outcome.failure_code == "F-EXE-001"

    def test_record_failure(self):
        trace = self.collector.start_trace(task_id="T-900")
        failure = self.collector.record_failure(
            trace.trace_id,
            message="Permission denied",
            category=FailureCategory.SECURITY,
            severity=FailureSeverity.HIGH,
            subcode="F-SEC-001",
        )
        assert failure.trace_id == trace.trace_id
        assert failure.classification.category == FailureCategory.SECURITY
        assert failure.message == "Permission denied"

        # Trace outcome should be updated
        assert trace.outcome.failure_code == "F-SEC"

    def test_list_failures(self):
        trace = self.collector.start_trace(task_id="T-901")
        self.collector.record_failure(
            trace.trace_id,
            message="err1",
            category=FailureCategory.EXECUTION,
        )
        self.collector.record_failure(
            trace.trace_id,
            message="err2",
            category=FailureCategory.INPUT,
        )

        all_failures = self.collector.list_failures(trace_id=trace.trace_id)
        assert len(all_failures) == 2

        exec_only = self.collector.list_failures(
            trace_id=trace.trace_id,
            category=FailureCategory.EXECUTION,
        )
        assert len(exec_only) == 1
        assert exec_only[0].message == "err1"

    def test_list_failures_filter_by_tenant(self):
        tenant_a_trace = self.collector.start_trace(task_id="T-902", tenant_id="tenant-a")
        tenant_b_trace = self.collector.start_trace(task_id="T-903", tenant_id="tenant-b")
        self.collector.record_failure(
            tenant_a_trace.trace_id,
            message="tenant-a failure",
            category=FailureCategory.EXECUTION,
        )
        self.collector.record_failure(
            tenant_b_trace.trace_id,
            message="tenant-b failure",
            category=FailureCategory.SECURITY,
        )

        tenant_failures = self.collector.list_failures(tenant_id="tenant-a")

        assert len(tenant_failures) == 1
        assert tenant_failures[0].trace_id == tenant_a_trace.trace_id
        assert tenant_failures[0].message == "tenant-a failure"


# ===================================================================
# 4. Artifact retention
# ===================================================================


class TestRetention:
    """Test artifact retention policies."""

    def test_tmp_retention_7_days(self):
        policy = get_retention_policy(ArtifactType.TMP)
        assert policy.retention_days == 7
        assert policy.initial_tier == "hot"

    def test_log_retention_30_days(self):
        policy = get_retention_policy(ArtifactType.LOG)
        assert policy.retention_days == 30
        assert policy.hot_to_warm_days == 30

    def test_dif_retention_90_days(self):
        policy = get_retention_policy(ArtifactType.DIF)
        assert policy.retention_days == 90
        assert policy.initial_tier == "warm"

    def test_rev_is_permanent(self):
        assert is_permanent(ArtifactType.REV) is True
        policy = get_retention_policy(ArtifactType.REV)
        assert policy.retention_days == 0  # 0 = permanent
        assert policy.initial_tier == "cold"

    def test_evd_is_permanent(self):
        assert is_permanent(ArtifactType.EVD) is True

    def test_ses_is_not_permanent(self):
        assert is_permanent(ArtifactType.SES) is False

    def test_all_types_have_policies(self):
        for art_type in ArtifactType:
            policy = get_retention_policy(art_type)
            assert policy.artifact_type == art_type

    def test_storage_path_session(self):
        path = get_storage_path(ArtifactType.SES, 2026, 2, 14, session_id="SES-001")
        assert path == "artifacts/sessions/2026/02/14/SES-001"

    def test_storage_path_evidence(self):
        path = get_storage_path(ArtifactType.EVD, 2026, 2, 14, task_id="T24")
        assert path == "artifacts/evidence/2026/02/T24"

    def test_storage_path_review(self):
        path = get_storage_path(ArtifactType.REV, 2026, 1, 16, task_id="T15")
        assert path == "artifacts/reviews/2026/01/T15"

    def test_storage_path_logs(self):
        path = get_storage_path(
            ArtifactType.LOG,
            2026,
            2,
            14,
            session_id="SES-X",
            run_id="RUN-Y",
        )
        assert "sessions/2026/02/14/SES-X/runs/RUN-Y/logs" in path


# ===================================================================
# 5. Trace API routes
# ===================================================================


class TestTraceAPI:
    """Test trace REST endpoints via TestClient."""

    @pytest.fixture(autouse=True)
    def _setup_client(self, client):
        """Reset the trace collector singleton before each test."""
        from agent33.api.routes.traces import _collector

        _collector._traces.clear()
        _collector._failures.clear()
        self.client = client

    def _start_trace(self, task_id: str = "T-API-001") -> dict:
        resp = self.client.post(
            "/v1/traces/",
            json={
                "task_id": task_id,
                "agent_id": "AGT-006",
                "agent_role": "implementer",
            },
        )
        assert resp.status_code == 201
        return resp.json()

    def _tenant_client(self, tenant_id: str) -> TestClient:
        token = create_access_token(
            "trace-user",
            scopes=["workflows:read", "tools:execute"],
            tenant_id=tenant_id,
        )
        return TestClient(app, headers={"Authorization": f"Bearer {token}"})

    def test_start_trace(self):
        data = self._start_trace()
        assert data["trace_id"].startswith("TRC-")
        assert data["status"] == "running"

    def test_list_traces(self):
        self._start_trace("T-1")
        self._start_trace("T-2")
        resp = self.client.get("/v1/traces/")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_trace(self):
        created = self._start_trace()
        resp = self.client.get(f"/v1/traces/{created['trace_id']}")
        assert resp.status_code == 200
        assert resp.json()["task_id"] == "T-API-001"

    def test_get_trace_is_tenant_scoped(self):
        tenant_a = self._tenant_client("tenant-a")
        tenant_b = self._tenant_client("tenant-b")

        created = tenant_a.post(
            "/v1/traces/",
            json={"task_id": "T-TENANT-A", "agent_id": "AGT-006"},
        )
        trace_id = created.json()["trace_id"]

        assert tenant_a.get(f"/v1/traces/{trace_id}").status_code == 200
        assert tenant_b.get(f"/v1/traces/{trace_id}").status_code == 404

    def test_start_trace_rejects_authenticated_user_without_tenant_context(self):
        tenantless = self._tenant_client("")
        resp = tenantless.post(
            "/v1/traces/",
            json={"task_id": "T-TENANTLESS", "agent_id": "AGT-006"},
        )
        assert resp.status_code == 403
        assert "Tenant context required" in resp.json()["detail"]

    def test_get_trace_rejects_authenticated_user_without_tenant_context(self):
        tenant_a = self._tenant_client("tenant-a")
        tenantless = self._tenant_client("")
        created = tenant_a.post(
            "/v1/traces/",
            json={"task_id": "T-TENANTLESS-READ", "agent_id": "AGT-006"},
        )
        trace_id = created.json()["trace_id"]

        denied = tenantless.get(f"/v1/traces/{trace_id}")
        assert denied.status_code == 403
        assert "Tenant context required" in denied.json()["detail"]

    def test_get_trace_not_found(self):
        resp = self.client.get("/v1/traces/TRC-doesnotexist")
        assert resp.status_code == 404

    def test_add_action(self):
        created = self._start_trace()
        tid = created["trace_id"]
        resp = self.client.post(
            f"/v1/traces/{tid}/actions",
            json={
                "step_id": "STP-001",
                "action_id": "ACT-001",
                "tool": "shell",
                "input_data": "echo test",
                "output_data": "test",
                "exit_code": 0,
                "duration_ms": 100,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["action_id"] == "ACT-001"

    def test_add_action_not_found(self):
        resp = self.client.post(
            "/v1/traces/TRC-nope/actions",
            json={
                "step_id": "STP-001",
                "action_id": "ACT-001",
                "tool": "shell",
            },
        )
        assert resp.status_code == 404

    def test_add_action_is_tenant_scoped(self):
        tenant_a = self._tenant_client("tenant-a")
        tenant_b = self._tenant_client("tenant-b")

        created = tenant_a.post(
            "/v1/traces/",
            json={"task_id": "T-TENANT-ACTION", "agent_id": "AGT-006"},
        )
        trace_id = created.json()["trace_id"]

        denied = tenant_b.post(
            f"/v1/traces/{trace_id}/actions",
            json={"step_id": "STP-001", "action_id": "ACT-001", "tool": "shell"},
        )
        assert denied.status_code == 404

    def test_complete_trace(self):
        created = self._start_trace()
        tid = created["trace_id"]
        resp = self.client.post(
            f"/v1/traces/{tid}/complete",
            json={"status": "completed"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["duration_ms"] >= 0

    def test_complete_trace_failed(self):
        created = self._start_trace()
        tid = created["trace_id"]
        resp = self.client.post(
            f"/v1/traces/{tid}/complete",
            json={
                "status": "failed",
                "failure_code": "F-EXE-001",
                "failure_message": "Test failure",
            },
        )
        assert resp.json()["status"] == "failed"

    def test_record_failure(self):
        created = self._start_trace()
        tid = created["trace_id"]
        resp = self.client.post(
            f"/v1/traces/{tid}/failures",
            json={
                "message": "Sandbox violation",
                "category": "F-SEC",
                "severity": "high",
                "subcode": "F-SEC-002",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["failure_id"].startswith("FLR-")
        assert data["category"] == "F-SEC"

    def test_list_failures(self):
        created = self._start_trace()
        tid = created["trace_id"]
        self.client.post(
            f"/v1/traces/{tid}/failures",
            json={"message": "err1", "category": "F-EXE"},
        )
        self.client.post(
            f"/v1/traces/{tid}/failures",
            json={"message": "err2", "category": "F-INP"},
        )

        resp = self.client.get(f"/v1/traces/{tid}/failures")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_failures_with_category_filter(self):
        created = self._start_trace()
        tid = created["trace_id"]
        self.client.post(
            f"/v1/traces/{tid}/failures",
            json={"message": "e1", "category": "F-EXE"},
        )
        self.client.post(
            f"/v1/traces/{tid}/failures",
            json={"message": "e2", "category": "F-SEC"},
        )

        resp = self.client.get(f"/v1/traces/{tid}/failures?category=F-SEC")
        assert len(resp.json()) == 1
        assert resp.json()[0]["classification"]["category"] == "F-SEC"

    def test_full_trace_lifecycle(self):
        """Full lifecycle: start → add actions → record failure → complete."""
        created = self._start_trace()
        tid = created["trace_id"]

        # Add some actions
        self.client.post(
            f"/v1/traces/{tid}/actions",
            json={
                "step_id": "STP-001",
                "action_id": "ACT-001",
                "tool": "shell",
                "input_data": "make build",
                "output_data": "OK",
                "exit_code": 0,
                "duration_ms": 5000,
            },
        )
        self.client.post(
            f"/v1/traces/{tid}/actions",
            json={
                "step_id": "STP-001",
                "action_id": "ACT-002",
                "tool": "shell",
                "input_data": "make test",
                "output_data": "FAIL",
                "exit_code": 1,
                "duration_ms": 3000,
                "status": "failure",
            },
        )

        # Record failure
        self.client.post(
            f"/v1/traces/{tid}/failures",
            json={
                "message": "Test suite failed",
                "category": "F-VAL",
                "severity": "medium",
                "subcode": "F-VAL-002",
            },
        )

        # Complete
        resp = self.client.post(
            f"/v1/traces/{tid}/complete",
            json={
                "status": "failed",
                "failure_code": "F-VAL-002",
                "failure_message": "Test suite failed",
            },
        )
        assert resp.json()["status"] == "failed"

        # Verify full trace
        resp = self.client.get(f"/v1/traces/{tid}")
        trace = resp.json()
        assert trace["outcome"]["status"] == "failed"
        assert len(trace["execution"]) == 1
        assert len(trace["execution"][0]["actions"]) == 2
