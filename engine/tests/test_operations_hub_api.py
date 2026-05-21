"""Phase 27 tests for operations hub service and API routes.

Covers:
- OperationsHubService aggregation from traces, budgets, improvements, workflows
- Lifecycle control dispatch (pause / resume / cancel)
- API routes: GET /v1/operations/hub, /v1/operations/processes/{id},
  POST /v1/operations/processes/{id}/control, GET /v1/operations/stream
- Edge cases: empty sources, multi-tenant isolation, error paths, SSE stream
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes.autonomy import get_autonomy_service
from agent33.api.routes.improvements import get_improvement_service
from agent33.api.routes.traces import get_trace_collector
from agent33.api.routes.workflows import get_execution_history
from agent33.autonomy.models import BudgetState
from agent33.improvement.models import IntakeContent, IntakeStatus, ResearchIntake
from agent33.main import app
from agent33.observability.trace_models import TraceStatus
from agent33.security.auth import create_access_token
from agent33.services.operations_hub import (
    OperationsHubService,
    ProcessNotFoundError,
    UnsupportedControlError,
)


def _client(scopes: list[str], *, tenant_id: str = "") -> TestClient:
    token = create_access_token("operations-user", scopes=scopes, tenant_id=tenant_id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture(autouse=True)
def reset_operations_sources() -> None:
    trace_collector = get_trace_collector()
    trace_collector._traces.clear()
    trace_collector._failures.clear()

    autonomy_service = get_autonomy_service()
    autonomy_service._budgets.clear()
    autonomy_service._enforcers.clear()
    autonomy_service._escalations.clear()

    improvement_service = get_improvement_service()
    improvement_service._intakes.clear()

    get_execution_history().clear()
    yield

    trace_collector._traces.clear()
    trace_collector._failures.clear()
    autonomy_service._budgets.clear()
    autonomy_service._enforcers.clear()
    autonomy_service._escalations.clear()
    improvement_service._intakes.clear()
    get_execution_history().clear()


@pytest.fixture
def anonymous_client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def read_client() -> TestClient:
    return _client(["workflows:read"])


@pytest.fixture
def execute_client() -> TestClient:
    return _client(["workflows:execute"])


@pytest.fixture
def no_scope_client() -> TestClient:
    return _client([])


@pytest.fixture
def tenant_read_client() -> TestClient:
    return _client(["workflows:read"], tenant_id="tenant-alpha")


@pytest.fixture
def seeded_state() -> dict[str, str]:
    trace_collector = get_trace_collector()
    trace_alpha = trace_collector.start_trace(
        task_id="trace-alpha",
        tenant_id="tenant-alpha",
        agent_id="agent-alpha",
    )
    trace_beta = trace_collector.start_trace(
        task_id="trace-beta",
        tenant_id="tenant-beta",
        agent_id="agent-beta",
    )
    trace_collector.complete_trace(trace_beta.trace_id, status=TraceStatus.COMPLETED)

    autonomy_service = get_autonomy_service()
    active_budget = autonomy_service.create_budget(task_id="budget-active", agent_id="agent-a")
    autonomy_service.activate(active_budget.budget_id)
    draft_budget = autonomy_service.create_budget(task_id="budget-draft", agent_id="agent-b")

    improvements = get_improvement_service()
    intake = improvements.submit_intake(
        ResearchIntake(content=IntakeContent(title="Improve workflow latency"))
    )
    improvements.transition_intake(intake.intake_id, IntakeStatus.TRIAGED)
    improvements.transition_intake(intake.intake_id, IntakeStatus.ANALYZING)

    now_ts = datetime.now(UTC).timestamp()
    history = get_execution_history()
    history.append(
        {
            "run_id": "wf-recent-run",
            "workflow_name": "wf-recent",
            "trigger_type": "manual",
            "status": "completed",
            "duration_ms": 420,
            "timestamp": now_ts - 60,
            "error": None,
            "job_id": None,
        }
    )
    history.append(
        {
            "workflow_name": "wf-old",
            "trigger_type": "scheduled",
            "status": "failed",
            "duration_ms": 1200,
            "timestamp": now_ts - (30 * 3600),
            "error": "timeout",
            "job_id": "job-old",
        }
    )

    return {
        "trace_alpha_id": trace_alpha.trace_id,
        "trace_beta_id": trace_beta.trace_id,
        "active_budget_id": active_budget.budget_id,
        "draft_budget_id": draft_budget.budget_id,
        "intake_id": intake.intake_id,
        "workflow_run_id": "wf-recent-run",
        "legacy_workflow_timestamp": str(int(now_ts - (30 * 3600))),
    }


def test_hub_requires_auth(anonymous_client: TestClient) -> None:
    response = anonymous_client.get("/v1/operations/hub")
    assert response.status_code == 401


def test_hub_requires_workflows_read_scope(no_scope_client: TestClient) -> None:
    response = no_scope_client.get("/v1/operations/hub")
    assert response.status_code == 403
    assert "workflows:read" in response.json()["detail"]


def test_control_requires_workflows_execute_scope(
    read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    response = read_client.post(
        f"/v1/operations/processes/{seeded_state['trace_alpha_id']}/control",
        json={"action": "cancel"},
    )
    assert response.status_code == 403
    assert "workflows:execute" in response.json()["detail"]


def test_hub_aggregates_expected_process_types(
    read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    response = read_client.get("/v1/operations/hub")
    assert response.status_code == 200
    payload = response.json()
    process_types = {item["type"] for item in payload["processes"]}
    assert {"trace", "autonomy_budget", "improvement_intake", "workflow"} <= process_types


def test_hub_include_filter_limits_sources(
    read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    response = read_client.get("/v1/operations/hub?include=traces,budgets")
    assert response.status_code == 200
    process_types = {item["type"] for item in response.json()["processes"]}
    assert process_types <= {"trace", "autonomy_budget"}


def test_hub_invalid_include_returns_400(read_client: TestClient) -> None:
    response = read_client.get("/v1/operations/hub?include=traces,invalid")
    assert response.status_code == 400
    assert "Invalid include values" in response.json()["detail"]


def test_hub_since_filter_excludes_old_workflows(
    read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    response = read_client.get(
        "/v1/operations/hub",
        params={"include": "workflows", "since": since},
    )
    assert response.status_code == 200
    names = {item["name"] for item in response.json()["processes"]}
    assert "wf-recent" in names
    assert "wf-old" not in names


def test_hub_status_filter_returns_running_only(
    read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    response = read_client.get("/v1/operations/hub?status=running")
    assert response.status_code == 200
    processes = response.json()["processes"]
    assert processes
    assert all(item["status"] == "running" for item in processes)


def test_hub_tenant_filter_excludes_non_tenant_sources(
    tenant_read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    response = tenant_read_client.get("/v1/operations/hub")
    assert response.status_code == 200
    processes = response.json()["processes"]
    assert processes
    assert all(item["type"] == "trace" for item in processes)
    assert all(item["metadata"]["tenant_id"] == "tenant-alpha" for item in processes)


def test_get_process_returns_trace_detail(
    read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    response = read_client.get(f"/v1/operations/processes/{seeded_state['trace_alpha_id']}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "trace"
    assert payload["id"] == seeded_state["trace_alpha_id"]


def test_get_process_missing_returns_404(read_client: TestClient) -> None:
    response = read_client.get("/v1/operations/processes/missing-id")
    assert response.status_code == 404


def test_control_cancel_trace_marks_trace_cancelled(
    execute_client: TestClient, seeded_state: dict[str, str]
) -> None:
    trace_id = seeded_state["trace_alpha_id"]
    response = execute_client.post(
        f"/v1/operations/processes/{trace_id}/control",
        json={"action": "cancel"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    trace = get_trace_collector().get_trace(trace_id)
    assert trace.outcome.status == TraceStatus.CANCELLED


def test_control_budget_pause_resume_cancel(
    execute_client: TestClient, seeded_state: dict[str, str]
) -> None:
    budget_id = seeded_state["active_budget_id"]

    pause_response = execute_client.post(
        f"/v1/operations/processes/{budget_id}/control",
        json={"action": "pause"},
    )
    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == "suspended"

    resume_response = execute_client.post(
        f"/v1/operations/processes/{budget_id}/control",
        json={"action": "resume"},
    )
    assert resume_response.status_code == 200
    assert resume_response.json()["status"] == "active"

    cancel_response = execute_client.post(
        f"/v1/operations/processes/{budget_id}/control",
        json={"action": "cancel"},
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] in {"expired", "completed"}

    budget = get_autonomy_service().get_budget(budget_id)
    assert budget.state in {BudgetState.EXPIRED, BudgetState.COMPLETED}


def test_control_improvement_returns_409(
    execute_client: TestClient, seeded_state: dict[str, str]
) -> None:
    response = execute_client.post(
        f"/v1/operations/processes/{seeded_state['intake_id']}/control",
        json={"action": "cancel"},
    )
    assert response.status_code == 409


def test_control_workflow_returns_409(
    execute_client: TestClient, read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    hub = read_client.get("/v1/operations/hub?include=workflows").json()
    workflow_process = next(item for item in hub["processes"] if item["type"] == "workflow")
    response = execute_client.post(
        f"/v1/operations/processes/{workflow_process['id']}/control",
        json={"action": "cancel"},
    )
    assert response.status_code == 409


def test_control_missing_process_returns_404(execute_client: TestClient) -> None:
    response = execute_client.post(
        "/v1/operations/processes/missing-id/control",
        json={"action": "cancel"},
    )
    assert response.status_code == 404


# =========================================================================
# Hub empty-sources and limit/sort tests
# =========================================================================


def test_hub_empty_sources_returns_zero_processes(read_client: TestClient) -> None:
    """When all subsystems are empty, hub returns zero active processes."""
    response = read_client.get("/v1/operations/hub")
    assert response.status_code == 200
    payload = response.json()
    assert payload["active_count"] == 0
    assert payload["processes"] == []
    assert "timestamp" in payload


def test_hub_limit_caps_returned_processes(
    read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    """Limit query parameter caps the number of returned processes."""
    response = read_client.get("/v1/operations/hub?limit=2")
    assert response.status_code == 200
    payload = response.json()
    assert payload["active_count"] <= 2
    assert len(payload["processes"]) <= 2


def test_hub_processes_sorted_by_most_recent_first(
    read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    """Processes are sorted most-recent started_at first."""
    response = read_client.get("/v1/operations/hub")
    assert response.status_code == 200
    processes = response.json()["processes"]
    if len(processes) >= 2:
        timestamps = [p["started_at"] for p in processes]
        assert timestamps == sorted(timestamps, reverse=True)


def test_hub_internal_started_at_stripped(
    read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    """Internal _started_at key used for sorting is not in response."""
    response = read_client.get("/v1/operations/hub")
    assert response.status_code == 200
    for proc in response.json()["processes"]:
        assert "_started_at" not in proc


# =========================================================================
# Process detail for each type
# =========================================================================


def test_get_process_returns_budget_detail(
    read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    """Process detail for a budget returns correct type and metadata."""
    budget_id = seeded_state["active_budget_id"]
    response = read_client.get(f"/v1/operations/processes/{budget_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "autonomy_budget"
    assert payload["id"] == budget_id
    assert "agent_id" in payload["metadata"]
    assert "approved_by" in payload["metadata"]


def test_get_process_returns_improvement_detail(
    read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    """Process detail for an improvement intake returns correct shape."""
    intake_id = seeded_state["intake_id"]
    response = read_client.get(f"/v1/operations/processes/{intake_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "improvement_intake"
    assert payload["id"] == intake_id
    assert payload["name"] == "Improve workflow latency"
    assert payload["metadata"]["research_type"] == "external"


def test_get_process_returns_workflow_detail(
    read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    """Process detail for a workflow returns correct shape."""
    hub = read_client.get("/v1/operations/hub?include=workflows").json()
    wf_procs = [p for p in hub["processes"] if p["type"] == "workflow"]
    assert wf_procs, "Expected at least one workflow process in seeded state"
    wf_id = wf_procs[0]["id"]

    response = read_client.get(f"/v1/operations/processes/{wf_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "workflow"
    assert payload["id"] == wf_id
    assert payload["metadata"]["run_id"]
    assert payload["id"] == f"workflow:{payload['metadata']['run_id']}"
    assert "trigger_type" in payload["metadata"]
    assert "duration_ms" in payload["metadata"]


# =========================================================================
# Process shape and field verification
# =========================================================================


def test_trace_process_shape_in_hub(read_client: TestClient, seeded_state: dict[str, str]) -> None:
    """Trace entries in hub have all expected fields."""
    response = read_client.get("/v1/operations/hub?include=traces")
    assert response.status_code == 200
    traces = [p for p in response.json()["processes"] if p["type"] == "trace"]
    assert traces
    proc = traces[0]
    assert "id" in proc
    assert "status" in proc
    assert "started_at" in proc
    assert "name" in proc
    assert "metadata" in proc
    meta = proc["metadata"]
    assert "tenant_id" in meta
    assert "agent_id" in meta
    assert "session_id" in meta
    assert "run_id" in meta


def test_budget_process_shape_in_hub(
    read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    """Budget entries in hub have all expected fields."""
    response = read_client.get("/v1/operations/hub?include=budgets")
    assert response.status_code == 200
    budgets = [p for p in response.json()["processes"] if p["type"] == "autonomy_budget"]
    assert budgets
    proc = budgets[0]
    assert "id" in proc
    assert "status" in proc
    assert "started_at" in proc
    assert "name" in proc
    assert proc["metadata"]["agent_id"]


def test_improvement_process_shape_in_hub(
    read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    """Improvement intake entries in hub have all expected fields."""
    response = read_client.get("/v1/operations/hub?include=improvements")
    assert response.status_code == 200
    intakes = [p for p in response.json()["processes"] if p["type"] == "improvement_intake"]
    assert intakes
    proc = intakes[0]
    assert proc["name"] == "Improve workflow latency"
    assert proc["metadata"]["research_type"] == "external"
    assert proc["metadata"]["urgency"] in {"high", "medium", "low"}


def test_workflow_process_shape_in_hub(
    read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    """Workflow entries in hub have all expected fields."""
    response = read_client.get("/v1/operations/hub?include=workflows")
    assert response.status_code == 200
    workflows = [p for p in response.json()["processes"] if p["type"] == "workflow"]
    assert workflows
    proc = workflows[0]
    assert proc["id"] == f"workflow:{proc['metadata']['run_id']}"
    assert proc["metadata"]["run_id"]
    assert "trigger_type" in proc["metadata"]
    assert "duration_ms" in proc["metadata"]


def test_legacy_workflow_history_entry_gets_compatibility_run_id(
    read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    response = read_client.get("/v1/operations/hub?include=workflows&since=1970-01-01T00:00:00Z")
    assert response.status_code == 200

    legacy = next(proc for proc in response.json()["processes"] if proc["name"] == "wf-old")
    assert legacy["metadata"]["run_id"].startswith("legacy-wf-old-")
    assert legacy["id"] == f"workflow:{legacy['metadata']['run_id']}"


def test_legacy_workflow_process_id_still_resolves(
    seeded_state: dict[str, str],
) -> None:
    svc = OperationsHubService()

    result = svc.get_process(f"workflow:wf-old:{seeded_state['legacy_workflow_timestamp']}")

    assert result["type"] == "workflow"
    assert result["metadata"]["run_id"].startswith("legacy-wf-old-")


# =========================================================================
# Invalid since timestamp
# =========================================================================


def test_hub_invalid_since_returns_400(read_client: TestClient) -> None:
    """Invalid since timestamp returns 400."""
    response = read_client.get("/v1/operations/hub?since=not-a-date")
    assert response.status_code == 400
    assert "Invalid since" in response.json()["detail"]


# =========================================================================
# Invalid action enum returns 422
# =========================================================================


def test_control_invalid_action_returns_422(
    execute_client: TestClient, seeded_state: dict[str, str]
) -> None:
    """POST /control with a non-enum action value returns 422 validation error."""
    response = execute_client.post(
        f"/v1/operations/processes/{seeded_state['trace_alpha_id']}/control",
        json={"action": "explode"},
    )
    assert response.status_code == 422


# =========================================================================
# Unsupported trace actions (pause/resume on trace)
# =========================================================================


def test_control_pause_on_trace_returns_409(
    execute_client: TestClient, seeded_state: dict[str, str]
) -> None:
    """Pause action is unsupported for traces and returns 409."""
    response = execute_client.post(
        f"/v1/operations/processes/{seeded_state['trace_alpha_id']}/control",
        json={"action": "pause"},
    )
    assert response.status_code == 409
    assert "unsupported" in response.json()["detail"].lower()


def test_control_resume_on_trace_returns_409(
    execute_client: TestClient, seeded_state: dict[str, str]
) -> None:
    """Resume action is unsupported for traces and returns 409."""
    response = execute_client.post(
        f"/v1/operations/processes/{seeded_state['trace_alpha_id']}/control",
        json={"action": "resume"},
    )
    assert response.status_code == 409
    assert "unsupported" in response.json()["detail"].lower()


# =========================================================================
# Multi-tenant isolation
# =========================================================================


def test_tenant_client_cannot_access_other_tenant_process(
    seeded_state: dict[str, str],
) -> None:
    """Tenant-scoped client gets 404 for another tenant's trace."""
    tenant_beta_client = _client(["workflows:read"], tenant_id="tenant-beta")
    # trace_alpha belongs to tenant-alpha
    response = tenant_beta_client.get(f"/v1/operations/processes/{seeded_state['trace_alpha_id']}")
    assert response.status_code == 404


def test_tenant_client_can_access_own_trace(
    seeded_state: dict[str, str],
) -> None:
    """Tenant-scoped client can access their own trace detail."""
    alpha_client = _client(["workflows:read"], tenant_id="tenant-alpha")
    response = alpha_client.get(f"/v1/operations/processes/{seeded_state['trace_alpha_id']}")
    assert response.status_code == 200
    assert response.json()["metadata"]["tenant_id"] == "tenant-alpha"


def test_tenant_client_cannot_control_other_tenant_trace(
    seeded_state: dict[str, str],
) -> None:
    """Tenant-scoped client gets 404 when trying to control another tenant's trace."""
    beta_exec = _client(["workflows:read", "workflows:execute"], tenant_id="tenant-beta")
    response = beta_exec.post(
        f"/v1/operations/processes/{seeded_state['trace_alpha_id']}/control",
        json={"action": "cancel"},
    )
    assert response.status_code == 404


def test_tenant_hub_excludes_budgets_improvements_workflows(
    tenant_read_client: TestClient, seeded_state: dict[str, str]
) -> None:
    """Tenant-scoped hub only returns traces, not budgets/improvements/workflows."""
    response = tenant_read_client.get("/v1/operations/hub")
    assert response.status_code == 200
    types = {p["type"] for p in response.json()["processes"]}
    assert types <= {"trace"}, f"Expected only traces but got {types}"


# =========================================================================
# SSE stream endpoint
# =========================================================================


def test_stream_without_nats_returns_503(read_client: TestClient) -> None:
    """Stream endpoint returns 503 when NATS is not available."""
    original = getattr(app.state, "nats_bus", None)
    try:
        app.state.nats_bus = None
        response = read_client.get("/v1/operations/stream")
        assert response.status_code == 503
        assert "NATS" in response.json()["detail"]
    finally:
        if original is not None:
            app.state.nats_bus = original
        elif hasattr(app.state, "nats_bus"):
            delattr(app.state, "nats_bus")


def test_stream_requires_read_scope(no_scope_client: TestClient) -> None:
    """Stream endpoint requires workflows:read scope."""
    response = no_scope_client.get("/v1/operations/stream")
    assert response.status_code == 403
    assert "workflows:read" in response.json()["detail"]


# =========================================================================
# Service-level unit tests (direct OperationsHubService)
# =========================================================================


class TestServiceGetHub:
    """Direct unit tests for OperationsHubService.get_hub."""

    def test_empty_hub_returns_zero_count(self) -> None:
        """Empty subsystems yield active_count=0."""
        svc = OperationsHubService()
        result = svc.get_hub()
        assert result["active_count"] == 0
        assert result["processes"] == []

    def test_include_traces_only_skips_others(self) -> None:
        """include={'traces'} does not query budgets/improvements/workflows."""
        trace_collector = get_trace_collector()
        trace_collector.start_trace(task_id="svc-trace", agent_id="a")
        svc = OperationsHubService()
        result = svc.get_hub(include={"traces"})
        types = {p["type"] for p in result["processes"]}
        assert types <= {"trace"}

    def test_since_filters_old_entries(self) -> None:
        """Entries older than since are excluded."""
        svc = OperationsHubService()
        # With no data and a very old since, we still get 0
        old_since = datetime.now(UTC) - timedelta(days=30)
        result = svc.get_hub(since=old_since)
        assert result["active_count"] == 0

    def test_status_filter_applied_after_aggregation(self, seeded_state: dict[str, str]) -> None:
        """Status filter removes non-matching processes across all sources."""
        svc = OperationsHubService()
        result = svc.get_hub(status="running")
        for proc in result["processes"]:
            assert proc["status"] == "running"


class TestServiceGetProcess:
    """Direct unit tests for OperationsHubService.get_process."""

    def test_trace_detail_includes_actions(self, seeded_state: dict[str, str]) -> None:
        """Trace detail includes actions list."""
        svc = OperationsHubService()
        trace_id = seeded_state["trace_alpha_id"]
        result = svc.get_process(trace_id)
        assert result["type"] == "trace"
        assert "actions" in result

    def test_budget_detail_includes_approved_by(self, seeded_state: dict[str, str]) -> None:
        """Budget detail includes approved_by in metadata."""
        svc = OperationsHubService()
        budget_id = seeded_state["active_budget_id"]
        result = svc.get_process(budget_id)
        assert result["type"] == "autonomy_budget"
        assert "approved_by" in result["metadata"]

    def test_missing_process_raises_not_found(self) -> None:
        """Non-existent process ID raises ProcessNotFoundError."""
        svc = OperationsHubService()
        with pytest.raises(ProcessNotFoundError):
            svc.get_process("nonexistent-xyz-999")

    def test_workflow_no_matching_entry_raises(self) -> None:
        """Well-formed workflow ID with no matching history raises."""
        svc = OperationsHubService()
        with pytest.raises(ProcessNotFoundError):
            svc.get_process("workflow:phantom:9999999999")

    def test_workflow_bad_format_raises_not_found(self) -> None:
        """Malformed workflow: prefix raises ProcessNotFoundError."""
        svc = OperationsHubService()
        with pytest.raises(ProcessNotFoundError):
            svc.get_process("workflow:missing-timestamp")

    def test_workflow_non_numeric_legacy_suffix_raises_not_found(self) -> None:
        """Malformed legacy workflow IDs should fail closed."""
        svc = OperationsHubService()
        with pytest.raises(ProcessNotFoundError):
            svc.get_process("workflow:bad:timestamp")


class TestServiceControlProcess:
    """Direct unit tests for OperationsHubService.control_process."""

    def test_cancel_trace_sets_cancelled_status(self, seeded_state: dict[str, str]) -> None:
        """Cancel on trace sets outcome to CANCELLED."""
        svc = OperationsHubService()
        trace_id = seeded_state["trace_alpha_id"]
        result = svc.control_process(trace_id, "cancel")
        assert result["status"] == "cancelled"

        trace = get_trace_collector().get_trace(trace_id)
        assert trace.outcome.status == TraceStatus.CANCELLED

    def test_pause_trace_raises_unsupported(self, seeded_state: dict[str, str]) -> None:
        """Pause on a trace raises UnsupportedControlError."""
        svc = OperationsHubService()
        with pytest.raises(UnsupportedControlError, match="unsupported for trace"):
            svc.control_process(seeded_state["trace_alpha_id"], "pause")

    def test_pause_then_resume_budget(self, seeded_state: dict[str, str]) -> None:
        """Pause and resume correctly transition budget state."""
        svc = OperationsHubService()
        budget_id = seeded_state["active_budget_id"]

        paused = svc.control_process(budget_id, "pause")
        assert paused["status"] == "suspended"

        resumed = svc.control_process(budget_id, "resume")
        assert resumed["status"] == "active"

    def test_cancel_budget_sets_terminal_state(self, seeded_state: dict[str, str]) -> None:
        """Cancel on budget sets it to expired or completed."""
        svc = OperationsHubService()
        budget_id = seeded_state["active_budget_id"]
        result = svc.control_process(budget_id, "cancel")
        assert result["status"] in {"expired", "completed"}

    def test_control_on_workflow_raises_unsupported(self, seeded_state: dict[str, str]) -> None:
        """Control on workflow history raises UnsupportedControlError."""
        svc = OperationsHubService()
        with pytest.raises(UnsupportedControlError, match="workflow history"):
            svc.control_process("workflow:wf-recent:123", "cancel")

    def test_control_on_improvement_raises_unsupported(self, seeded_state: dict[str, str]) -> None:
        """Control on improvement intake raises UnsupportedControlError."""
        svc = OperationsHubService()
        intake_id = seeded_state["intake_id"]
        with pytest.raises(UnsupportedControlError, match="improvement intake"):
            svc.control_process(intake_id, "cancel")

    def test_control_not_found_raises(self) -> None:
        """Control on unknown ID raises ProcessNotFoundError."""
        svc = OperationsHubService()
        with pytest.raises(ProcessNotFoundError):
            svc.control_process("completely-unknown-id", "cancel")

    def test_tenant_scoped_control_rejects_other_tenant(
        self, seeded_state: dict[str, str]
    ) -> None:
        """Tenant-scoped control rejects traces owned by another tenant."""
        svc = OperationsHubService()
        # trace_alpha belongs to tenant-alpha
        with pytest.raises(ProcessNotFoundError):
            svc.control_process(
                seeded_state["trace_alpha_id"],
                "cancel",
                tenant_id="tenant-beta",
            )
