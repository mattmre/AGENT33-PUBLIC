"""Tests for browser/computer-use execution gates."""

from __future__ import annotations

import pytest

from agent33.config import settings
from agent33.tools.base import ToolContext
from agent33.tools.browser_gate import evaluate_browser_computer_use_gate
from agent33.tools.computer_use import ComputerUseTool


@pytest.fixture(autouse=True)
def _restore_gate_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "browser_computer_use_enabled", True)


def test_gate_blocks_when_feature_flag_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "browser_computer_use_enabled", False)

    decision = evaluate_browser_computer_use_gate(
        "browser",
        "screenshot",
        ToolContext(tenant_id="tenant-a"),
    )

    assert decision.allowed is False
    assert "feature_flag:disabled" in decision.evidence


def test_gate_allows_read_actions_without_policy() -> None:
    decision = evaluate_browser_computer_use_gate(
        "computer_use",
        "screenshot",
        ToolContext(tenant_id="tenant-a"),
    )

    assert decision.allowed is True
    assert decision.action_class == "read"
    assert "policy:read-only" in decision.evidence


def test_gate_blocks_interactive_actions_without_allow_policy() -> None:
    decision = evaluate_browser_computer_use_gate(
        "computer_use",
        "left_click",
        ToolContext(tenant_id="tenant-a"),
    )

    assert decision.allowed is False
    assert decision.action_class == "interactive"
    assert "policy:missing" in decision.evidence


async def test_computer_use_interactive_action_requires_allow_policy() -> None:
    tool = ComputerUseTool()

    result = await tool.execute(
        {"action": "left_click", "coordinate": [10, 20]},
        ToolContext(tenant_id="tenant-a"),
    )

    assert result.success is False
    assert "explicit allow policy" in result.error
    assert "browser-computer-use-gate" in result.error


async def test_computer_use_interactive_action_runs_with_allow_policy() -> None:
    """Even with allow policy, computer_use returns not-available (OS automation undeployed)."""
    tool = ComputerUseTool()

    result = await tool.execute(
        {"action": "left_click", "coordinate": [10, 20]},
        ToolContext(tenant_id="tenant-a", tool_policies={"computer_use": "allow"}),
    )

    assert result.success is False
    assert "not available" in result.error
