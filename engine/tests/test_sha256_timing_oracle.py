"""Regression tests for SHA-256 timing oracle fixes (POST-1.4).

Verifies that both packs/loader.py and security/approval_tokens.py use
hmac.compare_digest() instead of bare == / != for digest comparisons.
"""

from __future__ import annotations

import hashlib
import inspect
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agent33.tools.approvals import ApprovalReason, ApprovalStatus, ToolApprovalRequest


def _make_approved_request(
    tool_name: str = "shell",
    operation: str = "",
    requested_by: str = "user1",
    reviewed_by: str = "admin1",
    tenant_id: str = "tenant-001",
) -> ToolApprovalRequest:
    """Create a mock approved ToolApprovalRequest."""
    return ToolApprovalRequest(
        reason=ApprovalReason.TOOL_POLICY_ASK,
        tool_name=tool_name,
        operation=operation,
        requested_by=requested_by,
        tenant_id=tenant_id,
        status=ApprovalStatus.APPROVED,
        reviewed_by=reviewed_by,
    )


class TestPackLoaderHmacDigest:
    """packs/loader.py must use hmac.compare_digest for checksum comparison."""

    def test_valid_checksum_passes(self, tmp_path: Path) -> None:
        """A file whose actual sha256 matches expected should not be flagged."""
        from agent33.packs.loader import verify_checksums

        pack_dir = tmp_path / "mypack"
        pack_dir.mkdir()
        test_file = pack_dir / "PACK.yaml"
        test_file.write_text("name: mypack\nversion: 1.0.0\n")
        actual = hashlib.sha256(test_file.read_bytes()).hexdigest()

        checksums = pack_dir / "CHECKSUMS.sha256"
        checksums.write_text(f"{actual}  PACK.yaml\n")

        ok, mismatches = verify_checksums(pack_dir)
        assert ok is True
        assert mismatches == []

    def test_tampered_file_detected(self, tmp_path: Path) -> None:
        """A file whose content differs from the checksum must be flagged."""
        from agent33.packs.loader import verify_checksums

        pack_dir = tmp_path / "mypack"
        pack_dir.mkdir()
        test_file = pack_dir / "PACK.yaml"
        test_file.write_text("name: mypack\n")
        wrong_hash = "a" * 64

        checksums = pack_dir / "CHECKSUMS.sha256"
        checksums.write_text(f"{wrong_hash}  PACK.yaml\n")

        ok, mismatches = verify_checksums(pack_dir)
        assert ok is False
        assert len(mismatches) == 1
        assert "PACK.yaml" in mismatches[0]
        assert "Checksum mismatch" in mismatches[0]

    def test_compare_digest_used_not_equality(self) -> None:
        """Verify the actual implementation calls hmac.compare_digest.

        Read loader.py source and confirm no bare != comparison on hexdigest output.
        """
        from agent33.packs import loader

        source = inspect.getsource(loader)
        # The old vulnerable pattern must not exist
        assert "actual_hash != expected_hash" not in source
        # The secure replacement must be present
        assert "hmac.compare_digest" in source


class TestApprovalTokensHmacDigest:
    """security/approval_tokens.py must use hmac.compare_digest for arg_hash comparison."""

    def test_compare_digest_used_not_equality(self) -> None:
        """Verify the actual implementation calls hmac.compare_digest for arg_hash."""
        from agent33.security import approval_tokens

        source = inspect.getsource(approval_tokens)
        # The old vulnerable pattern must not exist
        assert 'data.get("arg_hash") != expected_hash' not in source
        # The secure replacement must be present
        assert "hmac.compare_digest" in source

    def test_mismatched_arg_hash_raises(self) -> None:
        """A token with wrong arg_hash must raise ApprovalTokenError."""
        from agent33.security.approval_tokens import ApprovalTokenError, ApprovalTokenManager

        mgr = ApprovalTokenManager(secret="test-secret-key-that-is-long-enough")
        approval = _make_approved_request()
        token = mgr.issue(approval, arguments={"cmd": "ls"})

        # Tamper: verify with different arguments
        with pytest.raises(ApprovalTokenError, match="hash mismatch"):
            mgr.validate(
                token=token,
                tool_name="shell",
                arguments={"cmd": "rm -rf /"},  # tampered
                tenant_id="tenant-001",
            )

    def test_correct_arg_hash_succeeds(self) -> None:
        """A token validated with the same arguments must pass."""
        from agent33.security.approval_tokens import ApprovalTokenManager

        mgr = ApprovalTokenManager(secret="test-secret-key-that-is-long-enough")
        approval = _make_approved_request()
        args = {"cmd": "ls"}
        token = mgr.issue(approval, arguments=args)

        payload = mgr.validate(
            token=token,
            tool_name="shell",
            arguments=args,
            tenant_id="tenant-001",
        )
        assert payload.tool == "shell"
        assert payload.tenant_id == "tenant-001"
