"""Tests for P67: 4-level autonomy system.

Verifies that each autonomy level (0-3) produces a correctly-configured
AutonomyBudget with the expected file, command, network, and resource
scopes, and that the RuntimeEnforcer integration works end-to-end.
"""

from __future__ import annotations

import pytest

from agent33.autonomy.enforcement import RuntimeEnforcer
from agent33.autonomy.levels import (
    AUTONOMY_LEVEL_DESCRIPTIONS,
    autonomy_level_to_budget,
)
from agent33.autonomy.models import BudgetState, EnforcementResult

# ---------------------------------------------------------------------------
# Basic construction & validation
# ---------------------------------------------------------------------------


class TestAutonomyLevelConstruction:
    """Verify that all four levels produce valid budgets."""

    def test_all_four_levels_produce_active_budgets(self) -> None:
        for level in range(4):
            budget = autonomy_level_to_budget(level)
            assert budget is not None
            assert budget.state == BudgetState.ACTIVE
            assert budget.budget_id.startswith(f"level-{level}-")

    def test_invalid_level_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="must be 0-3"):
            autonomy_level_to_budget(4)

    def test_negative_level_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="must be 0-3"):
            autonomy_level_to_budget(-1)

    def test_budget_ids_are_unique(self) -> None:
        budgets = [autonomy_level_to_budget(1) for _ in range(5)]
        ids = [b.budget_id for b in budgets]
        assert len(set(ids)) == 5

    def test_custom_task_name_embedded(self) -> None:
        budget = autonomy_level_to_budget(2, task_name="my-custom-task")
        assert budget.task_id == "my-custom-task"

    def test_descriptions_exist_for_all_levels(self) -> None:
        for level in range(4):
            assert level in AUTONOMY_LEVEL_DESCRIPTIONS
            assert len(AUTONOMY_LEVEL_DESCRIPTIONS[level]) > 0


# ---------------------------------------------------------------------------
# Level 0 -- Fully supervised
# ---------------------------------------------------------------------------


class TestLevel0FullySupervised:
    """Level 0 should block writes, commands, and network."""

    def test_read_patterns_allow_all(self) -> None:
        budget = autonomy_level_to_budget(0)
        assert "**" in budget.files.read

    def test_write_patterns_empty(self) -> None:
        budget = autonomy_level_to_budget(0)
        assert budget.files.write == []

    def test_commands_blocked_by_allowlist_sentinel(self) -> None:
        budget = autonomy_level_to_budget(0)
        # Level 0 uses a sentinel entry in allowed_commands that never
        # matches real commands, so the allowlist check blocks everything.
        assert len(budget.allowed_commands) == 1
        assert budget.allowed_commands[0].command == "__none__"

    def test_network_disabled(self) -> None:
        budget = autonomy_level_to_budget(0)
        assert budget.network.enabled is False

    def test_conservative_resource_limits(self) -> None:
        budget = autonomy_level_to_budget(0)
        assert budget.limits.max_iterations == 5
        assert budget.limits.max_tool_calls == 10
        assert budget.limits.max_files_modified == 0

    def test_enforcer_blocks_file_write(self) -> None:
        budget = autonomy_level_to_budget(0)
        enforcer = RuntimeEnforcer(budget)
        result = enforcer.check_file_write("/some/file.txt")
        assert result == EnforcementResult.BLOCKED

    def test_enforcer_allows_file_read(self) -> None:
        budget = autonomy_level_to_budget(0)
        enforcer = RuntimeEnforcer(budget)
        result = enforcer.check_file_read("/any/path/file.py")
        assert result == EnforcementResult.ALLOWED

    def test_enforcer_blocks_command(self) -> None:
        budget = autonomy_level_to_budget(0)
        enforcer = RuntimeEnforcer(budget)
        result = enforcer.check_command("git status")
        assert result == EnforcementResult.BLOCKED

    def test_enforcer_blocks_network(self) -> None:
        budget = autonomy_level_to_budget(0)
        enforcer = RuntimeEnforcer(budget)
        result = enforcer.check_network("example.com")
        assert result == EnforcementResult.BLOCKED

    def test_has_escalation_trigger(self) -> None:
        budget = autonomy_level_to_budget(0)
        assert len(budget.escalation_triggers) > 0
        assert budget.escalation_triggers[0].target == "orchestrator"


# ---------------------------------------------------------------------------
# Level 1 -- Read/analyze auto (DEFAULT)
# ---------------------------------------------------------------------------


class TestLevel1ReadAnalyzeDefault:
    """Level 1 should allow reads and safe commands, block network."""

    def test_read_patterns_allow_all(self) -> None:
        budget = autonomy_level_to_budget(1)
        assert "**" in budget.files.read

    def test_write_patterns_allow_with_limits(self) -> None:
        budget = autonomy_level_to_budget(1)
        assert "**" in budget.files.write
        # But resource limits cap how much can be written
        assert budget.limits.max_files_modified == 10
        assert budget.limits.max_lines_changed == 1000

    def test_safe_read_commands_allowed(self) -> None:
        budget = autonomy_level_to_budget(1)
        enforcer = RuntimeEnforcer(budget)
        # git with read-only subcommands should be allowed
        result = enforcer.check_command("git log --oneline")
        assert result == EnforcementResult.ALLOWED

    def test_cat_command_allowed(self) -> None:
        budget = autonomy_level_to_budget(1)
        enforcer = RuntimeEnforcer(budget)
        result = enforcer.check_command("cat README.md")
        assert result == EnforcementResult.ALLOWED

    def test_ls_command_allowed(self) -> None:
        budget = autonomy_level_to_budget(1)
        enforcer = RuntimeEnforcer(budget)
        result = enforcer.check_command("ls -la")
        assert result == EnforcementResult.ALLOWED

    def test_non_allowlisted_command_blocked(self) -> None:
        budget = autonomy_level_to_budget(1)
        enforcer = RuntimeEnforcer(budget)
        result = enforcer.check_command("rm -rf /tmp/something")
        assert result == EnforcementResult.BLOCKED

    def test_network_disabled(self) -> None:
        budget = autonomy_level_to_budget(1)
        assert budget.network.enabled is False

    def test_moderate_resource_limits(self) -> None:
        budget = autonomy_level_to_budget(1)
        assert budget.limits.max_iterations == 20
        assert budget.limits.max_tool_calls == 50

    def test_require_approval_commands_defined(self) -> None:
        budget = autonomy_level_to_budget(1)
        assert "python" in budget.require_approval_commands
        assert "pip" in budget.require_approval_commands

    def test_git_write_commands_blocked_by_allowlist(self) -> None:
        budget = autonomy_level_to_budget(1)
        enforcer = RuntimeEnforcer(budget)
        # git push is not in the read-only allowlist, so it gets blocked
        result = enforcer.check_command("git push origin main")
        assert result == EnforcementResult.BLOCKED

    def test_git_commit_blocked_by_allowlist(self) -> None:
        budget = autonomy_level_to_budget(1)
        enforcer = RuntimeEnforcer(budget)
        result = enforcer.check_command("git commit -m 'test'")
        assert result == EnforcementResult.BLOCKED


# ---------------------------------------------------------------------------
# Level 2 -- Autonomous except destructive/external
# ---------------------------------------------------------------------------


class TestLevel2AutonomousExceptDestructive:
    """Level 2 should allow most operations, block destructive/external."""

    def test_file_read_and_write_allowed(self) -> None:
        budget = autonomy_level_to_budget(2)
        assert "**" in budget.files.read
        assert "**" in budget.files.write

    def test_system_files_denied(self) -> None:
        budget = autonomy_level_to_budget(2)
        assert "/etc/**" in budget.files.deny
        assert "/sys/**" in budget.files.deny
        assert "~/.ssh/**" in budget.files.deny

    def test_env_files_denied(self) -> None:
        budget = autonomy_level_to_budget(2)
        assert "**/.env" in budget.files.deny

    def test_enforcer_blocks_system_file_write(self) -> None:
        budget = autonomy_level_to_budget(2)
        enforcer = RuntimeEnforcer(budget)
        result = enforcer.check_file_write("/etc/passwd")
        assert result == EnforcementResult.BLOCKED

    def test_enforcer_allows_project_file_write(self) -> None:
        budget = autonomy_level_to_budget(2)
        enforcer = RuntimeEnforcer(budget)
        result = enforcer.check_file_write("src/main.py", lines=10)
        assert result == EnforcementResult.ALLOWED

    def test_destructive_commands_denied(self) -> None:
        budget = autonomy_level_to_budget(2)
        assert "rm" in budget.denied_commands
        assert "sudo" in budget.denied_commands
        assert "curl" in budget.denied_commands
        assert "wget" in budget.denied_commands
        assert "docker" in budget.denied_commands
        assert "kubectl" in budget.denied_commands

    def test_enforcer_blocks_rm(self) -> None:
        budget = autonomy_level_to_budget(2)
        enforcer = RuntimeEnforcer(budget)
        result = enforcer.check_command("rm -rf /tmp/something")
        assert result == EnforcementResult.BLOCKED

    def test_enforcer_blocks_sudo(self) -> None:
        budget = autonomy_level_to_budget(2)
        enforcer = RuntimeEnforcer(budget)
        result = enforcer.check_command("sudo apt-get install foo")
        assert result == EnforcementResult.BLOCKED

    def test_enforcer_allows_safe_command(self) -> None:
        budget = autonomy_level_to_budget(2)
        enforcer = RuntimeEnforcer(budget)
        # No allowlist means anything not in deny is allowed
        result = enforcer.check_command("python -m pytest tests/")
        assert result == EnforcementResult.ALLOWED

    def test_local_network_allowed(self) -> None:
        budget = autonomy_level_to_budget(2)
        assert budget.network.enabled is True
        assert "localhost" in budget.network.allowed_domains
        assert "127.0.0.1" in budget.network.allowed_domains

    def test_enforcer_allows_localhost(self) -> None:
        budget = autonomy_level_to_budget(2)
        enforcer = RuntimeEnforcer(budget)
        result = enforcer.check_network("localhost")
        assert result == EnforcementResult.ALLOWED

    def test_enforcer_blocks_external_domain(self) -> None:
        budget = autonomy_level_to_budget(2)
        enforcer = RuntimeEnforcer(budget)
        result = enforcer.check_network("api.github.com")
        assert result == EnforcementResult.BLOCKED

    def test_generous_resource_limits(self) -> None:
        budget = autonomy_level_to_budget(2)
        assert budget.limits.max_iterations == 50
        assert budget.limits.max_tool_calls == 200
        assert budget.limits.max_files_modified == 30


# ---------------------------------------------------------------------------
# Level 3 -- Fully autonomous
# ---------------------------------------------------------------------------


class TestLevel3FullyAutonomous:
    """Level 3 should allow everything."""

    def test_all_files_allowed(self) -> None:
        budget = autonomy_level_to_budget(3)
        assert "**" in budget.files.read
        assert "**" in budget.files.write
        assert budget.files.deny == []

    def test_no_command_restrictions(self) -> None:
        budget = autonomy_level_to_budget(3)
        assert budget.denied_commands == []
        assert budget.require_approval_commands == []

    def test_network_fully_enabled(self) -> None:
        budget = autonomy_level_to_budget(3)
        assert budget.network.enabled is True
        assert budget.network.allowed_domains == []
        assert budget.network.denied_domains == []

    def test_enforcer_allows_any_network(self) -> None:
        budget = autonomy_level_to_budget(3)
        enforcer = RuntimeEnforcer(budget)
        result = enforcer.check_network("api.github.com")
        assert result == EnforcementResult.ALLOWED

    def test_enforcer_allows_any_command(self) -> None:
        budget = autonomy_level_to_budget(3)
        enforcer = RuntimeEnforcer(budget)
        result = enforcer.check_command("docker compose up -d")
        assert result == EnforcementResult.ALLOWED

    def test_enforcer_allows_any_file_write(self) -> None:
        budget = autonomy_level_to_budget(3)
        enforcer = RuntimeEnforcer(budget)
        result = enforcer.check_file_write("/etc/hosts", lines=5)
        assert result == EnforcementResult.ALLOWED

    def test_high_resource_limits(self) -> None:
        budget = autonomy_level_to_budget(3)
        assert budget.limits.max_iterations == 100
        assert budget.limits.max_tool_calls == 500
        assert budget.limits.max_duration_minutes == 120

    def test_no_escalation_triggers(self) -> None:
        budget = autonomy_level_to_budget(3)
        assert budget.escalation_triggers == []


# ---------------------------------------------------------------------------
# Cross-level progression
# ---------------------------------------------------------------------------


class TestLevelProgression:
    """Higher levels should be strictly more permissive."""

    def test_network_permissiveness_increases(self) -> None:
        b0 = autonomy_level_to_budget(0)
        b1 = autonomy_level_to_budget(1)
        b2 = autonomy_level_to_budget(2)
        b3 = autonomy_level_to_budget(3)

        assert b0.network.enabled is False
        assert b1.network.enabled is False
        assert b2.network.enabled is True
        assert b3.network.enabled is True

    def test_iteration_limits_increase(self) -> None:
        limits = [autonomy_level_to_budget(level).limits.max_iterations for level in range(4)]
        assert limits == sorted(limits)
        assert limits[0] < limits[3]

    def test_tool_call_limits_increase(self) -> None:
        limits = [autonomy_level_to_budget(level).limits.max_tool_calls for level in range(4)]
        assert limits == sorted(limits)

    def test_file_modification_limits_increase(self) -> None:
        limits = [autonomy_level_to_budget(level).limits.max_files_modified for level in range(4)]
        assert limits == sorted(limits)

    def test_duration_limits_increase(self) -> None:
        limits = [
            autonomy_level_to_budget(level).limits.max_duration_minutes for level in range(4)
        ]
        assert limits == sorted(limits)


# ---------------------------------------------------------------------------
# Config integration
# ---------------------------------------------------------------------------


class TestConfigIntegration:
    """Verify the config field exists and defaults correctly."""

    def test_default_autonomy_level_is_one(self) -> None:
        from agent33.config import Settings

        s = Settings(
            jwt_secret="test-secret",
            api_secret_key="test-key",
            _env_file=None,
        )
        assert s.autonomy_default_level == 1

    def test_autonomy_level_can_be_overridden(self) -> None:
        from agent33.config import Settings

        s = Settings(
            jwt_secret="test-secret",
            api_secret_key="test-key",
            autonomy_default_level=3,
            _env_file=None,
        )
        assert s.autonomy_default_level == 3


# ---------------------------------------------------------------------------
# API request model integration
# ---------------------------------------------------------------------------


class TestAPIRequestModel:
    """Verify the autonomy_level field on the request model."""

    def test_request_model_accepts_autonomy_level(self) -> None:
        from agent33.api.routes.agents import InvokeIterativeRequest

        req = InvokeIterativeRequest(autonomy_level=2)
        assert req.autonomy_level == 2

    def test_request_model_defaults_to_none(self) -> None:
        from agent33.api.routes.agents import InvokeIterativeRequest

        req = InvokeIterativeRequest()
        assert req.autonomy_level is None

    def test_request_model_rejects_invalid_level(self) -> None:
        from pydantic import ValidationError

        from agent33.api.routes.agents import InvokeIterativeRequest

        with pytest.raises(ValidationError):
            InvokeIterativeRequest(autonomy_level=5)

    def test_request_model_rejects_negative_level(self) -> None:
        from pydantic import ValidationError

        from agent33.api.routes.agents import InvokeIterativeRequest

        with pytest.raises(ValidationError):
            InvokeIterativeRequest(autonomy_level=-1)


# ---------------------------------------------------------------------------
# Package-level export
# ---------------------------------------------------------------------------


class TestPackageExport:
    """Verify the autonomy package re-exports the P67 API."""

    def test_autonomy_level_to_budget_exported(self) -> None:
        from agent33.autonomy import autonomy_level_to_budget as exported_fn

        budget = exported_fn(1)
        assert budget.state == BudgetState.ACTIVE

    def test_descriptions_exported(self) -> None:
        from agent33.autonomy import AUTONOMY_LEVEL_DESCRIPTIONS

        assert 0 in AUTONOMY_LEVEL_DESCRIPTIONS
        assert 3 in AUTONOMY_LEVEL_DESCRIPTIONS
