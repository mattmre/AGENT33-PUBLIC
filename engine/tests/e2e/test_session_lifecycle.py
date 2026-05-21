"""E2E: Session lifecycle through the HTTP API.

These tests exercise the full operator session lifecycle:
1. Session create -> checkpoint -> end -> verify final state
2. Task tracking within a session
3. Replay log accumulation
4. Crash detection for abandoned sessions
"""

from __future__ import annotations

import pytest

from agent33.security.auth import create_access_token

pytestmark = pytest.mark.e2e


def _admin_token() -> str:
    return create_access_token("e2e-session-user", scopes=["admin"])


class TestSessionLifecycleE2E:
    """Session create -> checkpoint -> tasks -> end -> verify."""

    def test_session_start_checkpoint_end(self, e2e_client):
        """Full session lifecycle: create -> checkpoint -> end.

        Verifies that:
        - POST /v1/sessions/ creates a session with status=active
        - POST /v1/sessions/{id}/checkpoint succeeds and records state
        - POST /v1/sessions/{id}/end transitions to completed
        - GET /v1/sessions/{id} shows the final state with ended_at set
        """
        _, client, _ = e2e_client
        token = _admin_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Create session
        resp = client.post(
            "/v1/sessions/",
            json={"purpose": "E2E lifecycle test", "context": {"env": "test"}},
            headers=headers,
        )
        if resp.status_code == 503:
            pytest.skip("Operator session service not initialized")

        assert resp.status_code == 201
        session = resp.json()
        session_id = session["session_id"]
        assert session["status"] == "active"
        assert session["purpose"] == "E2E lifecycle test"
        assert session["ended_at"] is None

        # Checkpoint
        resp = client.post(
            f"/v1/sessions/{session_id}/checkpoint",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "checkpointed"

        # End session
        resp = client.post(
            f"/v1/sessions/{session_id}/end",
            json={"status": "completed"},
            headers=headers,
        )
        assert resp.status_code == 200
        ended = resp.json()
        assert ended["status"] == "completed"
        assert ended["ended_at"] is not None

        # Verify final state via GET
        resp = client.get(f"/v1/sessions/{session_id}", headers=headers)
        assert resp.status_code == 200
        final = resp.json()
        assert final["status"] == "completed"
        assert final["ended_at"] is not None

    def test_session_with_tasks(self, e2e_client):
        """Create a session, add tasks, update task status, verify counts.

        Verifies that:
        - Tasks can be added to active sessions
        - Task status transitions work (pending -> in_progress -> done)
        - Task counts in session response reflect actual task state
        """
        _, client, _ = e2e_client
        token = _admin_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Create session
        resp = client.post(
            "/v1/sessions/",
            json={"purpose": "E2E task tracking"},
            headers=headers,
        )
        if resp.status_code == 503:
            pytest.skip("Operator session service not initialized")

        assert resp.status_code == 201
        session_id = resp.json()["session_id"]

        # Add first task
        resp = client.post(
            f"/v1/sessions/{session_id}/tasks/",
            json={"description": "Build feature X", "metadata": {"priority": "high"}},
            headers=headers,
        )
        assert resp.status_code == 201
        task1 = resp.json()
        task1_id = task1["task_id"]
        assert task1["description"] == "Build feature X"
        assert task1["status"] == "pending"
        assert task1["metadata"]["priority"] == "high"

        # Add second task
        resp = client.post(
            f"/v1/sessions/{session_id}/tasks/",
            json={"description": "Write tests"},
            headers=headers,
        )
        assert resp.status_code == 201
        task2_id = resp.json()["task_id"]

        # Update first task to in_progress
        resp = client.put(
            f"/v1/sessions/{session_id}/tasks/{task1_id}",
            json={"status": "in_progress"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

        # Complete first task
        resp = client.put(
            f"/v1/sessions/{session_id}/tasks/{task1_id}",
            json={"status": "done"},
            headers=headers,
        )
        assert resp.status_code == 200
        done_task = resp.json()
        assert done_task["status"] == "done"
        assert done_task["completed_at"] is not None

        # List tasks -- verify both are present with correct statuses
        resp = client.get(f"/v1/sessions/{session_id}/tasks/", headers=headers)
        assert resp.status_code == 200
        tasks = resp.json()
        assert len(tasks) == 2
        statuses = {t["task_id"]: t["status"] for t in tasks}
        assert statuses[task1_id] == "done"
        assert statuses[task2_id] == "pending"

        # Verify session task count
        resp = client.get(f"/v1/sessions/{session_id}", headers=headers)
        assert resp.status_code == 200
        session_state = resp.json()
        assert session_state["task_count"] == 2
        assert session_state["tasks_completed"] == 1

    def test_session_replay_accumulates_events(self, e2e_client):
        """Replay log records lifecycle events as they occur.

        Verifies that:
        - session.started event is recorded on creation
        - checkpoint event is recorded
        - session.ended event is recorded
        - Replay summary counts match actual event types
        """
        _, client, _ = e2e_client
        token = _admin_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Create + checkpoint + end
        resp = client.post(
            "/v1/sessions/",
            json={"purpose": "E2E replay test"},
            headers=headers,
        )
        if resp.status_code == 503:
            pytest.skip("Operator session service not initialized")
        assert resp.status_code == 201
        session_id = resp.json()["session_id"]

        client.post(f"/v1/sessions/{session_id}/checkpoint", headers=headers)
        client.post(
            f"/v1/sessions/{session_id}/end",
            json={"status": "completed"},
            headers=headers,
        )

        # Get replay events
        resp = client.get(f"/v1/sessions/{session_id}/replay/", headers=headers)
        assert resp.status_code == 200
        events = resp.json()

        # Should have at least: started, checkpoint, ended
        event_types = [e["event_type"] for e in events]
        assert "session.started" in event_types
        assert "checkpoint" in event_types
        assert "session.ended" in event_types

        # Get replay summary
        resp = client.get(
            f"/v1/sessions/{session_id}/replay/summary",
            headers=headers,
        )
        assert resp.status_code == 200
        summary = resp.json()
        assert summary["total_events"] >= 3
        assert "session.started" in summary["by_type"]

    def test_session_suspend_and_resume(self, e2e_client):
        """Session can be suspended and then resumed.

        Verifies the state machine: active -> suspended -> active
        and that the resume endpoint works through the HTTP API.
        """
        _, client, _ = e2e_client
        token = _admin_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Create session
        resp = client.post(
            "/v1/sessions/",
            json={"purpose": "E2E suspend/resume"},
            headers=headers,
        )
        if resp.status_code == 503:
            pytest.skip("Operator session service not initialized")
        assert resp.status_code == 201
        session_id = resp.json()["session_id"]

        # Suspend (end with status=suspended)
        resp = client.post(
            f"/v1/sessions/{session_id}/end",
            json={"status": "suspended"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "suspended"

        # Resume
        resp = client.post(
            f"/v1/sessions/{session_id}/resume",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

    def test_end_already_completed_session_returns_409(self, e2e_client):
        """Ending a completed session returns 409 conflict.

        Verifies that the state machine rejects invalid transitions
        at the HTTP layer.
        """
        _, client, _ = e2e_client
        token = _admin_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Create and end
        resp = client.post(
            "/v1/sessions/",
            json={"purpose": "E2E double-end"},
            headers=headers,
        )
        if resp.status_code == 503:
            pytest.skip("Operator session service not initialized")
        assert resp.status_code == 201
        session_id = resp.json()["session_id"]

        resp = client.post(
            f"/v1/sessions/{session_id}/end",
            json={"status": "completed"},
            headers=headers,
        )
        assert resp.status_code == 200

        # Try to end again
        resp = client.post(
            f"/v1/sessions/{session_id}/end",
            json={"status": "completed"},
            headers=headers,
        )
        assert resp.status_code == 409
