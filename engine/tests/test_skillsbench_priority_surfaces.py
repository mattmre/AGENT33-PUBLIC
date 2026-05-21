"""Regression guards for SkillsBench-priority capability surfaces."""

from __future__ import annotations

import inspect

from agent33.agents.context_manager import ContextBudget
from agent33.agents.runtime import AgentRuntime
from agent33.agents.tool_loop import ToolLoopConfig
from agent33.config import settings
from agent33.evaluation.ctrf import CTRFGenerator
from agent33.evaluation.multi_trial import MultiTrialExecutor
from agent33.evaluation.service import DeterministicFallbackEvaluator, EvaluationService
from agent33.skills.matching import SkillMatcher


def test_agent_runtime_exposes_iterative_invoke() -> None:
    """AgentRuntime should expose iterative tool-loop invocation."""
    method = AgentRuntime.invoke_iterative
    assert inspect.iscoroutinefunction(method)


def test_tool_loop_defaults_remain_iterative() -> None:
    """Tool loop defaults should support multi-step execution."""
    config = ToolLoopConfig()
    assert config.max_iterations >= 10
    assert config.max_tool_calls_per_iteration >= 1
    assert config.enable_double_confirmation is True


def test_context_budget_reserves_completion_tokens() -> None:
    """Context window budget should keep room for model completion."""
    budget = ContextBudget()
    assert budget.effective_limit < budget.max_context_tokens
    assert budget.summarize_at < budget.effective_limit


def test_skill_matcher_exposes_four_stage_entrypoint() -> None:
    """Skill matcher contract should keep the async match(query) entrypoint."""
    assert hasattr(SkillMatcher, "match")
    signature = inspect.signature(SkillMatcher.match)
    assert "query" in signature.parameters


def test_evaluation_supports_multi_trial_and_ctrf() -> None:
    """Evaluation services should expose multi-trial and CTRF surfaces."""
    assert MultiTrialExecutor is not None
    assert CTRFGenerator is not None
    service = EvaluationService()
    assert hasattr(service, "export_ctrf")


def test_skillsbench_feature_flags_are_exposed() -> None:
    """SkillsBench wiring flags should exist on runtime settings."""
    assert hasattr(settings, "skillsbench_skill_matcher_enabled")
    assert hasattr(settings, "skillsbench_context_manager_enabled")


def test_evaluation_exposes_fallback_adapter_surface() -> None:
    """Evaluation service should expose deterministic adapter integration."""
    assert DeterministicFallbackEvaluator is not None
    service = EvaluationService()
    assert hasattr(service, "set_trial_evaluator")
