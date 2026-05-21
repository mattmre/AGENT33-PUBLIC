"""Tests for W18-F1: ExecutionReplay wiring."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent33.main import app
from agent33.observability.replay import ExecutionReplay
from agent33.security.auth import create_access_token
from agent33.workflows.definition import WorkflowDefinition
from agent33.workflows.executor import WorkflowExecutor


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = create_access_token("test-user", scopes=["admin"])
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# ReplayStep dataclass fields
# ---------------------------------------------------------------------------


def test_replay_step_has_extended_fields() -> None:
    """ReplayStep must carry action_type, elapsed_ms, status, error."""
    replay = ExecutionReplay()
    replay.record_step(
        "run-1",
        "step-a",
        {"x": 1},
        action_type="invoke_agent",
        elapsed_ms=42.5,
        status="success",
    )
    steps = replay.get_steps("run-1")
    assert len(steps) == 1
    s = steps[0]
    assert s.action_type == "invoke_agent"
    assert s.elapsed_ms == 42.5
    assert s.status == "success"
    assert s.error is None


def test_replay_step_captures_failure() -> None:
    replay = ExecutionReplay()
    replay.record_step(
        "run-2",
        "step-b",
        {},
        action_type="run_command",
        elapsed_ms=5.0,
        status="failed",
        error="timeout",
    )
    steps = replay.get_steps("run-2")
    assert steps[0].status == "failed"
    assert steps[0].error == "timeout"


# ---------------------------------------------------------------------------
# WorkflowExecutor wires replay on success
# ---------------------------------------------------------------------------


MINIMAL_WORKFLOW = {
    "name": "test-wf",
    "version": "1.0.0",
    "description": "test",
    "steps": [
        {
            "id": "s1",
            "action": "transform",
            "inputs": {"data": {"value": 1}},
        }
    ],
}


async def test_executor_records_success_step_in_replay() -> None:
    replay = ExecutionReplay()
    defn = WorkflowDefinition.model_validate(MINIMAL_WORKFLOW)
    executor = WorkflowExecutor(defn, replay=replay)
    result = await executor.execute({})
    assert result.status.value == "success"
    steps = replay.get_steps("test-wf")
    assert len(steps) == 1
    assert steps[0].step_id == "s1"
    assert steps[0].status == "success"
    assert steps[0].action_type == "transform"
    assert steps[0].elapsed_ms >= 0


async def test_executor_records_failed_step_in_replay() -> None:
    replay = ExecutionReplay()
    defn = WorkflowDefinition.model_validate(
        {
            "name": "fail-wf",
            "version": "1.0.0",
            "description": "test",
            "steps": [
                {
                    "id": "bad",
                    "action": "validate",
                    "inputs": {"schema": {"type": "object"}, "data": None},
                }
            ],
        }
    )
    executor = WorkflowExecutor(defn, replay=replay)
    await executor.execute({})
    steps = replay.get_steps("fail-wf")
    # We get at least one step recorded regardless of success/failure
    assert len(steps) >= 1
    assert steps[0].step_id == "bad"


# ---------------------------------------------------------------------------
# GET /v1/workflows/{run_id}/replay returns steps
# ---------------------------------------------------------------------------


def test_replay_route_returns_empty_for_unknown_run(auth_headers: dict[str, str]) -> None:
    client = TestClient(app, headers=auth_headers)
    resp = client.get("/v1/workflows/nonexistent-run/replay")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "nonexistent-run"
    assert data["steps"] == []


def test_replay_route_returns_steps_after_execution(auth_headers: dict[str, str]) -> None:
    """After seeding app.state.execution_replay, the route returns those steps."""
    replay = ExecutionReplay()
    replay.record_step(
        "seeded-run",
        "step-x",
        {"val": 99},
        action_type="transform",
        elapsed_ms=10.0,
        status="success",
    )
    original = getattr(app.state, "execution_replay", None)
    app.state.execution_replay = replay
    try:
        client = TestClient(app, headers=auth_headers)
        resp = client.get("/v1/workflows/seeded-run/replay")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "seeded-run"
        assert len(data["steps"]) == 1
        step = data["steps"][0]
        assert step["step_id"] == "step-x"
        assert step["action_type"] == "transform"
        assert step["status"] == "success"
        assert step["elapsed_ms"] == 10.0
        assert step["state_snapshot"] == {"val": 99}
    finally:
        app.state.execution_replay = original
