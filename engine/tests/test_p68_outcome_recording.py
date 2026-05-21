"""Tests for P68-Lite: auto-outcome recording in agent invoke routes.

Verifies that:
1. Successful single invocation records SUCCESS_RATE=1.0 and LATENCY_MS events
2. Failed single invocation records SUCCESS_RATE=0.0 with error metadata
3. Successful iterative invocation records SUCCESS_RATE, LATENCY_MS,
   and conditionally FAILURE_CLASS events
4. Failed iterative invocation records SUCCESS_RATE=0.0
5. Outcome recording failure does NOT break the invocation response
6. OutcomesService is wired via app.state (not just module-level singleton)
7. The outcomes routes use get_outcomes_service (app.state fallback)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agent33.agents.definition import AgentDefinition, AgentRole
from agent33.agents.registry import AgentRegistry
from agent33.agents.runtime import AgentResult, IterativeAgentResult
from agent33.api.routes.agents import _record_outcome_safe
from agent33.evaluation.ppack_ab_models import PPackABAssignment, PPackABVariant
from agent33.evaluation.ppack_ab_persistence import PPackABPersistence
from agent33.evaluation.ppack_ab_service import PPackABService
from agent33.main import app
from agent33.outcomes.models import OutcomeMetricType
from agent33.outcomes.service import OutcomesService
from agent33.security.auth import create_access_token

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MINIMAL_DEF = AgentDefinition(
    name="test-agent",
    version="1.0.0",
    role=AgentRole.WORKER,
    description="A test agent for P68",
    skills=[],
)


def _make_registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(_MINIMAL_DEF)
    return reg


def _make_agent_result(**overrides: Any) -> AgentResult:
    defaults: dict[str, Any] = {
        "output": {"response": "hello"},
        "raw_response": "hello",
        "tokens_used": 42,
        "model": "test-model",
        "routing_decision": None,
    }
    defaults.update(overrides)
    return AgentResult(**defaults)


def _make_iterative_result(**overrides: Any) -> IterativeAgentResult:
    defaults: dict[str, Any] = {
        "output": {"response": "done"},
        "raw_response": "done",
        "tokens_used": 100,
        "model": "test-model",
        "iterations": 3,
        "tool_calls_made": 5,
        "tools_used": ["shell", "file_ops"],
        "termination_reason": "complete",
        "routing_decision": None,
    }
    defaults.update(overrides)
    return IterativeAgentResult(**defaults)


@pytest.fixture()
def outcomes_service() -> OutcomesService:
    return OutcomesService()


@pytest.fixture()
def invoke_client(outcomes_service: OutcomesService) -> TestClient:
    """Client with agent registry and outcomes service on app.state."""
    token = create_access_token(
        "test-user",
        scopes=["agents:invoke", "agents:read"],
        tenant_id="t-abc",
    )
    registry = _make_registry()
    app.state.agent_registry = registry
    app.state.outcomes_service = outcomes_service
    app.state.ppack_ab_service = PPackABService(
        outcomes_service=outcomes_service,
        persistence=PPackABPersistence(":memory:"),
    )
    # model_router needed for iterative; install a mock to avoid 503
    app.state.model_router = MagicMock()
    client = TestClient(
        app,
        headers={
            "Authorization": f"Bearer {token}",
            "X-Session-ID": "test-session-123",
        },
    )
    yield client  # type: ignore[misc]
    # Cleanup app.state attributes we set
    for attr in ("agent_registry", "outcomes_service", "ppack_ab_service", "model_router"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


# ---------------------------------------------------------------------------
# Test: _record_outcome_safe is non-blocking on failure
# ---------------------------------------------------------------------------


def test_record_outcome_safe_does_not_raise_on_service_error() -> None:
    """Outcome recording must NEVER propagate exceptions to caller."""
    broken_svc = OutcomesService()
    broken_svc.record_event = MagicMock(side_effect=RuntimeError("storage is down"))  # type: ignore[method-assign]

    # This must not raise
    _record_outcome_safe(
        broken_svc,
        tenant_id="t-1",
        domain="agent-x",
        event_type="invoke",
        metric_type=OutcomeMetricType.SUCCESS_RATE,
        value=1.0,
    )
    broken_svc.record_event.assert_called_once()


def test_record_outcome_safe_noop_when_service_is_none() -> None:
    """When outcomes_service is None, nothing happens and no error is raised."""
    _record_outcome_safe(
        None,
        tenant_id="t-1",
        domain="agent-x",
        event_type="invoke",
        metric_type=OutcomeMetricType.SUCCESS_RATE,
        value=1.0,
    )


# ---------------------------------------------------------------------------
# Test: Single invoke records SUCCESS_RATE and LATENCY_MS on success
# ---------------------------------------------------------------------------


@patch("agent33.api.routes.agents.AgentRuntime")
def test_invoke_records_success_and_latency(
    mock_runtime_cls: MagicMock,
    invoke_client: TestClient,
    outcomes_service: OutcomesService,
) -> None:
    mock_instance = MagicMock()
    mock_instance.invoke = AsyncMock(return_value=_make_agent_result())
    mock_runtime_cls.return_value = mock_instance

    response = invoke_client.post(
        "/v1/agents/test-agent/invoke",
        json={"inputs": {"message": "hi"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["agent"] == "test-agent"
    assert body["tokens_used"] == 42
    assert body["cadre_profile"]["cadre"] == "execution_orchestration"
    assert body["cadre_profile"]["label"] == "Execution / Orchestration"

    # Verify outcome events were recorded
    events = outcomes_service.list_events(tenant_id="t-abc", domain="test-agent")
    assert len(events) == 2

    success_events = [e for e in events if e.metric_type == OutcomeMetricType.SUCCESS_RATE]
    latency_events = [e for e in events if e.metric_type == OutcomeMetricType.LATENCY_MS]

    assert len(success_events) == 1
    assert success_events[0].value == 1.0
    assert success_events[0].metadata["termination"] == "success"
    assert success_events[0].metadata["model"] == "test-model"
    assert success_events[0].metadata["tokens"] == 42
    assert success_events[0].metadata["ppack_variant"] in {"control", "treatment"}
    assert success_events[0].metadata["experiment_key"] == "ppack_v3"
    assert success_events[0].domain == "test-agent"
    assert success_events[0].event_type == "invoke"

    assert len(latency_events) == 1
    assert latency_events[0].value >= 0  # mocked calls may complete in 0ms
    assert isinstance(latency_events[0].value, float)
    assert latency_events[0].metadata["agent"] == "test-agent"
    assert latency_events[0].metadata["ppack_variant"] in {"control", "treatment"}


@patch("agent33.api.routes.agents.AgentRuntime")
def test_invoke_reuses_single_ppack_assignment_per_request(
    mock_runtime_cls: MagicMock,
    invoke_client: TestClient,
    outcomes_service: OutcomesService,
) -> None:
    mock_instance = MagicMock()
    mock_instance.invoke = AsyncMock(return_value=_make_agent_result())
    mock_runtime_cls.return_value = mock_instance

    assignment = PPackABAssignment(
        tenant_id="t-abc",
        session_id="test-session-123",
        variant=PPackABVariant.TREATMENT,
        assignment_hash="abc123",
    )
    mock_ab_service = MagicMock()
    mock_ab_service.assign_variant.return_value = assignment
    app.state.ppack_ab_service = mock_ab_service

    response = invoke_client.post(
        "/v1/agents/test-agent/invoke",
        json={"inputs": {"message": "hi"}},
    )
    assert response.status_code == 200
    assert mock_ab_service.assign_variant.call_count == 1
    assert mock_runtime_cls.call_args.kwargs["ppack_variant"] == assignment.variant.value

    events = outcomes_service.list_events(tenant_id="t-abc", domain="test-agent")
    assert len(events) == 2
    assert {
        event.metadata["ppack_variant"] for event in events if "ppack_variant" in event.metadata
    } == {assignment.variant.value}


# ---------------------------------------------------------------------------
# Test: Single invoke records SUCCESS_RATE=0.0 on ValueError
# ---------------------------------------------------------------------------


@patch("agent33.api.routes.agents.AgentRuntime")
def test_invoke_records_failure_on_value_error(
    mock_runtime_cls: MagicMock,
    invoke_client: TestClient,
    outcomes_service: OutcomesService,
) -> None:
    mock_instance = MagicMock()
    mock_instance.invoke = AsyncMock(side_effect=ValueError("bad input"))
    mock_runtime_cls.return_value = mock_instance

    response = invoke_client.post(
        "/v1/agents/test-agent/invoke",
        json={"inputs": {"message": "hi"}},
    )
    assert response.status_code == 422

    events = outcomes_service.list_events(tenant_id="t-abc", domain="test-agent")
    assert len(events) == 1
    assert events[0].metric_type == OutcomeMetricType.SUCCESS_RATE
    assert events[0].value == 0.0
    assert events[0].metadata["termination"] == "validation_error"
    assert "bad input" in events[0].metadata["error"]


# ---------------------------------------------------------------------------
# Test: Single invoke records SUCCESS_RATE=0.0 on RuntimeError
# ---------------------------------------------------------------------------


@patch("agent33.api.routes.agents.AgentRuntime")
def test_invoke_records_failure_on_runtime_error(
    mock_runtime_cls: MagicMock,
    invoke_client: TestClient,
    outcomes_service: OutcomesService,
) -> None:
    mock_instance = MagicMock()
    mock_instance.invoke = AsyncMock(side_effect=RuntimeError("LLM down"))
    mock_runtime_cls.return_value = mock_instance

    response = invoke_client.post(
        "/v1/agents/test-agent/invoke",
        json={"inputs": {"message": "hi"}},
    )
    assert response.status_code == 502

    events = outcomes_service.list_events(tenant_id="t-abc", domain="test-agent")
    assert len(events) == 1
    assert events[0].value == 0.0
    assert events[0].metadata["termination"] == "runtime_error"


# ---------------------------------------------------------------------------
# Test: Iterative invoke records SUCCESS_RATE, LATENCY, no FAILURE_CLASS
# for successful "complete" termination
# ---------------------------------------------------------------------------


@patch("agent33.api.routes.agents.AgentRuntime")
def test_iterative_invoke_records_success(
    mock_runtime_cls: MagicMock,
    invoke_client: TestClient,
    outcomes_service: OutcomesService,
) -> None:
    # Install tool_registry and tool_governance to avoid 503
    app.state.tool_registry = MagicMock()
    app.state.tool_registry.list_all.return_value = []
    app.state.tool_governance = MagicMock()

    mock_instance = MagicMock()
    mock_instance.invoke_iterative = AsyncMock(
        return_value=_make_iterative_result(termination_reason="complete")
    )
    mock_runtime_cls.return_value = mock_instance

    response = invoke_client.post(
        "/v1/agents/test-agent/invoke-iterative",
        json={"inputs": {"task": "do something"}, "max_iterations": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["termination_reason"] == "complete"
    assert body["iterations"] == 3
    assert body["cadre_profile"]["required_artifact"].startswith("Patch summary")

    events = outcomes_service.list_events(tenant_id="t-abc", domain="test-agent")
    # Should have SUCCESS_RATE + LATENCY (no FAILURE_CLASS for "complete")
    assert len(events) == 2

    success_events = [e for e in events if e.metric_type == OutcomeMetricType.SUCCESS_RATE]
    assert len(success_events) == 1
    assert success_events[0].value == 1.0
    assert success_events[0].metadata["termination"] == "complete"
    assert success_events[0].metadata["iterations"] == 3
    assert success_events[0].metadata["tool_calls_made"] == 5
    assert success_events[0].event_type == "invoke_iterative"

    latency_events = [e for e in events if e.metric_type == OutcomeMetricType.LATENCY_MS]
    assert len(latency_events) == 1
    assert latency_events[0].value >= 0  # mocked calls may complete in 0ms
    assert isinstance(latency_events[0].value, float)

    # Clean up extra state
    delattr(app.state, "tool_registry")
    delattr(app.state, "tool_governance")


# ---------------------------------------------------------------------------
# Test: Iterative invoke records FAILURE_CLASS for non-success termination
# ---------------------------------------------------------------------------


@patch("agent33.api.routes.agents.AgentRuntime")
def test_iterative_invoke_records_failure_class_on_max_iterations(
    mock_runtime_cls: MagicMock,
    invoke_client: TestClient,
    outcomes_service: OutcomesService,
) -> None:
    app.state.tool_registry = MagicMock()
    app.state.tool_registry.list_all.return_value = []
    app.state.tool_governance = MagicMock()

    mock_instance = MagicMock()
    mock_instance.invoke_iterative = AsyncMock(
        return_value=_make_iterative_result(termination_reason="max_iterations")
    )
    mock_runtime_cls.return_value = mock_instance

    response = invoke_client.post(
        "/v1/agents/test-agent/invoke-iterative",
        json={"inputs": {"task": "loop forever"}, "max_iterations": 3},
    )
    assert response.status_code == 200

    events = outcomes_service.list_events(tenant_id="t-abc", domain="test-agent")
    # SUCCESS_RATE + LATENCY + FAILURE_CLASS
    assert len(events) == 3

    failure_events = [e for e in events if e.metric_type == OutcomeMetricType.FAILURE_CLASS]
    assert len(failure_events) == 1
    assert failure_events[0].metadata["failure_class"] == "max_iterations"
    assert failure_events[0].value == 1.0

    delattr(app.state, "tool_registry")
    delattr(app.state, "tool_governance")


# ---------------------------------------------------------------------------
# Test: Iterative invoke records failure on RuntimeError
# ---------------------------------------------------------------------------


@patch("agent33.api.routes.agents.AgentRuntime")
def test_iterative_invoke_records_failure_on_error(
    mock_runtime_cls: MagicMock,
    invoke_client: TestClient,
    outcomes_service: OutcomesService,
) -> None:
    app.state.tool_registry = MagicMock()
    app.state.tool_registry.list_all.return_value = []
    app.state.tool_governance = MagicMock()

    mock_instance = MagicMock()
    mock_instance.invoke_iterative = AsyncMock(side_effect=RuntimeError("tool loop crashed"))
    mock_runtime_cls.return_value = mock_instance

    response = invoke_client.post(
        "/v1/agents/test-agent/invoke-iterative",
        json={"inputs": {"task": "crash"}},
    )
    assert response.status_code == 502

    events = outcomes_service.list_events(tenant_id="t-abc", domain="test-agent")
    assert len(events) == 1
    assert events[0].metric_type == OutcomeMetricType.SUCCESS_RATE
    assert events[0].value == 0.0
    assert events[0].metadata["termination"] == "runtime_error"

    delattr(app.state, "tool_registry")
    delattr(app.state, "tool_governance")


# ---------------------------------------------------------------------------
# Test: Outcome recording failure does NOT break invoke response
# ---------------------------------------------------------------------------


@patch("agent33.api.routes.agents.AgentRuntime")
def test_invoke_succeeds_even_when_outcome_recording_fails(
    mock_runtime_cls: MagicMock,
    invoke_client: TestClient,
    outcomes_service: OutcomesService,
) -> None:
    """If OutcomesService.record_event raises, the invoke response must succeed."""
    mock_instance = MagicMock()
    mock_instance.invoke = AsyncMock(return_value=_make_agent_result())
    mock_runtime_cls.return_value = mock_instance

    # Sabotage the outcomes service
    outcomes_service.record_event = MagicMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("DB write failed"),
    )

    response = invoke_client.post(
        "/v1/agents/test-agent/invoke",
        json={"inputs": {"message": "hi"}},
    )
    # The response MUST succeed even though outcome recording failed
    assert response.status_code == 200
    assert response.json()["agent"] == "test-agent"
    # Verify recording was attempted (twice: success + latency)
    assert outcomes_service.record_event.call_count == 2


# ---------------------------------------------------------------------------
# Test: OutcomesService is accessible via app.state
# ---------------------------------------------------------------------------


def test_outcomes_service_on_app_state(
    invoke_client: TestClient,
    outcomes_service: OutcomesService,
) -> None:
    """Verify the service installed by the fixture is on app.state."""
    assert hasattr(app.state, "outcomes_service")
    assert app.state.outcomes_service is outcomes_service


# ---------------------------------------------------------------------------
# Test: outcomes routes get_outcomes_service falls back to module-level
# ---------------------------------------------------------------------------


def test_outcomes_routes_get_service_fallback() -> None:
    """When app.state has no outcomes_service, fall back to module-level."""
    from agent33.api.routes.outcomes import _service, get_outcomes_service

    mock_request = MagicMock()
    mock_request.app.state = MagicMock(spec=[])  # no attributes at all

    result = get_outcomes_service(mock_request)
    assert result is _service


def test_outcomes_routes_get_service_from_app_state() -> None:
    """When app.state has outcomes_service, prefer it over module-level."""
    from agent33.api.routes.outcomes import _service, get_outcomes_service

    custom_svc = OutcomesService()
    mock_request = MagicMock()
    mock_request.app.state.outcomes_service = custom_svc

    result = get_outcomes_service(mock_request)
    assert result is custom_svc
    assert result is not _service


# ---------------------------------------------------------------------------
# Test: set_outcomes_service replaces module-level singleton
# ---------------------------------------------------------------------------


def test_set_outcomes_service() -> None:
    from agent33.api.routes import outcomes as outcomes_mod

    original = outcomes_mod._service
    replacement = OutcomesService()
    try:
        outcomes_mod.set_outcomes_service(replacement)
        assert outcomes_mod._service is replacement
    finally:
        outcomes_mod.set_outcomes_service(original)


# ---------------------------------------------------------------------------
# Test: FAILURE_CLASS metric type exists
# ---------------------------------------------------------------------------


def test_failure_class_metric_type_exists() -> None:
    assert OutcomeMetricType.FAILURE_CLASS == "failure_class"
    assert "failure_class" in [m.value for m in OutcomeMetricType]
