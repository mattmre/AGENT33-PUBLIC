"""Tests for W18-F2: CheckpointManager wiring into WorkflowExecutor."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes import workflows
from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.workflows.definition import WorkflowDefinition
from agent33.workflows.executor import WorkflowExecutor
from agent33.workflows.run_archive import WorkflowRunArchiveService


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = create_access_token("test-user", scopes=["admin"])
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def reset_route_state() -> None:
    workflows.reset_workflow_state()
    workflows.set_workflow_run_archive_service(None)
    original_checkpoint = getattr(app.state, "checkpoint_manager", sentinel := object())
    original_archive = getattr(app.state, "workflow_run_archive_service", sentinel)
    yield
    workflows.reset_workflow_state()
    workflows.set_workflow_run_archive_service(None)
    if original_checkpoint is sentinel:
        if hasattr(app.state, "checkpoint_manager"):
            del app.state.checkpoint_manager
    else:
        app.state.checkpoint_manager = original_checkpoint
    if original_archive is sentinel:
        if hasattr(app.state, "workflow_run_archive_service"):
            del app.state.workflow_run_archive_service
    else:
        app.state.workflow_run_archive_service = original_archive


def _mock_checkpoint_manager(
    stored: list[dict[str, Any]] | None = None,
    loaded: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a CheckpointManager mock that accumulates save_checkpoint calls."""
    mgr = MagicMock()
    records: list[dict[str, Any]] = stored if stored is not None else []

    async def _save(workflow_id: str, step_id: str, state: dict[str, Any]) -> str:
        records.append({"workflow_id": workflow_id, "step_id": step_id, "state": state})
        return f"ckpt-{len(records)}"

    async def _list(workflow_id: str | None = None) -> list[dict[str, Any]]:
        if workflow_id is None:
            return list(records)
        return [r for r in records if r["workflow_id"] == workflow_id]

    mgr.save_checkpoint = AsyncMock(side_effect=_save)
    mgr.load_checkpoint = AsyncMock(return_value=loaded)
    mgr.list_checkpoints = AsyncMock(side_effect=_list)
    mgr._records = records
    return mgr


MINIMAL_WORKFLOW = {
    "name": "ckpt-wf",
    "version": "1.0.0",
    "description": "checkpoint test",
    "steps": [
        {
            "id": "s1",
            "action": "transform",
            "inputs": {"data": {"value": 1}},
        }
    ],
}


# ---------------------------------------------------------------------------
# Executor calls save_checkpoint on step success
# ---------------------------------------------------------------------------


async def test_executor_saves_checkpoint_on_success() -> None:
    """WorkflowExecutor must call checkpoint_manager.save_checkpoint after each
    successful step with (run_id, step_id, state)."""
    mgr = _mock_checkpoint_manager()
    defn = WorkflowDefinition.model_validate(MINIMAL_WORKFLOW)
    executor = WorkflowExecutor(defn, checkpoint_manager=mgr)
    result = await executor.execute({})

    assert result.status.value == "success"
    mgr.save_checkpoint.assert_awaited_once()
    call_args = mgr.save_checkpoint.call_args
    assert call_args.args[0] == "ckpt-wf"  # workflow_id / run_id
    assert call_args.args[1] == "s1"  # step_id
    assert call_args.args[2]["s1"] == {"result": {"value": 1}}
    assert call_args.args[2]["__workflow_checkpoint"]["completed_steps"] == ["s1"]


async def test_executor_does_not_call_checkpoint_when_none() -> None:
    """No checkpoint call when checkpoint_manager is None (default)."""
    defn = WorkflowDefinition.model_validate(MINIMAL_WORKFLOW)
    executor = WorkflowExecutor(defn)  # no checkpoint_manager
    result = await executor.execute({})
    assert result.status.value == "success"  # execution still succeeds


async def test_executor_does_not_checkpoint_on_step_failure() -> None:
    """save_checkpoint must NOT be called for a failed step."""
    mgr = _mock_checkpoint_manager()
    fail_workflow = {
        "name": "fail-ckpt-wf",
        "version": "1.0.0",
        "description": "fail test",
        "steps": [
            {
                "id": "bad",
                "action": "validate",
                "inputs": {"schema": {"type": "object"}, "data": None},
            }
        ],
    }
    defn = WorkflowDefinition.model_validate(fail_workflow)
    executor = WorkflowExecutor(defn, checkpoint_manager=mgr)
    await executor.execute({})
    # save_checkpoint should not have been called for the failed step
    mgr.save_checkpoint.assert_not_awaited()


async def test_executor_resumes_from_checkpoint_without_rerunning_completed_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint resume must restore state and execute only incomplete steps."""
    workflow = {
        "name": "resume-wf",
        "version": "1.0.0",
        "steps": [
            {"id": "s1", "action": "transform", "inputs": {"data": {"value": 1}}},
            {"id": "s2", "action": "transform", "inputs": {"expression": "s1.result.value"}},
        ],
    }
    loaded = {
        "s1": {"result": {"value": 7}},
        "__workflow_checkpoint": {"completed_steps": ["s1"], "last_step_id": "s1"},
    }
    mgr = _mock_checkpoint_manager(loaded=loaded)
    calls: list[str] = []

    async def _fake_dispatch(self, step, resolved_inputs, state, dry_run):  # noqa: ANN001, ARG001
        calls.append(step.id)
        return {"result": resolved_inputs.get("expression", step.id)}

    monkeypatch.setattr(WorkflowExecutor, "_dispatch_action", _fake_dispatch)

    executor = WorkflowExecutor(
        WorkflowDefinition.model_validate(workflow),
        checkpoint_manager=mgr,
        run_id="resume-run",
    )
    result = await executor.execute({})

    assert calls == ["s2"]
    assert result.status.value == "success"
    assert result.steps_executed == ["s2"]
    assert [step.status for step in result.step_results] == ["skipped", "success"]
    assert result.outputs["result"] == 7
    mgr.save_checkpoint.assert_awaited_once()
    saved_state = mgr.save_checkpoint.call_args.args[2]
    assert saved_state["s1"] == {"result": {"value": 7}}
    assert saved_state["s2"] == {"result": 7}
    assert saved_state["__workflow_checkpoint"]["completed_steps"] == ["s1", "s2"]


# ---------------------------------------------------------------------------
# GET /v1/workflows/{run_id}/checkpoints route
# ---------------------------------------------------------------------------


def test_checkpoint_route_returns_empty_when_no_manager(
    auth_headers: dict[str, str],
) -> None:
    """Without a checkpoint_manager on app.state, route returns empty list."""
    original = getattr(app.state, "checkpoint_manager", sentinel := object())
    app.state.checkpoint_manager = None
    try:
        client = TestClient(app, headers=auth_headers)
        resp = client.get("/v1/workflows/run-xyz/checkpoints")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "run-xyz"
        assert data["checkpoints"] == []
    finally:
        if original is sentinel:
            del app.state.checkpoint_manager
        else:
            app.state.checkpoint_manager = original


def test_checkpoint_route_returns_records(auth_headers: dict[str, str]) -> None:
    """Route delegates to checkpoint_manager.list_checkpoints(workflow_id=run_id)."""
    seeded = [
        {"id": "ckpt-1", "workflow_id": "run-abc", "step_id": "s1", "created_at": "2025-01-01"},
    ]
    mgr = _mock_checkpoint_manager(stored=seeded)
    original = getattr(app.state, "checkpoint_manager", sentinel := object())
    app.state.checkpoint_manager = mgr
    try:
        client = TestClient(app, headers=auth_headers)
        resp = client.get("/v1/workflows/run-abc/checkpoints")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "run-abc"
        mgr.list_checkpoints.assert_awaited_once_with(workflow_id="run-abc")
        assert len(data["checkpoints"]) == 1
        assert data["checkpoints"][0]["step_id"] == "s1"
    finally:
        if original is sentinel:
            del app.state.checkpoint_manager
        else:
            app.state.checkpoint_manager = original


def test_resume_route_reexecutes_only_incomplete_steps(
    tmp_path,
    auth_headers: dict[str, str],
) -> None:
    """POST /v1/workflows/{run_id}/resume must use checkpoint state and original inputs."""
    workflow = WorkflowDefinition.model_validate(
        {
            "name": "resume-route-wf",
            "version": "1.0.0",
            "steps": [
                {"id": "s1", "action": "transform", "inputs": {"data": {"value": 1}}},
                {"id": "s2", "action": "transform", "inputs": {"expression": "s1.result.value"}},
            ],
        }
    )
    workflows.get_workflow_registry()[workflow.name] = workflow

    archive = WorkflowRunArchiveService(tmp_path / "workflow-runs")
    workflows.set_workflow_run_archive_service(archive)
    app.state.workflow_run_archive_service = archive
    archive.start_run(
        "resume-route-run",
        workflow.name,
        metadata={"requested_inputs": {"request_id": "original"}},
        tenant_id="",
    )
    archive.record_result(
        "resume-route-run",
        {
            "status": "partial",
            "outputs": {},
            "step_results": [
                {
                    "step_id": "s1",
                    "status": "success",
                    "outputs": {
                        "artifacts": [
                            {
                                "data": "original artifact",
                                "mime_type": "text/plain",
                                "metadata": {"filename": "original.txt"},
                            }
                        ]
                    },
                }
            ],
        },
    )
    original_summary = archive.load_summary("resume-route-run")
    assert original_summary is not None
    assert original_summary["artifact_count"] == 1

    loaded = {
        "request_id": "original",
        "s1": {"result": {"value": 9}},
        "__workflow_checkpoint": {"completed_steps": ["s1"], "last_step_id": "s1"},
    }
    mgr = _mock_checkpoint_manager(loaded=loaded)
    app.state.checkpoint_manager = mgr

    client = TestClient(app, headers=auth_headers)
    response = client.post("/v1/workflows/resume-route-run/resume")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == "resume-route-run"
    assert payload["workflow_name"] == workflow.name
    assert payload["resumed_from_checkpoint"] is True
    assert payload["steps_executed"] == ["s2"]
    assert [step["status"] for step in payload["step_results"]] == ["skipped", "success"]
    assert payload["outputs"]["result"] == 9
    resumed_detail = archive.load_detail("resume-route-run")
    assert resumed_detail is not None
    assert resumed_detail["run"]["started_at"] == original_summary["started_at"]
    assert [artifact["name"] for artifact in resumed_detail["artifacts"]] == ["original.txt"]
    assert (
        archive.read_artifact("resume-route-run", "artifacts/original.txt") == "original artifact"
    )
    assert mgr.load_checkpoint.await_count == 2
    mgr.save_checkpoint.assert_awaited_once()
