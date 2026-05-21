"""Tests for stateless HITL approval tokens (Phase 45)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import jwt
import pytest

from agent33.security.approval_tokens import (
    ApprovalTokenError,
    ApprovalTokenManager,
    ApprovalTokenPayload,
)
from agent33.services.orchestration_state import OrchestrationStateStore
from agent33.tools.approvals import ApprovalReason, ApprovalStatus, ToolApprovalRequest

if TYPE_CHECKING:
    from pathlib import Path


def _make_approved_request(
    tool_name: str = "shell",
    operation: str = "",
    requested_by: str = "user1",
    reviewed_by: str = "admin1",
    tenant_id: str = "tenant-001",
) -> ToolApprovalRequest:
    """Create a mock approved ToolApprovalRequest."""
    req = ToolApprovalRequest(
        reason=ApprovalReason.TOOL_POLICY_ASK,
        tool_name=tool_name,
        operation=operation,
        requested_by=requested_by,
        tenant_id=tenant_id,
        status=ApprovalStatus.APPROVED,
        reviewed_by=reviewed_by,
    )
    return req


class TestApprovalTokenIssuance:
    """Token issuance: valid approvals produce signed JWTs."""

    def test_issue_returns_jwt_string(self) -> None:
        mgr = ApprovalTokenManager(secret="test-secret")
        approval = _make_approved_request()
        token = mgr.issue(approval, arguments={"command": "ls"})
        assert isinstance(token, str)
        # Should be decodable
        data = jwt.decode(token, "test-secret", algorithms=["HS256"])
        assert data["typ"] == "a33_approval"
        assert data["tool"] == "shell"

    def test_issue_includes_arg_hash(self) -> None:
        mgr = ApprovalTokenManager(secret="test-secret")
        approval = _make_approved_request()
        token = mgr.issue(approval, arguments={"command": "rm /tmp/safe"})
        data = jwt.decode(token, "test-secret", algorithms=["HS256"])
        assert data["arg_hash"].startswith("sha256:")

    def test_issue_uses_custom_ttl(self) -> None:
        now = time.time()
        clock_time = now
        mgr = ApprovalTokenManager(
            secret="test-secret",
            default_ttl_seconds=300,
            clock=lambda: clock_time,
        )
        approval = _make_approved_request()
        token = mgr.issue(approval, arguments={}, ttl_seconds=60)
        data = jwt.decode(
            token,
            "test-secret",
            algorithms=["HS256"],
            options={"verify_exp": False},
        )
        assert data["exp"] == int(now) + 60

    def test_issue_rejects_non_approved(self) -> None:
        mgr = ApprovalTokenManager(secret="test-secret")
        pending = ToolApprovalRequest(
            reason=ApprovalReason.TOOL_POLICY_ASK,
            tool_name="shell",
            status=ApprovalStatus.PENDING,
        )
        with pytest.raises(ApprovalTokenError, match="Cannot issue token"):
            mgr.issue(pending, arguments={})

    def test_issue_with_empty_arguments(self) -> None:
        mgr = ApprovalTokenManager(secret="test-secret")
        approval = _make_approved_request()
        token = mgr.issue(approval, arguments={})
        assert isinstance(token, str)

    def test_issue_includes_tenant_and_sub(self) -> None:
        mgr = ApprovalTokenManager(secret="test-secret")
        approval = _make_approved_request(reviewed_by="admin@org.com", tenant_id="t-42")
        token = mgr.issue(approval, arguments={})
        data = jwt.decode(token, "test-secret", algorithms=["HS256"])
        assert data["sub"] == "admin@org.com"
        assert data["tenant_id"] == "t-42"
        assert data["jti"] == approval.approval_id

    def test_issue_with_operation(self) -> None:
        mgr = ApprovalTokenManager(secret="test-secret")
        approval = _make_approved_request(tool_name="file_ops", operation="write")
        token = mgr.issue(approval, arguments={"path": "/tmp/f.txt"})
        data = jwt.decode(token, "test-secret", algorithms=["HS256"])
        assert data["op"] == "write"

    def test_issue_uses_configured_default_one_time(self) -> None:
        mgr = ApprovalTokenManager(secret="test-secret", default_one_time=False)
        approval = _make_approved_request()
        token = mgr.issue(approval, arguments={})
        data = jwt.decode(token, "test-secret", algorithms=["HS256"])
        assert data["one_time"] is False


class TestApprovalTokenValidation:
    """Token validation: scope enforcement, arg hash, expiry, one-time."""

    def test_valid_token_succeeds(self) -> None:
        mgr = ApprovalTokenManager(secret="test-secret")
        approval = _make_approved_request(tool_name="shell")
        args = {"command": "ls"}
        token = mgr.issue(approval, arguments=args)
        payload = mgr.validate(token, "shell", args, tenant_id="tenant-001")
        assert isinstance(payload, ApprovalTokenPayload)
        assert payload.tool == "shell"
        assert payload.jti == approval.approval_id

    def test_wrong_tool_name_rejected(self) -> None:
        mgr = ApprovalTokenManager(secret="test-secret")
        approval = _make_approved_request(tool_name="shell")
        args = {"command": "ls"}
        token = mgr.issue(approval, arguments=args)
        with pytest.raises(ApprovalTokenError, match="tool mismatch"):
            mgr.validate(token, "file_ops", args)

    def test_tampered_arguments_rejected(self) -> None:
        mgr = ApprovalTokenManager(secret="test-secret")
        approval = _make_approved_request(tool_name="shell")
        original_args = {"command": "rm /tmp/safe"}
        token = mgr.issue(approval, arguments=original_args)
        tampered_args = {"command": "rm /"}
        with pytest.raises(ApprovalTokenError, match="argument hash mismatch"):
            mgr.validate(token, "shell", tampered_args)

    def test_expired_token_rejected(self) -> None:
        # Use a TTL of 1 second so the token expires almost immediately
        now = time.time()
        mgr = ApprovalTokenManager(
            secret="test-secret",
            default_ttl_seconds=0,  # 0 second TTL = already expired
            clock=lambda: now - 2,  # issue 2 seconds in the past
        )
        approval = _make_approved_request()
        args = {"command": "ls"}
        token = mgr.issue(approval, arguments=args)
        # Token was issued with exp = (now - 2) + 0 = now - 2, already expired
        mgr._clock = lambda: now
        with pytest.raises(ApprovalTokenError, match="expired"):
            mgr.validate(token, "shell", args)

    def test_tenant_mismatch_rejected(self) -> None:
        mgr = ApprovalTokenManager(secret="test-secret")
        approval = _make_approved_request(tenant_id="tenant-A")
        args = {"command": "ls"}
        token = mgr.issue(approval, arguments=args)
        with pytest.raises(ApprovalTokenError, match="tenant mismatch"):
            mgr.validate(token, "shell", args, tenant_id="tenant-B")

    def test_one_time_token_consumed_on_first_use(self) -> None:
        mgr = ApprovalTokenManager(secret="test-secret")
        approval = _make_approved_request()
        args = {"command": "ls"}
        token = mgr.issue(approval, arguments=args, one_time=True)
        # First use succeeds
        mgr.validate(token, "shell", args, tenant_id="tenant-001")
        # Second use fails
        with pytest.raises(ApprovalTokenError, match="already been consumed"):
            mgr.validate(token, "shell", args, tenant_id="tenant-001")

    def test_non_one_time_token_reusable(self) -> None:
        mgr = ApprovalTokenManager(secret="test-secret")
        approval = _make_approved_request()
        args = {"command": "ls"}
        token = mgr.issue(approval, arguments=args, one_time=False)
        # Both uses succeed
        mgr.validate(token, "shell", args, tenant_id="tenant-001")
        mgr.validate(token, "shell", args, tenant_id="tenant-001")

    def test_validate_without_consuming_allows_explicit_consume_later(self) -> None:
        mgr = ApprovalTokenManager(secret="test-secret")
        approval = _make_approved_request()
        args = {"command": "ls"}
        token = mgr.issue(approval, arguments=args, one_time=True)

        payload = mgr.validate(token, "shell", args, tenant_id="tenant-001", consume=False)
        assert payload.jti == approval.approval_id

        assert mgr.consume(payload.jti) is True
        with pytest.raises(ApprovalTokenError, match="already been consumed"):
            mgr.validate(token, "shell", args, tenant_id="tenant-001")

    def test_wrong_secret_rejected(self) -> None:
        mgr = ApprovalTokenManager(secret="correct-secret")
        approval = _make_approved_request()
        token = mgr.issue(approval, arguments={})
        bad_mgr = ApprovalTokenManager(secret="wrong-secret")
        with pytest.raises(ApprovalTokenError, match="Invalid approval token"):
            bad_mgr.validate(token, "shell", {})

    def test_non_approval_jwt_rejected(self) -> None:
        """A regular auth JWT should not pass as an approval token."""
        secret = "test-secret"
        mgr = ApprovalTokenManager(secret=secret)
        # Create a regular JWT (no typ: a33_approval)
        regular_jwt = jwt.encode(
            {
                "sub": "user",
                "exp": int(time.time()) + 300,
                "typ": "access",
                "tool": "shell",
                "jti": "abc",
                "iat": int(time.time()),
            },
            secret,
            algorithm="HS256",
        )
        with pytest.raises(ApprovalTokenError, match="wrong typ"):
            mgr.validate(regular_jwt, "shell", {})


class TestApprovalTokenRevocation:
    """Token revocation: emergency revoke by JTI."""

    def test_revoke_token(self) -> None:
        mgr = ApprovalTokenManager(secret="test-secret")
        approval = _make_approved_request()
        args = {"command": "ls"}
        token = mgr.issue(approval, arguments=args)
        # Revoke by JTI
        assert mgr.revoke(approval.approval_id) is True
        # Validation should fail
        with pytest.raises(ApprovalTokenError, match="revoked"):
            mgr.validate(token, "shell", args)

    def test_revoke_idempotent(self) -> None:
        mgr = ApprovalTokenManager(secret="test-secret")
        assert mgr.revoke("APR-xyz") is True
        assert mgr.revoke("APR-xyz") is False  # already revoked

    def test_is_revoked(self) -> None:
        mgr = ApprovalTokenManager(secret="test-secret")
        assert mgr.is_revoked("APR-abc") is False
        mgr.revoke("APR-abc")
        assert mgr.is_revoked("APR-abc") is True

    def test_consumed_tokens_persist_across_manager_instances(self, tmp_path: Path) -> None:
        store = OrchestrationStateStore(str(tmp_path / "approval-state.json"))
        approval = _make_approved_request()
        args = {"command": "ls"}

        mgr = ApprovalTokenManager(secret="test-secret", state_store=store)
        token = mgr.issue(approval, arguments=args)
        mgr.validate(token, "shell", args, tenant_id="tenant-001")

        reloaded = ApprovalTokenManager(secret="test-secret", state_store=store)
        with pytest.raises(ApprovalTokenError, match="already been consumed"):
            reloaded.validate(token, "shell", args, tenant_id="tenant-001")

    def test_revoked_tokens_persist_across_manager_instances(self, tmp_path: Path) -> None:
        store = OrchestrationStateStore(str(tmp_path / "approval-state.json"))
        approval = _make_approved_request()
        args = {"command": "ls"}

        mgr = ApprovalTokenManager(secret="test-secret", state_store=store)
        token = mgr.issue(approval, arguments=args)
        mgr.revoke(approval.approval_id)

        reloaded = ApprovalTokenManager(secret="test-secret", state_store=store)
        with pytest.raises(ApprovalTokenError, match="revoked"):
            reloaded.validate(token, "shell", args, tenant_id="tenant-001")


class TestApprovalTokenPruning:
    """Pruning: consumed/revoked sets are bounded."""

    def test_consumed_entries_pruned_after_double_ttl(self) -> None:
        now = time.time()
        clock_time = now

        def clock() -> float:
            return clock_time

        mgr = ApprovalTokenManager(
            secret="test-secret",
            default_ttl_seconds=60,
            clock=clock,
        )
        approval = _make_approved_request()
        token = mgr.issue(approval, arguments={})
        mgr.validate(token, "shell", {}, tenant_id="tenant-001")
        assert approval.approval_id in mgr._consumed

        # Advance clock past 2x TTL (120s)
        clock_time = now + 121.0
        mgr._prune_consumed()
        assert approval.approval_id not in mgr._consumed

    def test_revoked_entries_pruned_after_double_ttl(self) -> None:
        now = time.time()
        clock_time = now

        def clock() -> float:
            return clock_time

        mgr = ApprovalTokenManager(
            secret="test-secret",
            default_ttl_seconds=60,
            clock=clock,
        )
        mgr.revoke("APR-old")
        assert "APR-old" in mgr._revoked

        clock_time = now + 121.0
        mgr._prune_revoked()
        assert "APR-old" not in mgr._revoked
