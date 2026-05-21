"""Tests for Phase 44 session API endpoints.

These tests exercise the actual endpoint handlers by mocking the session
service and auth layer, verifying request/response shapes, status codes,
and error handling.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent33.api.routes.sessions import router
from agent33.sessions.models import (
    OperatorSession,
    OperatorSessionStatus,
    SessionEvent,
    SessionEventType,
    TaskEntry,
)


def _make_app(
    session_service: Any,
    *,
    tenant_id: str = "test-tenant",
    scopes: list[str] | None = None,
) -> FastAPI:
    """Create a minimal FastAPI app with session routes and fake auth."""
    from starlette.middleware.base import BaseHTTPMiddleware

    app = FastAPI()
    app.include_router(router)
    app.state.operator_session_service = session_service
    effective_scopes = (
        scopes if scopes is not None else ["admin", "sessions:read", "sessions:write"]
    )

    class _FakeAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Any, call_next: Any) -> Any:
            request.state.user = MagicMock(
                tenant_id=tenant_id,
                scopes=effective_scopes,
            )
            return await call_next(request)

    app.add_middleware(_FakeAuthMiddleware)
    return app


@pytest.fixture()
def mock_service() -> MagicMock:
    """Create a mock OperatorSessionService."""
    svc = MagicMock()
    svc.start_session = AsyncMock()
    svc.end_session = AsyncMock()
    svc.resume_session = AsyncMock()
    svc.checkpoint = AsyncMock()
    svc.get_session = AsyncMock()
    svc.list_sessions = AsyncMock()
    svc.detect_incomplete_sessions = AsyncMock()
    svc.add_task = AsyncMock()
    svc.update_task = AsyncMock()
    svc.list_tasks = AsyncMock()
    svc.get_replay = AsyncMock()
    svc.get_replay_summary = AsyncMock()
    return svc


def _sample_session(
    session_id: str = "abc123",
    purpose: str = "Test",
    status: OperatorSessionStatus = OperatorSessionStatus.ACTIVE,
    tenant_id: str = "",
) -> OperatorSession:
    now = datetime.now(UTC)
    return OperatorSession(
        session_id=session_id,
        purpose=purpose,
        status=status,
        started_at=now,
        updated_at=now,
        tenant_id=tenant_id,
    )


def _sample_task(task_id: str = "t1", description: str = "Do something") -> TaskEntry:
    return TaskEntry(task_id=task_id, description=description)


class TestCreateSession:
    """Tests for POST /v1/sessions/."""

    def test_create_session_success(self, mock_service: MagicMock) -> None:
        session = _sample_session()
        mock_service.start_session.return_value = session
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.post(
            "/v1/sessions/",
            json={"purpose": "Build feature", "context": {"branch": "main"}},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["session_id"] == "abc123"
        assert data["purpose"] == "Test"
        assert data["status"] == "active"
        mock_service.start_session.assert_called_once_with(
            purpose="Build feature",
            context={"branch": "main"},
            tenant_id="",
        )

    def test_create_session_empty_body(self, mock_service: MagicMock) -> None:
        session = _sample_session(purpose="")
        mock_service.start_session.return_value = session
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.post("/v1/sessions/", json={})
        assert resp.status_code == 201

    def test_create_session_binds_non_admin_to_request_tenant(
        self, mock_service: MagicMock
    ) -> None:
        mock_service.start_session.return_value = _sample_session(tenant_id="tenant-a")
        app = _make_app(
            mock_service,
            tenant_id="tenant-a",
            scopes=["sessions:read", "sessions:write"],
        )
        client = TestClient(app)

        resp = client.post("/v1/sessions/", json={"purpose": "Scoped"})
        assert resp.status_code == 201
        mock_service.start_session.assert_called_once_with(
            purpose="Scoped",
            context={},
            tenant_id="tenant-a",
        )

    def test_create_session_rejects_tenantless_non_admin(self, mock_service: MagicMock) -> None:
        app = _make_app(mock_service, tenant_id="", scopes=["sessions:write"])
        client = TestClient(app)

        resp = client.post("/v1/sessions/", json={"purpose": "Blocked"})
        assert resp.status_code == 403
        assert "Tenant context required" in resp.json()["detail"]
        mock_service.start_session.assert_not_called()

    def test_create_session_service_unavailable(self) -> None:
        # Pass None as service -- _get_session_service will raise 503
        app = _make_app(None)
        client = TestClient(app)
        resp = client.post("/v1/sessions/", json={})
        assert resp.status_code == 503


class TestGetSession:
    """Tests for GET /v1/sessions/{session_id}."""

    def test_get_session_found(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session()
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.get("/v1/sessions/abc123")
        assert resp.status_code == 200
        assert resp.json()["session_id"] == "abc123"

    def test_get_session_not_found(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = None
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.get("/v1/sessions/nonexistent")
        assert resp.status_code == 404

    def test_get_session_forbidden_for_other_tenant(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session(tenant_id="tenant-b")
        app = _make_app(
            mock_service,
            tenant_id="tenant-a",
            scopes=["sessions:read"],
        )
        client = TestClient(app)

        resp = client.get("/v1/sessions/abc123")
        assert resp.status_code == 403
        assert "Tenant mismatch" in resp.json()["detail"]


class TestListSessions:
    """Tests for GET /v1/sessions/."""

    def test_list_sessions_default(self, mock_service: MagicMock) -> None:
        mock_service.list_sessions.return_value = [
            _sample_session("s1"),
            _sample_session("s2"),
        ]
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.get("/v1/sessions/")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_sessions_with_status_filter(self, mock_service: MagicMock) -> None:
        mock_service.list_sessions.return_value = [
            _sample_session("s1", status=OperatorSessionStatus.COMPLETED),
        ]
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.get("/v1/sessions/?status=completed")
        assert resp.status_code == 200
        mock_service.list_sessions.assert_called_once_with(
            status=OperatorSessionStatus.COMPLETED,
            limit=50,
            tenant_id=None,
        )

    def test_list_sessions_non_admin_is_tenant_scoped(self, mock_service: MagicMock) -> None:
        mock_service.list_sessions.return_value = [_sample_session("s1", tenant_id="tenant-a")]
        app = _make_app(
            mock_service,
            tenant_id="tenant-a",
            scopes=["sessions:read"],
        )
        client = TestClient(app)

        resp = client.get("/v1/sessions/")
        assert resp.status_code == 200
        mock_service.list_sessions.assert_called_once_with(
            status=None,
            limit=50,
            tenant_id="tenant-a",
        )


class TestEndSession:
    """Tests for POST /v1/sessions/{id}/end."""

    def test_end_session_completed(self, mock_service: MagicMock) -> None:
        ended = _sample_session(status=OperatorSessionStatus.COMPLETED)
        ended.ended_at = datetime.now(UTC)
        mock_service.get_session.return_value = _sample_session()
        mock_service.end_session.return_value = ended
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.post(
            "/v1/sessions/abc123/end",
            json={"status": "completed"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_end_session_not_found(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session()
        mock_service.end_session.side_effect = KeyError("not found")
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.post("/v1/sessions/nope/end", json={"status": "completed"})
        assert resp.status_code == 404

    def test_end_session_conflict(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session()
        mock_service.end_session.side_effect = ValueError("Already completed")
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.post("/v1/sessions/abc123/end", json={"status": "completed"})
        assert resp.status_code == 409

    def test_end_session_forbidden_for_other_tenant(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session(tenant_id="tenant-b")
        app = _make_app(
            mock_service,
            tenant_id="tenant-a",
            scopes=["sessions:write"],
        )
        client = TestClient(app)

        resp = client.post("/v1/sessions/abc123/end", json={"status": "completed"})
        assert resp.status_code == 403
        assert "Tenant mismatch" in resp.json()["detail"]
        mock_service.end_session.assert_not_called()


class TestResumeSession:
    """Tests for POST /v1/sessions/{id}/resume."""

    def test_resume_session_success(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session()
        mock_service.resume_session.return_value = _sample_session()
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.post("/v1/sessions/abc123/resume")
        assert resp.status_code == 200

    def test_resume_not_found(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session()
        mock_service.resume_session.side_effect = KeyError("not found")
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.post("/v1/sessions/nope/resume")
        assert resp.status_code == 404

    def test_resume_conflict(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session()
        mock_service.resume_session.side_effect = ValueError("Cannot resume active")
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.post("/v1/sessions/abc123/resume")
        assert resp.status_code == 409

    def test_resume_forbidden_for_other_tenant(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session(tenant_id="tenant-b")
        app = _make_app(
            mock_service,
            tenant_id="tenant-a",
            scopes=["sessions:write"],
        )
        client = TestClient(app)

        resp = client.post("/v1/sessions/abc123/resume")
        assert resp.status_code == 403
        assert "Tenant mismatch" in resp.json()["detail"]
        mock_service.resume_session.assert_not_called()


class TestCheckpoint:
    """Tests for POST /v1/sessions/{id}/checkpoint."""

    def test_checkpoint_success(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session()
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.post("/v1/sessions/abc123/checkpoint")
        assert resp.status_code == 200
        assert resp.json()["status"] == "checkpointed"
        mock_service.checkpoint.assert_called_once_with("abc123")

    def test_checkpoint_not_found(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session()
        mock_service.checkpoint.side_effect = KeyError("not found")
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.post("/v1/sessions/nope/checkpoint")
        assert resp.status_code == 404

    def test_checkpoint_forbidden_for_other_tenant(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session(tenant_id="tenant-b")
        app = _make_app(
            mock_service,
            tenant_id="tenant-a",
            scopes=["sessions:write"],
        )
        client = TestClient(app)

        resp = client.post("/v1/sessions/abc123/checkpoint")
        assert resp.status_code == 403
        assert "Tenant mismatch" in resp.json()["detail"]
        mock_service.checkpoint.assert_not_called()


class TestTaskEndpoints:
    """Tests for session task CRUD endpoints."""

    def test_add_task(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session()
        mock_service.add_task.return_value = _sample_task()
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.post(
            "/v1/sessions/s1/tasks/",
            json={"description": "Implement X", "metadata": {"pr": 42}},
        )
        assert resp.status_code == 201
        assert resp.json()["task_id"] == "t1"
        mock_service.add_task.assert_called_once()

    def test_add_task_session_not_found(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session()
        mock_service.add_task.side_effect = KeyError("session not found")
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.post("/v1/sessions/nope/tasks/", json={"description": "X"})
        assert resp.status_code == 404

    def test_add_task_forbidden_for_other_tenant(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session(tenant_id="tenant-b")
        app = _make_app(
            mock_service,
            tenant_id="tenant-a",
            scopes=["sessions:write"],
        )
        client = TestClient(app)

        resp = client.post("/v1/sessions/s1/tasks/", json={"description": "Implement X"})
        assert resp.status_code == 403
        assert "Tenant mismatch" in resp.json()["detail"]
        mock_service.add_task.assert_not_called()

    def test_list_tasks(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session()
        mock_service.list_tasks.return_value = [
            _sample_task("t1", "Task 1"),
            _sample_task("t2", "Task 2"),
        ]
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.get("/v1/sessions/s1/tasks/")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_tasks_forbidden_for_other_tenant(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session(tenant_id="tenant-b")
        app = _make_app(
            mock_service,
            tenant_id="tenant-a",
            scopes=["sessions:read"],
        )
        client = TestClient(app)

        resp = client.get("/v1/sessions/s1/tasks/")
        assert resp.status_code == 403
        assert "Tenant mismatch" in resp.json()["detail"]
        mock_service.list_tasks.assert_not_called()

    def test_update_task(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session()
        updated = _sample_task()
        updated.status = "done"
        updated.completed_at = datetime.now(UTC)
        mock_service.update_task.return_value = updated
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.put(
            "/v1/sessions/s1/tasks/t1",
            json={"status": "done"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "done"

    def test_update_task_not_found(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session()
        mock_service.update_task.side_effect = KeyError("task not found")
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.put("/v1/sessions/s1/tasks/nope", json={"status": "done"})
        assert resp.status_code == 404

    def test_update_task_invalid_status(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session()
        mock_service.update_task.side_effect = ValueError("Invalid status")
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.put("/v1/sessions/s1/tasks/t1", json={"status": "done"})
        assert resp.status_code == 422

    def test_update_task_forbidden_for_other_tenant(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session(tenant_id="tenant-b")
        app = _make_app(
            mock_service,
            tenant_id="tenant-a",
            scopes=["sessions:write"],
        )
        client = TestClient(app)

        resp = client.put("/v1/sessions/s1/tasks/t1", json={"status": "done"})
        assert resp.status_code == 403
        assert "Tenant mismatch" in resp.json()["detail"]
        mock_service.update_task.assert_not_called()


class TestReplayEndpoints:
    """Tests for replay event endpoints."""

    def test_get_replay(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session()
        events = [
            SessionEvent(
                event_id="e1",
                event_type=SessionEventType.SESSION_STARTED,
                session_id="s1",
                data={"purpose": "test"},
            ),
            SessionEvent(
                event_id="e2",
                event_type=SessionEventType.TOOL_EXECUTED,
                session_id="s1",
                data={"tool": "shell"},
            ),
        ]
        mock_service.get_replay.return_value = events
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.get("/v1/sessions/s1/replay/?offset=0&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["event_type"] == "session.started"
        assert data[1]["event_type"] == "tool.executed"

    def test_get_replay_forbidden_for_other_tenant(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session(tenant_id="tenant-b")
        app = _make_app(
            mock_service,
            tenant_id="tenant-a",
            scopes=["sessions:read"],
        )
        client = TestClient(app)

        resp = client.get("/v1/sessions/s1/replay/?offset=0&limit=10")
        assert resp.status_code == 403
        assert "Tenant mismatch" in resp.json()["detail"]
        mock_service.get_replay.assert_not_called()

    def test_get_replay_summary(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session()
        mock_service.get_replay_summary.return_value = {
            "total_events": 15,
            "by_type": {"session.started": 1, "tool.executed": 10, "checkpoint": 4},
            "duration_seconds": 120.5,
            "first_event_at": "2026-03-10T10:00:00+00:00",
            "last_event_at": "2026-03-10T10:02:00+00:00",
        }
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.get("/v1/sessions/s1/replay/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 15
        assert data["by_type"]["tool.executed"] == 10
        assert data["duration_seconds"] == 120.5

    def test_get_replay_summary_forbidden_for_other_tenant(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _sample_session(tenant_id="tenant-b")
        app = _make_app(
            mock_service,
            tenant_id="tenant-a",
            scopes=["sessions:read"],
        )
        client = TestClient(app)

        resp = client.get("/v1/sessions/s1/replay/summary")
        assert resp.status_code == 403
        assert "Tenant mismatch" in resp.json()["detail"]
        mock_service.get_replay_summary.assert_not_called()


class TestIncompleteEndpoint:
    """Tests for GET /v1/sessions/incomplete."""

    def test_list_incomplete_sessions(self, mock_service: MagicMock) -> None:
        crashed = _sample_session("c1", status=OperatorSessionStatus.CRASHED)
        suspended = _sample_session("s1", status=OperatorSessionStatus.SUSPENDED)
        mock_service.detect_incomplete_sessions.return_value = [crashed]
        mock_service.list_sessions.return_value = [suspended]
        app = _make_app(mock_service)
        client = TestClient(app)

        resp = client.get("/v1/sessions/incomplete")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        statuses = {d["status"] for d in data}
        assert statuses == {"crashed", "suspended"}

    def test_list_incomplete_sessions_non_admin_is_tenant_scoped(
        self, mock_service: MagicMock
    ) -> None:
        tenant_session = _sample_session(
            "c1",
            status=OperatorSessionStatus.CRASHED,
            tenant_id="tenant-a",
        )
        mock_service.detect_incomplete_sessions.return_value = [tenant_session]
        mock_service.list_sessions.return_value = []
        app = _make_app(
            mock_service,
            tenant_id="tenant-a",
            scopes=["sessions:read"],
        )
        client = TestClient(app)

        resp = client.get("/v1/sessions/incomplete")
        assert resp.status_code == 200
        mock_service.detect_incomplete_sessions.assert_called_once_with(tenant_id="tenant-a")
        mock_service.list_sessions.assert_called_once_with(
            status=OperatorSessionStatus.SUSPENDED,
            limit=50,
            tenant_id="tenant-a",
        )
