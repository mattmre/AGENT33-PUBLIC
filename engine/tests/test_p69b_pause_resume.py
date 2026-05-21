"""Tests for P69b human-in-the-loop tool approval pause/resume.

Covers 6 service-level test cases and 4 route-level test cases.
"""

from __future__ import annotations

import contextlib
import os
import time
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agent33.autonomy.p69b_models import (
    PausedInvocationStatus,
    ToolApprovalDenied,
    ToolApprovalInvalidState,
    ToolApprovalNonceReplay,
    compute_nonce,
)
from agent33.autonomy.p69b_service import P69bService
from agent33.main import app
from agent33.security.auth import create_access_token

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT = "tenant-p69b-test"
_INVOCATION = "inv-00000000-0000-0000-0000-000000000001"
_TOOL = "shell_exec"
_SECRET = "test-secret-key"


def _make_nonce(run_id: str = _INVOCATION, tool_name: str = _TOOL) -> str:
    return compute_nonce(run_id, tool_name, _SECRET, timestamp=time.time())


def _auth_headers(scopes: list[str] | None = None) -> dict[str, str]:
    token = create_access_token(
        "p69b-test-user",
        scopes=scopes or ["invocations:write", "invocations:read"],
        tenant_id=_TENANT,
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------


class TestP69bServicePause:
    """TC-1: Pause stores PausedInvocation in service with correct fields."""

    def test_pause_creates_record_with_correct_fields(self) -> None:
        svc = P69bService(timeout_seconds=300)
        nonce = _make_nonce()
        record = svc.pause(
            invocation_id=_INVOCATION,
            tenant_id=_TENANT,
            tool_name=_TOOL,
            tool_input={"command": "ls -la"},
            nonce=nonce,
        )

        assert record.invocation_id == _INVOCATION
        assert record.tenant_id == _TENANT
        assert record.tool_name == _TOOL
        assert record.tool_input == {"command": "ls -la"}
        assert record.nonce == nonce
        assert record.status == PausedInvocationStatus.PENDING
        assert record.resolved_at is None
        assert record.approved_by is None
        # expires_at should be approx 300 seconds from now
        delta = (record.expires_at - datetime.now(UTC)).total_seconds()
        assert 295 < delta < 305, f"unexpected expires_at delta: {delta}"

    def test_pause_record_is_retrievable(self) -> None:
        svc = P69bService(timeout_seconds=300)
        nonce = _make_nonce()
        record = svc.pause(
            invocation_id=_INVOCATION,
            tenant_id=_TENANT,
            tool_name=_TOOL,
            tool_input={},
            nonce=nonce,
        )
        pending = svc.get_pending(_INVOCATION)
        assert len(pending) == 1
        assert pending[0].id == record.id


class TestP69bServiceResumeApprove:
    """TC-2: Resume with approved=True sets status to APPROVED and resolved_at."""

    def test_resume_approve_sets_status_and_resolved_at(self) -> None:
        svc = P69bService(timeout_seconds=300)
        nonce = _make_nonce()
        record = svc.pause(
            invocation_id=_INVOCATION,
            tenant_id=_TENANT,
            tool_name=_TOOL,
            tool_input={},
            nonce=nonce,
        )
        updated = svc.resume(record.id, approved=True, approved_by="operator@example.com")

        assert updated.status == PausedInvocationStatus.APPROVED
        assert updated.resolved_at is not None
        assert updated.approved_by == "operator@example.com"
        # Confirm the store is updated
        pending = svc.get_pending(_INVOCATION)
        assert len(pending) == 0

    def test_resume_approve_clears_pending_list(self) -> None:
        svc = P69bService(timeout_seconds=300)
        nonce = _make_nonce()
        record = svc.pause(
            invocation_id=_INVOCATION,
            tenant_id=_TENANT,
            tool_name=_TOOL,
            tool_input={},
            nonce=nonce,
        )
        svc.resume(record.id, approved=True)
        assert svc.get_pending(_INVOCATION) == []


class TestP69bServiceResumeDeny:
    """TC-3: Resume with approved=False sets status to DENIED."""

    def test_resume_deny_sets_denied_status(self) -> None:
        svc = P69bService(timeout_seconds=300)
        nonce = _make_nonce()
        record = svc.pause(
            invocation_id=_INVOCATION,
            tenant_id=_TENANT,
            tool_name=_TOOL,
            tool_input={},
            nonce=nonce,
        )
        updated = svc.resume(record.id, approved=False, approved_by="admin@example.com")

        assert updated.status == PausedInvocationStatus.DENIED
        assert updated.resolved_at is not None
        assert updated.approved_by == "admin@example.com"

    def test_resume_deny_removes_from_pending(self) -> None:
        svc = P69bService(timeout_seconds=300)
        nonce = _make_nonce()
        record = svc.pause(
            invocation_id=_INVOCATION,
            tenant_id=_TENANT,
            tool_name=_TOOL,
            tool_input={},
            nonce=nonce,
        )
        svc.resume(record.id, approved=False)
        assert svc.get_pending(_INVOCATION) == []

    def test_resume_non_pending_raises_invalid_state(self) -> None:
        svc = P69bService(timeout_seconds=300)
        nonce = _make_nonce()
        record = svc.pause(
            invocation_id=_INVOCATION,
            tenant_id=_TENANT,
            tool_name=_TOOL,
            tool_input={},
            nonce=nonce,
        )
        svc.resume(record.id, approved=False)
        # Second resume must fail
        with pytest.raises(ToolApprovalInvalidState):
            svc.resume(record.id, approved=True)


class TestP69bNonceReplay:
    """TC-4: HMAC nonce prevents replay (nonce already consumed)."""

    def test_nonce_replay_raises_on_second_pause(self) -> None:
        svc = P69bService(timeout_seconds=300)
        nonce = _make_nonce()

        # First pause succeeds
        record = svc.pause(
            invocation_id=_INVOCATION,
            tenant_id=_TENANT,
            tool_name=_TOOL,
            tool_input={},
            nonce=nonce,
        )

        # Mark record as CONSUMED (simulating what happens after a successful resume)
        consumed = record.model_copy(update={"status": PausedInvocationStatus.CONSUMED})
        svc._store[record.id] = consumed

        # Second pause with same nonce must be rejected
        with pytest.raises(ToolApprovalNonceReplay):
            svc.pause(
                invocation_id=_INVOCATION,
                tenant_id=_TENANT,
                tool_name=_TOOL,
                tool_input={},
                nonce=nonce,
            )

    def test_different_nonce_does_not_replay(self) -> None:
        svc = P69bService(timeout_seconds=300)
        nonce1 = compute_nonce(_INVOCATION, _TOOL, _SECRET, timestamp=time.time())
        nonce2 = compute_nonce(_INVOCATION, "other_tool", _SECRET, timestamp=time.time())

        record = svc.pause(
            invocation_id=_INVOCATION,
            tenant_id=_TENANT,
            tool_name=_TOOL,
            tool_input={},
            nonce=nonce1,
        )
        consumed = record.model_copy(update={"status": PausedInvocationStatus.CONSUMED})
        svc._store[record.id] = consumed

        # A different nonce must not trigger replay protection
        record2 = svc.pause(
            invocation_id=_INVOCATION,
            tenant_id=_TENANT,
            tool_name="other_tool",
            tool_input={},
            nonce=nonce2,
        )
        assert record2.status == PausedInvocationStatus.PENDING


class TestP69bHeadlessMode:
    """TC-5: Headless deny mode auto-denies; headless approve mode auto-approves."""

    def test_headless_mode_returns_deny(self) -> None:
        svc = P69bService()
        with patch.dict(os.environ, {"AGENT33_HEADLESS_TOOL_APPROVAL": "deny"}):
            assert svc.headless_mode() == "deny"

    def test_headless_mode_returns_approve(self) -> None:
        svc = P69bService()
        with patch.dict(os.environ, {"AGENT33_HEADLESS_TOOL_APPROVAL": "approve"}):
            assert svc.headless_mode() == "approve"

    def test_headless_mode_returns_none_when_unset(self) -> None:
        svc = P69bService()
        env = {k: v for k, v in os.environ.items() if k != "AGENT33_HEADLESS_TOOL_APPROVAL"}
        with patch.dict(os.environ, env, clear=True):
            assert svc.headless_mode() is None

    def test_headless_mode_returns_none_for_invalid_value(self) -> None:
        svc = P69bService()
        with patch.dict(os.environ, {"AGENT33_HEADLESS_TOOL_APPROVAL": "interactive"}):
            assert svc.headless_mode() is None

    def test_headless_deny_caller_raises_tool_approval_denied(self) -> None:
        """Callers that check headless_mode() == 'deny' should raise ToolApprovalDenied."""
        svc = P69bService()
        with patch.dict(os.environ, {"AGENT33_HEADLESS_TOOL_APPROVAL": "deny"}):
            mode = svc.headless_mode()
            with pytest.raises(ToolApprovalDenied):
                if mode == "deny":
                    raise ToolApprovalDenied("Headless deny: tool call auto-denied")

    def test_headless_approve_caller_does_not_raise(self) -> None:
        """Callers that check headless_mode() == 'approve' should not raise."""
        svc = P69bService()
        with patch.dict(os.environ, {"AGENT33_HEADLESS_TOOL_APPROVAL": "approve"}):
            mode = svc.headless_mode()
            # In approve mode, no exception is raised — call proceeds
            assert mode == "approve"


class TestP69bFeatureFlag:
    """TC-6: Feature flag controls P69b enablement."""

    def test_is_enabled_false_by_default(self) -> None:
        svc = P69bService()
        env = {k: v for k, v in os.environ.items() if k != "P69B_TOOL_APPROVAL_ENABLED"}
        with patch.dict(os.environ, env, clear=True):
            assert svc.is_enabled() is False

    def test_is_enabled_false_when_explicitly_false(self) -> None:
        svc = P69bService()
        with patch.dict(os.environ, {"P69B_TOOL_APPROVAL_ENABLED": "false"}):
            assert svc.is_enabled() is False

    def test_is_enabled_true_when_env_set(self) -> None:
        svc = P69bService()
        with patch.dict(os.environ, {"P69B_TOOL_APPROVAL_ENABLED": "true"}):
            assert svc.is_enabled() is True

    def test_is_enabled_case_insensitive(self) -> None:
        svc = P69bService()
        with patch.dict(os.environ, {"P69B_TOOL_APPROVAL_ENABLED": "TRUE"}):
            assert svc.is_enabled() is True

    def test_kill_switch_file_overrides_env(self) -> None:
        """Kill switch file disables P69b even when env var says enabled."""
        svc = P69bService()
        # Patch pathlib.Path.exists at the pathlib module level so that the
        # import-inside-function call in is_enabled() sees the mock.
        from pathlib import Path as _Path

        with (
            patch.object(_Path, "exists", return_value=True),
            patch.dict(os.environ, {"P69B_TOOL_APPROVAL_ENABLED": "true"}),
        ):
            # Even though the flag is set to "true", the kill switch takes precedence.
            assert svc.is_enabled() is False


# ---------------------------------------------------------------------------
# Route-level tests (using TestClient + app.state fixture injection)
# ---------------------------------------------------------------------------


@pytest.fixture()
def enabled_svc() -> P69bService:
    """Return a P69bService that acts as enabled (P69B_TOOL_APPROVAL_ENABLED=true)."""
    svc = P69bService(timeout_seconds=300)
    with patch.dict(os.environ, {"P69B_TOOL_APPROVAL_ENABLED": "true"}):
        yield svc


@pytest.fixture()
def p69b_client(enabled_svc: P69bService) -> Any:
    """TestClient with p69b_service installed on app.state."""
    original = getattr(app.state, "p69b_service", None)
    app.state.p69b_service = enabled_svc
    with patch.dict(os.environ, {"P69B_TOOL_APPROVAL_ENABLED": "true"}):
        client = TestClient(app, raise_server_exceptions=True)
        yield client, enabled_svc
    if original is not None:
        app.state.p69b_service = original
    else:
        with contextlib.suppress(AttributeError):
            del app.state.p69b_service


@pytest.fixture()
def p69b_disabled_client() -> Any:
    """TestClient with p69b_service installed but feature disabled."""
    svc = P69bService(timeout_seconds=300)
    original = getattr(app.state, "p69b_service", None)
    app.state.p69b_service = svc
    env_without_flag = {k: v for k, v in os.environ.items() if k != "P69B_TOOL_APPROVAL_ENABLED"}
    with patch.dict(os.environ, env_without_flag, clear=True):
        client = TestClient(app, raise_server_exceptions=True)
        yield client
    if original is not None:
        app.state.p69b_service = original
    else:
        with contextlib.suppress(AttributeError):
            del app.state.p69b_service


class TestP69bRoutes:
    """Route-level tests for all 4 P69b endpoints."""

    def test_pause_returns_200_with_approval_id(self, p69b_client: Any) -> None:
        """POST /v1/invocations/{id}/pause returns 200 and an approval_id."""
        client, svc = p69b_client
        nonce = _make_nonce()
        with patch.dict(os.environ, {"P69B_TOOL_APPROVAL_ENABLED": "true"}):
            response = client.post(
                f"/v1/invocations/{_INVOCATION}/pause",
                json={
                    "tool_name": _TOOL,
                    "tool_input": {"command": "echo hello"},
                    "nonce": nonce,
                },
                headers=_auth_headers(),
            )
        assert response.status_code == 200, response.text
        data = response.json()
        assert "approval_id" in data
        assert data["status"] == "PENDING"
        assert "expires_at" in data
        assert data["nonce"] == nonce

    def test_resume_returns_200_after_pause(self, p69b_client: Any) -> None:
        """POST /v1/invocations/{id}/resume returns 200 after a successful pause."""
        client, svc = p69b_client
        nonce = _make_nonce()
        with patch.dict(os.environ, {"P69B_TOOL_APPROVAL_ENABLED": "true"}):
            # Create a pause record directly via service so we control the nonce
            svc.pause(
                invocation_id=_INVOCATION,
                tenant_id=_TENANT,
                tool_name=_TOOL,
                tool_input={},
                nonce=nonce,
            )
            response = client.post(
                f"/v1/invocations/{_INVOCATION}/resume",
                json={
                    "approved": True,
                    "nonce": nonce,
                    "reason": "Approved in test.",
                },
                headers=_auth_headers(),
            )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["invocation_id"] == _INVOCATION
        assert data["status"] == "RUNNING"
        assert "resumed_at" in data

    def test_pending_approvals_returns_list(self, p69b_client: Any) -> None:
        """GET /v1/invocations/{id}/pending-approvals returns the list of pending items."""
        client, svc = p69b_client
        nonce = _make_nonce()
        with patch.dict(os.environ, {"P69B_TOOL_APPROVAL_ENABLED": "true"}):
            svc.pause(
                invocation_id=_INVOCATION,
                tenant_id=_TENANT,
                tool_name=_TOOL,
                tool_input={"command": "ls"},
                nonce=nonce,
            )
            response = client.get(
                f"/v1/invocations/{_INVOCATION}/pending-approvals",
                headers=_auth_headers(),
            )
        assert response.status_code == 200, response.text
        data = response.json()
        assert "approvals" in data
        assert len(data["approvals"]) == 1
        item = data["approvals"][0]
        assert item["tool_name"] == _TOOL
        assert item["status"] == "PENDING"
        assert "approval_id" in item
        assert "expires_at" in item

    def test_pause_returns_503_when_feature_disabled(self, p69b_disabled_client: Any) -> None:
        """POST /v1/invocations/{id}/pause returns 503 when feature flag is off."""
        client = p69b_disabled_client
        nonce = _make_nonce()
        response = client.post(
            f"/v1/invocations/{_INVOCATION}/pause",
            json={
                "tool_name": _TOOL,
                "tool_input": {},
                "nonce": nonce,
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 503, response.text
        data = response.json()
        # detail contains the error envelope
        detail = data.get("detail", data)
        if isinstance(detail, dict):
            assert detail.get("error") == "ToolApprovalFeatureDisabled"
        else:
            # FastAPI may return detail as a string — the key check is the 503 status
            assert "ToolApprovalFeatureDisabled" in str(detail)

    def test_global_pending_approvals_returns_paginated_list(self, p69b_client: Any) -> None:
        """GET /v1/approvals/pending returns paginated results for the tenant."""
        client, svc = p69b_client
        nonce1 = compute_nonce(_INVOCATION, "tool_a", _SECRET, timestamp=time.time())
        nonce2 = compute_nonce(_INVOCATION, "tool_b", _SECRET, timestamp=time.time() + 1)
        with patch.dict(os.environ, {"P69B_TOOL_APPROVAL_ENABLED": "true"}):
            svc.pause(
                invocation_id=_INVOCATION,
                tenant_id=_TENANT,
                tool_name="tool_a",
                tool_input={},
                nonce=nonce1,
            )
            svc.pause(
                invocation_id=_INVOCATION,
                tenant_id=_TENANT,
                tool_name="tool_b",
                tool_input={},
                nonce=nonce2,
            )
            response = client.get(
                "/v1/approvals/pending",
                params={"page": 1, "page_size": 10},
                headers=_auth_headers(),
            )
        assert response.status_code == 200, response.text
        data = response.json()
        assert "approvals" in data
        assert data["total"] >= 2
        assert data["page"] == 1
        assert "page_size" in data
        for item in data["approvals"]:
            assert "invocation_id" in item
            assert "approval_id" in item

    def test_resume_deny_returns_failed_status(self, p69b_client: Any) -> None:
        """POST /resume with approved=False returns status FAILED."""
        client, svc = p69b_client
        nonce = _make_nonce()
        with patch.dict(os.environ, {"P69B_TOOL_APPROVAL_ENABLED": "true"}):
            svc.pause(
                invocation_id=_INVOCATION,
                tenant_id=_TENANT,
                tool_name=_TOOL,
                tool_input={},
                nonce=nonce,
            )
            response = client.post(
                f"/v1/invocations/{_INVOCATION}/resume",
                json={
                    "approved": False,
                    "nonce": nonce,
                    "reason": "Denied by operator.",
                },
                headers=_auth_headers(),
            )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "FAILED"

    def test_resume_nonce_mismatch_returns_409(self, p69b_client: Any) -> None:
        """POST /resume with wrong nonce returns 409 Conflict."""
        client, svc = p69b_client
        correct_nonce = _make_nonce()
        wrong_nonce = "a" * 64  # 64 hex chars but wrong value
        with patch.dict(os.environ, {"P69B_TOOL_APPROVAL_ENABLED": "true"}):
            svc.pause(
                invocation_id=_INVOCATION,
                tenant_id=_TENANT,
                tool_name=_TOOL,
                tool_input={},
                nonce=correct_nonce,
            )
            response = client.post(
                f"/v1/invocations/{_INVOCATION}/resume",
                json={
                    "approved": True,
                    "nonce": wrong_nonce,
                },
                headers=_auth_headers(),
            )
        assert response.status_code == 409, response.text

    def test_pause_nonce_replay_returns_409(self, p69b_client: Any) -> None:
        """POST /pause with a consumed nonce returns 409 Conflict."""
        client, svc = p69b_client
        nonce = _make_nonce()
        with patch.dict(os.environ, {"P69B_TOOL_APPROVAL_ENABLED": "true"}):
            # Create and consume a record with that nonce
            record = svc.pause(
                invocation_id=_INVOCATION,
                tenant_id=_TENANT,
                tool_name=_TOOL,
                tool_input={},
                nonce=nonce,
            )
            consumed = record.model_copy(update={"status": PausedInvocationStatus.CONSUMED})
            svc._store[record.id] = consumed

            # Now try to pause again with the same nonce via the API
            response = client.post(
                f"/v1/invocations/{_INVOCATION}/pause",
                json={"tool_name": _TOOL, "tool_input": {}, "nonce": nonce},
                headers=_auth_headers(),
            )
        assert response.status_code == 409, response.text


# ---------------------------------------------------------------------------
# Compute nonce utility tests
# ---------------------------------------------------------------------------


class TestComputeNonce:
    """Verify the HMAC nonce formula produces consistent, bounded output."""

    def test_nonce_is_64_hex_chars(self) -> None:
        nonce = compute_nonce("run-1", "shell_exec", "secret", timestamp=1744300800.0)
        assert len(nonce) == 64
        assert all(c in "0123456789abcdef" for c in nonce)

    def test_same_window_produces_same_nonce(self) -> None:
        # Timestamps 0 and 29 fall in the same 30-second window (window 0)
        n1 = compute_nonce("run-1", "shell", "secret", timestamp=0.0)
        n2 = compute_nonce("run-1", "shell", "secret", timestamp=29.0)
        assert n1 == n2

    def test_different_windows_produce_different_nonces(self) -> None:
        n1 = compute_nonce("run-1", "shell", "secret", timestamp=0.0)
        n2 = compute_nonce("run-1", "shell", "secret", timestamp=30.0)
        assert n1 != n2

    def test_different_tools_produce_different_nonces(self) -> None:
        n1 = compute_nonce("run-1", "tool_a", "secret", timestamp=0.0)
        n2 = compute_nonce("run-1", "tool_b", "secret", timestamp=0.0)
        assert n1 != n2

    def test_different_run_ids_produce_different_nonces(self) -> None:
        n1 = compute_nonce("run-1", "shell", "secret", timestamp=0.0)
        n2 = compute_nonce("run-2", "shell", "secret", timestamp=0.0)
        assert n1 != n2

    def test_different_secrets_produce_different_nonces(self) -> None:
        n1 = compute_nonce("run-1", "shell", "secret-a", timestamp=0.0)
        n2 = compute_nonce("run-1", "shell", "secret-b", timestamp=0.0)
        assert n1 != n2
