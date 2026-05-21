"""Tests for per-component context window budgeting (S27).

Covers:
- Token estimation via ContextWindowManager
- Budget creation with various component combinations
- Budget utilization calculation (computed fields)
- History truncation (keeps system + recent, drops oldest)
- Context truncation strategies (head, tail, smart)
- ContextWindowPolicy enforcement (max ratios)
- fits_budget check against available tokens
- Utilization report contents
- API route GET /v1/agents/{name}/context-budget

Every assertion targets a specific behavioral outcome -- not just that
functions run without error.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agent33.agents.context_window import (
    ContextBudget,
    ContextWindowManager,
    ContextWindowPolicy,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _manager(**kwargs: Any) -> ContextWindowManager:
    """Create a ContextWindowManager with sensible test defaults."""
    return ContextWindowManager(**kwargs)


# ═══════════════════════════════════════════════════════════════════════
# Token estimation
# ═══════════════════════════════════════════════════════════════════════


class TestEstimateTokens:
    """ContextWindowManager.estimate_tokens() using the heuristic counter."""

    def test_empty_string_returns_zero(self) -> None:
        mgr = _manager()
        assert mgr.estimate_tokens("") == 0

    def test_short_text_positive(self) -> None:
        mgr = _manager()
        tokens = mgr.estimate_tokens("Hello world")
        # 11 chars / 3.5 ≈ 3
        assert tokens == 3

    def test_long_text_scales_linearly(self) -> None:
        mgr = _manager()
        short = mgr.estimate_tokens("a" * 100)
        long = mgr.estimate_tokens("a" * 1000)
        ratio = long / short
        # Should be ~10x
        assert 9.5 <= ratio <= 10.5

    def test_single_character_returns_at_least_one(self) -> None:
        mgr = _manager()
        assert mgr.estimate_tokens("x") >= 1


# ═══════════════════════════════════════════════════════════════════════
# Budget creation
# ═══════════════════════════════════════════════════════════════════════


class TestCreateBudget:
    """ContextWindowManager.create_budget() allocates tokens per-component."""

    def test_empty_budget_uses_defaults(self) -> None:
        mgr = _manager(default_max_tokens=100_000)
        budget = mgr.create_budget()
        assert budget.max_tokens == 100_000
        # With no components, only message overhead contributes
        assert budget.system_tokens == 0
        assert budget.tool_tokens == 0
        assert budget.skill_tokens == 0

    def test_system_prompt_counted(self) -> None:
        mgr = _manager()
        budget = mgr.create_budget(system_prompt="You are a helpful assistant.")
        assert budget.system_tokens > 0

    def test_tool_definitions_counted(self) -> None:
        mgr = _manager()
        tools = ['{"name": "search", "description": "Search the web"}']
        budget = mgr.create_budget(tools=tools)
        assert budget.tool_tokens > 0

    def test_history_messages_counted(self) -> None:
        mgr = _manager()
        history = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a programming language."},
        ]
        budget = mgr.create_budget(history=history)
        assert budget.history_tokens > 0

    def test_skills_counted(self) -> None:
        mgr = _manager()
        skills = ["## Skill: web_fetch\n\nFetch content from URLs."]
        budget = mgr.create_budget(skills=skills)
        assert budget.skill_tokens > 0

    def test_all_components_combined(self) -> None:
        mgr = _manager(default_max_tokens=200_000)
        budget = mgr.create_budget(
            max_tokens=200_000,
            system_prompt="System prompt here.",
            tools=['{"name": "tool1"}'],
            history=[{"role": "user", "content": "Hello"}],
            skills=["Skill instructions here."],
        )
        # Every component contributes > 0
        assert budget.system_tokens > 0
        assert budget.tool_tokens > 0
        assert budget.history_tokens > 0
        assert budget.skill_tokens > 0
        # used_tokens is the sum
        expected_used = (
            budget.system_tokens + budget.tool_tokens + budget.history_tokens + budget.skill_tokens
        )
        assert budget.used_tokens == expected_used
        # available = max - used
        assert budget.available_tokens == budget.max_tokens - budget.used_tokens

    def test_custom_max_tokens_overrides_default(self) -> None:
        mgr = _manager(default_max_tokens=100_000)
        budget = mgr.create_budget(max_tokens=32_000)
        assert budget.max_tokens == 32_000


# ═══════════════════════════════════════════════════════════════════════
# Budget utilization
# ═══════════════════════════════════════════════════════════════════════


class TestBudgetUtilization:
    """ContextBudget computed fields: used_tokens, available_tokens, utilization."""

    def test_zero_usage_yields_zero_utilization(self) -> None:
        budget = ContextBudget(max_tokens=100_000)
        assert budget.used_tokens == 0
        assert budget.available_tokens == 100_000
        assert budget.utilization == 0.0

    def test_full_usage_yields_hundred_percent(self) -> None:
        budget = ContextBudget(max_tokens=100, system_tokens=100)
        assert budget.used_tokens == 100
        assert budget.available_tokens == 0
        assert budget.utilization == 100.0

    def test_partial_usage(self) -> None:
        budget = ContextBudget(
            max_tokens=1000,
            system_tokens=200,
            tool_tokens=100,
            history_tokens=150,
            skill_tokens=50,
        )
        assert budget.used_tokens == 500
        assert budget.available_tokens == 500
        assert budget.utilization == 50.0

    def test_over_budget_available_clamped_to_zero(self) -> None:
        budget = ContextBudget(
            max_tokens=100,
            system_tokens=60,
            history_tokens=60,
        )
        assert budget.used_tokens == 120
        assert budget.available_tokens == 0  # clamped, not negative
        assert budget.utilization == 120.0  # can exceed 100%

    def test_zero_max_tokens_returns_hundred_percent(self) -> None:
        budget = ContextBudget(max_tokens=0)
        assert budget.utilization == 100.0


# ═══════════════════════════════════════════════════════════════════════
# History truncation
# ═══════════════════════════════════════════════════════════════════════


class TestTruncateHistory:
    """ContextWindowManager.truncate_history() keeps system + recent messages."""

    def test_under_budget_no_change(self) -> None:
        mgr = _manager()
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = mgr.truncate_history(messages, max_tokens=10_000)
        assert len(result) == 2
        assert result[0]["content"] == "hi"

    def test_over_budget_removes_oldest_non_system(self) -> None:
        mgr = _manager()
        messages = [
            {"role": "user", "content": "a" * 500},
            {"role": "assistant", "content": "b" * 500},
            {"role": "user", "content": "c" * 500},
            {"role": "user", "content": "recent"},
        ]
        # With a tight budget, oldest messages should be dropped
        result = mgr.truncate_history(messages, max_tokens=60)
        assert len(result) < len(messages)
        # Most recent message preserved
        assert result[-1]["content"] == "recent"

    def test_system_messages_always_preserved(self) -> None:
        mgr = _manager()
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "a" * 500},
            {"role": "assistant", "content": "b" * 500},
            {"role": "user", "content": "latest"},
        ]
        result = mgr.truncate_history(messages, max_tokens=30)
        system_msgs = [m for m in result if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0]["content"] == "You are helpful."

    def test_empty_messages_returns_empty(self) -> None:
        mgr = _manager()
        result = mgr.truncate_history([], max_tokens=100)
        assert result == []

    def test_does_not_mutate_original(self) -> None:
        mgr = _manager()
        messages = [
            {"role": "user", "content": "a" * 500},
            {"role": "user", "content": "b" * 500},
            {"role": "user", "content": "recent"},
        ]
        original_len = len(messages)
        mgr.truncate_history(messages, max_tokens=60)
        assert len(messages) == original_len


# ═══════════════════════════════════════════════════════════════════════
# Context truncation strategies
# ═══════════════════════════════════════════════════════════════════════


class TestTruncateContext:
    """ContextWindowManager.truncate_context() with head/tail/smart strategies."""

    def test_under_budget_returns_unchanged(self) -> None:
        mgr = _manager()
        text = "Short text"
        result = mgr.truncate_context(text, max_tokens=10_000)
        assert result == text

    def test_head_keeps_beginning(self) -> None:
        mgr = _manager()
        text = "BEGINNING" + "x" * 1000 + "END"
        result = mgr.truncate_context(text, max_tokens=10, strategy="head")
        assert result.startswith("BEGINNING")
        assert "END" not in result
        assert len(result) < len(text)

    def test_tail_keeps_end(self) -> None:
        mgr = _manager()
        text = "BEGINNING" + "x" * 1000 + "END"
        result = mgr.truncate_context(text, max_tokens=10, strategy="tail")
        assert result.endswith("END")
        assert "BEGINNING" not in result
        assert len(result) < len(text)

    def test_smart_keeps_start_and_end(self) -> None:
        mgr = _manager()
        text = "START_MARKER" + "x" * 2000 + "END_MARKER"
        result = mgr.truncate_context(text, max_tokens=30, strategy="smart")
        assert "START_MARKER" in result
        assert "END_MARKER" in result
        assert "[truncated]" in result
        assert len(result) < len(text)

    def test_default_strategy_is_tail(self) -> None:
        mgr = _manager()
        text = "BEGINNING" + "x" * 1000 + "END"
        result = mgr.truncate_context(text, max_tokens=10)
        # Default strategy = "tail", so END should be preserved
        assert result.endswith("END")


# ═══════════════════════════════════════════════════════════════════════
# Policy enforcement
# ═══════════════════════════════════════════════════════════════════════


class TestPolicyEnforcement:
    """ContextWindowManager.enforce_policy() caps components to their ratios."""

    def test_under_limits_no_change(self) -> None:
        policy = ContextWindowPolicy(
            max_history_ratio=0.5,
            max_skill_ratio=0.2,
            max_tool_ratio=0.15,
        )
        mgr = _manager(default_max_tokens=100_000, policy=policy)
        budget = ContextBudget(
            max_tokens=100_000,
            system_tokens=1000,
            history_tokens=10_000,  # 10% < 50%
            skill_tokens=5_000,  # 5% < 20%
            tool_tokens=5_000,  # 5% < 15%
        )
        enforced = mgr.enforce_policy(budget)
        assert enforced.history_tokens == 10_000
        assert enforced.skill_tokens == 5_000
        assert enforced.tool_tokens == 5_000

    def test_history_capped_to_ratio(self) -> None:
        policy = ContextWindowPolicy(max_history_ratio=0.5)
        mgr = _manager(default_max_tokens=100_000, policy=policy)
        budget = ContextBudget(
            max_tokens=100_000,
            system_tokens=1000,
            history_tokens=70_000,  # 70% > 50%
        )
        enforced = mgr.enforce_policy(budget)
        assert enforced.history_tokens == 50_000  # capped to 50%

    def test_skill_capped_to_ratio(self) -> None:
        policy = ContextWindowPolicy(max_skill_ratio=0.1)
        mgr = _manager(default_max_tokens=100_000, policy=policy)
        budget = ContextBudget(
            max_tokens=100_000,
            system_tokens=1000,
            skill_tokens=30_000,  # 30% > 10%
        )
        enforced = mgr.enforce_policy(budget)
        assert enforced.skill_tokens == 10_000

    def test_tool_capped_to_ratio(self) -> None:
        policy = ContextWindowPolicy(max_tool_ratio=0.05)
        mgr = _manager(default_max_tokens=100_000, policy=policy)
        budget = ContextBudget(
            max_tokens=100_000,
            system_tokens=1000,
            tool_tokens=20_000,
        )
        enforced = mgr.enforce_policy(budget)
        assert enforced.tool_tokens == 5_000

    def test_system_tokens_never_capped(self) -> None:
        """System tokens are always preserved by policy enforcement."""
        policy = ContextWindowPolicy()
        mgr = _manager(default_max_tokens=100_000, policy=policy)
        budget = ContextBudget(
            max_tokens=100_000,
            system_tokens=80_000,
        )
        enforced = mgr.enforce_policy(budget)
        assert enforced.system_tokens == 80_000

    def test_multiple_components_capped_simultaneously(self) -> None:
        policy = ContextWindowPolicy(
            max_history_ratio=0.3,
            max_skill_ratio=0.1,
            max_tool_ratio=0.1,
        )
        mgr = _manager(default_max_tokens=100_000, policy=policy)
        budget = ContextBudget(
            max_tokens=100_000,
            system_tokens=5_000,
            history_tokens=50_000,
            skill_tokens=25_000,
            tool_tokens=20_000,
        )
        enforced = mgr.enforce_policy(budget)
        assert enforced.history_tokens == 30_000
        assert enforced.skill_tokens == 10_000
        assert enforced.tool_tokens == 10_000
        assert enforced.system_tokens == 5_000


# ═══════════════════════════════════════════════════════════════════════
# fits_budget
# ═══════════════════════════════════════════════════════════════════════


class TestFitsBudget:
    """ContextWindowManager.fits_budget() checks available tokens."""

    def test_short_text_fits(self) -> None:
        mgr = _manager()
        budget = ContextBudget(max_tokens=100_000, system_tokens=1000)
        assert mgr.fits_budget("hello", budget) is True

    def test_text_exceeding_budget_does_not_fit(self) -> None:
        mgr = _manager()
        budget = ContextBudget(max_tokens=100, system_tokens=99)
        # available_tokens = 1
        assert mgr.fits_budget("a" * 100, budget) is False

    def test_exact_fit(self) -> None:
        mgr = _manager()
        budget = ContextBudget(max_tokens=1000, system_tokens=0)
        # 3500 chars / 3.5 = 1000 tokens exactly
        assert mgr.fits_budget("a" * 3500, budget) is True

    def test_zero_available_means_nothing_fits(self) -> None:
        mgr = _manager()
        budget = ContextBudget(max_tokens=100, system_tokens=100)
        assert budget.available_tokens == 0
        assert mgr.fits_budget("x", budget) is False


# ═══════════════════════════════════════════════════════════════════════
# Utilization report
# ═══════════════════════════════════════════════════════════════════════


class TestUtilizationReport:
    """ContextWindowManager.get_utilization_report() returns complete breakdown."""

    def test_report_contains_all_fields(self) -> None:
        mgr = _manager()
        budget = ContextBudget(
            max_tokens=100_000,
            system_tokens=5000,
            tool_tokens=2000,
            history_tokens=3000,
            skill_tokens=1000,
        )
        report = mgr.get_utilization_report(budget)

        assert report["max_tokens"] == 100_000
        assert report["system_tokens"] == 5000
        assert report["tool_tokens"] == 2000
        assert report["history_tokens"] == 3000
        assert report["skill_tokens"] == 1000
        assert report["used_tokens"] == 11_000
        assert report["available_tokens"] == 89_000
        assert report["utilization_pct"] == 11.0
        assert report["over_budget"] is False

    def test_over_budget_flag(self) -> None:
        mgr = _manager()
        budget = ContextBudget(
            max_tokens=100,
            system_tokens=60,
            history_tokens=60,
        )
        report = mgr.get_utilization_report(budget)
        assert report["over_budget"] is True
        assert report["utilization_pct"] == 120.0

    def test_warn_threshold_reported(self) -> None:
        policy = ContextWindowPolicy(warn_threshold=0.9)
        mgr = _manager(policy=policy)
        budget = ContextBudget(max_tokens=100, system_tokens=85)
        report = mgr.get_utilization_report(budget)
        assert report["warn_threshold_pct"] == 90.0
        assert report["above_warn_threshold"] is False

    def test_above_warn_threshold_flagged(self) -> None:
        policy = ContextWindowPolicy(warn_threshold=0.5)
        mgr = _manager(policy=policy)
        budget = ContextBudget(max_tokens=100, system_tokens=60)
        report = mgr.get_utilization_report(budget)
        assert report["above_warn_threshold"] is True


# ═══════════════════════════════════════════════════════════════════════
# check_and_warn
# ═══════════════════════════════════════════════════════════════════════


class TestCheckAndWarn:
    """ContextWindowManager.check_and_warn() logs at appropriate levels."""

    def test_no_warning_under_threshold(self) -> None:
        policy = ContextWindowPolicy(warn_threshold=0.9)
        mgr = _manager(policy=policy)
        budget = ContextBudget(max_tokens=100_000, system_tokens=1000)
        # Should not raise or crash
        mgr.check_and_warn(budget)

    def test_warning_logged_above_threshold(self) -> None:
        policy = ContextWindowPolicy(warn_threshold=0.5)
        mgr = _manager(policy=policy)
        budget = ContextBudget(max_tokens=100, system_tokens=60)  # 60% > 50%
        with patch("agent33.agents.context_window.logger") as mock_logger:
            mgr.check_and_warn(budget)
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args[0][0]
            assert "utilization" in call_args.lower()


# ═══════════════════════════════════════════════════════════════════════
# ContextWindowPolicy model validation
# ═══════════════════════════════════════════════════════════════════════


class TestContextWindowPolicy:
    """ContextWindowPolicy field validation."""

    def test_defaults(self) -> None:
        policy = ContextWindowPolicy()
        assert policy.max_history_ratio == 0.5
        assert policy.max_skill_ratio == 0.2
        assert policy.max_tool_ratio == 0.15
        assert policy.truncation_strategy == "smart"
        assert policy.warn_threshold == 0.8

    def test_custom_values(self) -> None:
        policy = ContextWindowPolicy(
            max_history_ratio=0.7,
            max_skill_ratio=0.1,
            max_tool_ratio=0.05,
            truncation_strategy="head",
            warn_threshold=0.95,
        )
        assert policy.max_history_ratio == 0.7
        assert policy.truncation_strategy == "head"
        assert policy.warn_threshold == 0.95

    def test_ratio_bounds_enforced(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ContextWindowPolicy(max_history_ratio=1.5)
        with pytest.raises(ValidationError):
            ContextWindowPolicy(max_history_ratio=-0.1)


# ═══════════════════════════════════════════════════════════════════════
# API route tests
# ═══════════════════════════════════════════════════════════════════════


class TestContextBudgetRoute:
    """GET /v1/agents/{name}/context-budget returns utilization breakdown."""

    def _get_client(self) -> TestClient:
        from agent33.main import app
        from agent33.security.auth import create_access_token

        token = create_access_token("test-user", scopes=["agents:read"])
        return TestClient(app, headers={"Authorization": f"Bearer {token}"})

    def test_known_agent_returns_budget(self) -> None:
        """Register an agent, then query its context budget."""
        from agent33.agents.definition import AgentDefinition
        from agent33.agents.registry import AgentRegistry
        from agent33.main import app

        # Install a registry with a test agent
        registry = AgentRegistry()
        definition = AgentDefinition(
            name="test-budget-agent",
            version="1.0.0",
            role="worker",
            description="Test agent for budget endpoint",
        )
        registry.register(definition)
        app.state.agent_registry = registry

        client = self._get_client()
        response = client.get("/v1/agents/test-budget-agent/context-budget")
        assert response.status_code == 200
        data = response.json()

        # All report fields present
        assert "max_tokens" in data
        assert "system_tokens" in data
        assert "tool_tokens" in data
        assert "history_tokens" in data
        assert "skill_tokens" in data
        assert "used_tokens" in data
        assert "available_tokens" in data
        assert "utilization_pct" in data
        assert "over_budget" in data
        assert "agent" in data
        assert data["agent"] == "test-budget-agent"

        # System prompt should have consumed some tokens
        assert data["system_tokens"] > 0
        assert data["over_budget"] is False

        # Cleanup
        delattr(app.state, "agent_registry")

    def test_unknown_agent_returns_404(self) -> None:
        from agent33.agents.registry import AgentRegistry
        from agent33.main import app

        registry = AgentRegistry()
        app.state.agent_registry = registry

        client = self._get_client()
        response = client.get("/v1/agents/nonexistent-agent/context-budget")
        assert response.status_code == 404

        delattr(app.state, "agent_registry")

    def test_unauthenticated_returns_401(self) -> None:
        from agent33.main import app

        client = TestClient(app)
        response = client.get("/v1/agents/any-agent/context-budget")
        assert response.status_code == 401


# ═══════════════════════════════════════════════════════════════════════
# Integration: runtime uses context_window_manager
# ═══════════════════════════════════════════════════════════════════════


class TestRuntimeIntegration:
    """AgentRuntime accepts and uses ContextWindowManager."""

    def test_runtime_accepts_context_window_manager(self) -> None:
        """Verify the parameter is accepted and stored without error."""
        from agent33.agents.context_window import ContextWindowManager
        from agent33.agents.definition import AgentDefinition
        from agent33.agents.runtime import AgentRuntime
        from agent33.llm.router import ModelRouter

        definition = AgentDefinition(
            name="test-cw",
            version="1.0.0",
            role="worker",
        )
        router = ModelRouter()
        cwm = ContextWindowManager()

        runtime = AgentRuntime(
            definition=definition,
            router=router,
            context_window_manager=cwm,
        )
        # The manager is stored internally -- verify via the attribute
        assert runtime._context_window_manager is cwm  # noqa: SLF001

    def test_runtime_works_without_manager(self) -> None:
        """Passing None (default) does not break anything."""
        from agent33.agents.definition import AgentDefinition
        from agent33.agents.runtime import AgentRuntime
        from agent33.llm.router import ModelRouter

        definition = AgentDefinition(
            name="test-no-cw",
            version="1.0.0",
            role="worker",
        )
        router = ModelRouter()

        runtime = AgentRuntime(
            definition=definition,
            router=router,
        )
        assert runtime._context_window_manager is None  # noqa: SLF001
