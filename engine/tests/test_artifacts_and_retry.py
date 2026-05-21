"""Tests for W18-F6: artifacts download + per-step retry routes."""

from __future__ import annotations

import io
import json
import zipfile
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from agent33.main import app
from agent33.security.auth import create_access_token


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = create_access_token("test-user", scopes=["admin"])
    return {"Authorization": f"Bearer {token}"}


def _make_replay_step(step_id: str, status: str = "success") -> MagicMock:
    s = MagicMock()
    s.step_id = step_id
    s.action_type = "transform"
    s.status = status
    s.elapsed_ms = 12.5
    s.error = None if status == "success" else "step failed"
    s.state_snapshot = {"value": 1}
    return s


def _mock_replay(steps: list[MagicMock]) -> MagicMock:
    replay = MagicMock()
    replay.get_steps = MagicMock(return_value=steps)
    return replay


# ---------------------------------------------------------------------------
# GET /v1/workflows/{run_id}/artifacts
# ---------------------------------------------------------------------------


def test_artifacts_returns_zip_with_step_files(auth_headers: dict[str, str]) -> None:
    """Each recorded step must produce a {step_id}.json inside the zip."""
    steps = [_make_replay_step("s1"), _make_replay_step("s2")]
    original = getattr(app.state, "execution_replay", sentinel := object())
    app.state.execution_replay = _mock_replay(steps)
    try:
        client = TestClient(app, headers=auth_headers)
        resp = client.get("/v1/workflows/run-123/artifacts")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        cd = resp.headers.get("content-disposition", "")
        assert "run-123_artifacts.zip" in cd

        buf = io.BytesIO(resp.content)
        with zipfile.ZipFile(buf) as zf:
            names = set(zf.namelist())
            assert "s1.json" in names
            assert "s2.json" in names
            s1 = json.loads(zf.read("s1.json"))
            assert s1["step_id"] == "s1"
            assert s1["status"] == "success"
    finally:
        if original is sentinel:
            del app.state.execution_replay
        else:
            app.state.execution_replay = original


def test_artifacts_returns_404_when_no_replay_service(
    auth_headers: dict[str, str],
) -> None:
    """Without a replay singleton on app.state, the route must return 404."""
    original = getattr(app.state, "execution_replay", sentinel := object())
    app.state.execution_replay = None
    try:
        client = TestClient(app, headers=auth_headers)
        resp = client.get("/v1/workflows/run-empty/artifacts")
        assert resp.status_code == 404
        data = resp.json()
        assert "Replay service" in data["detail"]
    finally:
        if original is sentinel:
            del app.state.execution_replay
        else:
            app.state.execution_replay = original


def test_artifacts_returns_404_when_run_has_no_recorded_steps(
    auth_headers: dict[str, str],
) -> None:
    """When replay is present but has no steps for the run, the route returns 404."""
    original = getattr(app.state, "execution_replay", sentinel := object())
    app.state.execution_replay = _mock_replay([])  # replay exists, but no steps for this run
    try:
        client = TestClient(app, headers=auth_headers)
        resp = client.get("/v1/workflows/run-no-steps/artifacts")
        assert resp.status_code == 404
        data = resp.json()
        assert "run-no-steps" in data["detail"]
    finally:
        if original is sentinel:
            del app.state.execution_replay
        else:
            app.state.execution_replay = original


def test_artifacts_requires_auth() -> None:
    """Unauthenticated requests must receive 401."""
    client = TestClient(app)
    resp = client.get("/v1/workflows/run-xyz/artifacts")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /v1/workflows/{run_id}/steps/{step_id}/retry
# ---------------------------------------------------------------------------


async def test_step_retry_returns_step_result(auth_headers: dict[str, str]) -> None:
    """A valid retry request must execute the step and return a step result."""
    client = TestClient(app, headers=auth_headers)
    resp = client.post(
        "/v1/workflows/run-123/steps/my-step/retry",
        json={"action": "transform", "inputs": {"data": {"x": 1}}, "state": {}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "run-123"
    assert data["step_id"] == "my-step"
    assert data["status"] in {"success", "failed"}
    assert "outputs" in data
    assert "error" in data
    assert "duration_ms" in data


async def test_step_retry_rejects_unknown_action(auth_headers: dict[str, str]) -> None:
    """Unknown action values must yield 422."""
    client = TestClient(app, headers=auth_headers)
    resp = client.post(
        "/v1/workflows/run-123/steps/s1/retry",
        json={"action": "not_a_real_action"},
    )
    assert resp.status_code == 422


def test_step_retry_requires_auth() -> None:
    """Unauthenticated step retry requests must receive 401."""
    client = TestClient(app)
    resp = client.post(
        "/v1/workflows/run-123/steps/s1/retry",
        json={"action": "transform"},
    )
    assert resp.status_code == 401
