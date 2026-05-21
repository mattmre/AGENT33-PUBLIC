"""Tests for step_retry route: replay and checkpoint_manager wiring.

Verifies that the per-step retry route (POST /v1/workflows/{run_id}/steps/{step_id}/retry)
correctly reads execution_replay and checkpoint_manager from app.state and threads
them through to WorkflowExecutor, reflecting their presence in the response body
and forwarding them to the executor instance.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agent33.main import app
from agent33.security.auth import create_access_token


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = create_access_token("test-user", scopes=["admin"])
    return {"Authorization": f"Bearer {token}"}


def _make_replay() -> MagicMock:
    """Build a minimal ExecutionReplay mock."""
    replay = MagicMock()
    replay.record_step = MagicMock()
    replay.get_steps = MagicMock(return_value=[])
    return replay


def _make_checkpoint_manager() -> MagicMock:
    """Build a minimal CheckpointManager mock."""
    mgr = MagicMock()
    mgr.save_checkpoint = AsyncMock(return_value="ckpt-1")
    mgr.load_checkpoint = AsyncMock(return_value=None)
    return mgr


# ---------------------------------------------------------------------------
# replay_enabled / checkpoint_enabled fields in response
# ---------------------------------------------------------------------------


def test_retry_response_shows_replay_enabled_false_when_not_wired(
    auth_headers: dict[str, str],
) -> None:
    """When execution_replay is absent from app.state, replay_enabled must be False."""
    original = getattr(app.state, "execution_replay", sentinel := object())
    app.state.execution_replay = None
    try:
        client = TestClient(app, headers=auth_headers)
        resp = client.post(
            "/v1/workflows/run-100/steps/s1/retry",
            json={"action": "transform", "inputs": {"data": {"v": 0}}, "state": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["replay_enabled"] is False
    finally:
        if original is sentinel:
            if hasattr(app.state, "execution_replay"):
                del app.state.execution_replay
        else:
            app.state.execution_replay = original


def test_retry_response_shows_replay_enabled_true_when_wired(
    auth_headers: dict[str, str],
) -> None:
    """When execution_replay is present on app.state, replay_enabled must be True."""
    original = getattr(app.state, "execution_replay", sentinel := object())
    app.state.execution_replay = _make_replay()
    try:
        client = TestClient(app, headers=auth_headers)
        resp = client.post(
            "/v1/workflows/run-101/steps/s1/retry",
            json={"action": "transform", "inputs": {"data": {"v": 1}}, "state": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["replay_enabled"] is True
    finally:
        if original is sentinel:
            if hasattr(app.state, "execution_replay"):
                del app.state.execution_replay
        else:
            app.state.execution_replay = original


def test_retry_response_shows_checkpoint_enabled_false_when_not_wired(
    auth_headers: dict[str, str],
) -> None:
    """When checkpoint_manager is absent from app.state, checkpoint_enabled is False."""
    original = getattr(app.state, "checkpoint_manager", sentinel := object())
    app.state.checkpoint_manager = None
    try:
        client = TestClient(app, headers=auth_headers)
        resp = client.post(
            "/v1/workflows/run-102/steps/s2/retry",
            json={"action": "transform", "inputs": {"data": {"v": 2}}, "state": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["checkpoint_enabled"] is False
    finally:
        if original is sentinel:
            if hasattr(app.state, "checkpoint_manager"):
                del app.state.checkpoint_manager
        else:
            app.state.checkpoint_manager = original


def test_retry_response_shows_checkpoint_enabled_true_when_wired(
    auth_headers: dict[str, str],
) -> None:
    """When checkpoint_manager is present on app.state, checkpoint_enabled is True."""
    original = getattr(app.state, "checkpoint_manager", sentinel := object())
    app.state.checkpoint_manager = _make_checkpoint_manager()
    try:
        client = TestClient(app, headers=auth_headers)
        resp = client.post(
            "/v1/workflows/run-103/steps/s2/retry",
            json={"action": "transform", "inputs": {"data": {"v": 3}}, "state": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["checkpoint_enabled"] is True
    finally:
        if original is sentinel:
            if hasattr(app.state, "checkpoint_manager"):
                del app.state.checkpoint_manager
        else:
            app.state.checkpoint_manager = original


# ---------------------------------------------------------------------------
# WorkflowExecutor receives replay and checkpoint_manager from app.state
# ---------------------------------------------------------------------------


async def test_executor_receives_replay_from_app_state(
    auth_headers: dict[str, str],
) -> None:
    """WorkflowExecutor must be constructed with the replay from app.state."""
    replay = _make_replay()
    original = getattr(app.state, "execution_replay", sentinel := object())
    app.state.execution_replay = replay

    captured: list[MagicMock | None] = []

    from agent33.workflows.executor import WorkflowExecutor

    _real_init = WorkflowExecutor.__init__

    def _spy_init(self, *args, **kwargs):  # noqa: ANN001
        captured.append(kwargs.get("replay"))
        _real_init(self, *args, **kwargs)

    try:
        with patch.object(WorkflowExecutor, "__init__", _spy_init):
            client = TestClient(app, headers=auth_headers)
            resp = client.post(
                "/v1/workflows/run-200/steps/s1/retry",
                json={"action": "transform", "inputs": {"data": {}}, "state": {}},
            )
        assert resp.status_code == 200
        assert len(captured) == 1
        assert captured[0] is replay, (
            "WorkflowExecutor was not constructed with the replay from app.state"
        )
    finally:
        if original is sentinel:
            if hasattr(app.state, "execution_replay"):
                del app.state.execution_replay
        else:
            app.state.execution_replay = original


async def test_executor_receives_checkpoint_manager_from_app_state(
    auth_headers: dict[str, str],
) -> None:
    """WorkflowExecutor must be constructed with the checkpoint_manager from app.state."""
    mgr = _make_checkpoint_manager()
    original = getattr(app.state, "checkpoint_manager", sentinel := object())
    app.state.checkpoint_manager = mgr

    captured: list[MagicMock | None] = []

    from agent33.workflows.executor import WorkflowExecutor

    _real_init = WorkflowExecutor.__init__

    def _spy_init(self, *args, **kwargs):  # noqa: ANN001
        captured.append(kwargs.get("checkpoint_manager"))
        _real_init(self, *args, **kwargs)

    try:
        with patch.object(WorkflowExecutor, "__init__", _spy_init):
            client = TestClient(app, headers=auth_headers)
            resp = client.post(
                "/v1/workflows/run-201/steps/s1/retry",
                json={"action": "transform", "inputs": {"data": {}}, "state": {}},
            )
        assert resp.status_code == 200
        assert len(captured) == 1
        assert captured[0] is mgr, (
            "WorkflowExecutor was not constructed with the checkpoint_manager from app.state"
        )
    finally:
        if original is sentinel:
            if hasattr(app.state, "checkpoint_manager"):
                del app.state.checkpoint_manager
        else:
            app.state.checkpoint_manager = original


# ---------------------------------------------------------------------------
# retry_run_id and __retry_metadata are correctly set in the response
# ---------------------------------------------------------------------------


def test_retry_response_includes_retry_run_id(auth_headers: dict[str, str]) -> None:
    """Response must contain retry_run_id that embeds the parent run_id."""
    client = TestClient(app, headers=auth_headers)
    resp = client.post(
        "/v1/workflows/parent-run-xyz/steps/step-abc/retry",
        json={"action": "transform", "inputs": {"data": {}}, "state": {}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "retry_run_id" in data
    # retry_run_id must contain both the parent run_id and step_id fragments
    assert "parent-run-xyz" in data["retry_run_id"]
    assert "step-abc" in data["retry_run_id"]


def test_retry_response_resume_from_checkpoint_is_false(auth_headers: dict[str, str]) -> None:
    """Step retry must not resume from checkpoint (it is a fresh retry of one step)."""
    mgr = _make_checkpoint_manager()
    original = getattr(app.state, "checkpoint_manager", sentinel := object())
    app.state.checkpoint_manager = mgr
    try:
        client = TestClient(app, headers=auth_headers)
        resp = client.post(
            "/v1/workflows/run-300/steps/s1/retry",
            json={"action": "transform", "inputs": {"data": {}}, "state": {}},
        )
        assert resp.status_code == 200
        # load_checkpoint should NOT have been called — resume_from_checkpoint=False
        mgr.load_checkpoint.assert_not_awaited()
    finally:
        if original is sentinel:
            if hasattr(app.state, "checkpoint_manager"):
                del app.state.checkpoint_manager
        else:
            app.state.checkpoint_manager = original
