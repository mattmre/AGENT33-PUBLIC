"""Tests for W18-F3: browser safety hardening."""

import pytest
from fastapi.testclient import TestClient

from agent33.config import settings
from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.tools.base import ToolContext
from agent33.tools.browser_gate import evaluate_browser_computer_use_gate
from agent33.tools.computer_use import ComputerUseTool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = create_access_token("test-user", scopes=["admin"])
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# W18-F3-T01: ComputerUseTool always returns not-available after gate passes
# ---------------------------------------------------------------------------


async def test_computer_use_screenshot_returns_not_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """computer_use:screenshot with gate enabled must NOT return a placeholder."""
    monkeypatch.setattr(settings, "browser_computer_use_enabled", True)
    tool = ComputerUseTool()
    result = await tool.execute(
        {"action": "screenshot"},
        ToolContext(tenant_id="tenant-a"),
    )
    # Gate passes (screenshot is read-only) but OS automation is not wired
    assert result.success is False
    assert "not available" in result.error
    assert "SCREENSHOT_BASE64_PLACEHOLDER" not in result.error
    assert "SCREENSHOT_BASE64_PLACEHOLDER" not in result.output


# ---------------------------------------------------------------------------
# W18-F3-T02: Domain allowlist gate for navigate
# ---------------------------------------------------------------------------


def test_browser_gate_navigate_blocked_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    """navigate to a domain not in allowlist must be refused."""
    monkeypatch.setattr(settings, "browser_computer_use_enabled", True)
    ctx = ToolContext(
        tenant_id="t1",
        domain_allowlist=["example.com", "trusted.org"],
    )
    decision = evaluate_browser_computer_use_gate(
        "browser",
        "navigate",
        ctx,
        url="https://evil.example.net/path",
    )
    assert decision.allowed is False
    assert "domain_blocked" in " ".join(decision.evidence)
    assert "evil.example.net" in decision.reason


def test_browser_gate_navigate_allowed_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    """navigate to a domain in allowlist must be allowed (assuming interactive policy)."""
    monkeypatch.setattr(settings, "browser_computer_use_enabled", True)
    ctx = ToolContext(
        tenant_id="t1",
        domain_allowlist=["example.com"],
        tool_policies={"browser": "allow"},
    )
    decision = evaluate_browser_computer_use_gate(
        "browser",
        "navigate",
        ctx,
        url="https://www.example.com/page",
    )
    assert decision.allowed is True


def test_browser_gate_navigate_no_allowlist_passes_domain_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When domain_allowlist is empty, domain check is skipped."""
    monkeypatch.setattr(settings, "browser_computer_use_enabled", True)
    ctx = ToolContext(
        tenant_id="t1",
        domain_allowlist=[],
        tool_policies={"browser": "allow"},
    )
    decision = evaluate_browser_computer_use_gate(
        "browser",
        "navigate",
        ctx,
        url="https://anywhere.example.com/",
    )
    assert decision.allowed is True


# ---------------------------------------------------------------------------
# W18-F3-T03: Feature flag disabled → gate refuses everything
# ---------------------------------------------------------------------------


def test_feature_flag_disabled_blocks_any_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """browser_computer_use_enabled=False must block all tools."""
    monkeypatch.setattr(settings, "browser_computer_use_enabled", False)
    for tool_name, action in [
        ("browser", "navigate"),
        ("browser", "screenshot"),
        ("computer_use", "screenshot"),
        ("computer_use", "left_click"),
    ]:
        decision = evaluate_browser_computer_use_gate(
            tool_name,
            action,
            ToolContext(tenant_id="t1"),
        )
        assert decision.allowed is False, f"Expected {tool_name}:{action} to be blocked"
        assert "feature_flag:disabled" in decision.evidence


# ---------------------------------------------------------------------------
# W18-F3-T04: GET /v1/browser/sessions returns empty list
# ---------------------------------------------------------------------------


def test_list_browser_sessions_empty(auth_headers: dict[str, str]) -> None:
    """GET /v1/browser/sessions returns 200 with sessions=[] when no sessions exist."""
    import agent33.tools.builtin.browser as _browser_mod

    original = dict(_browser_mod._sessions)
    _browser_mod._sessions.clear()
    try:
        client = TestClient(app, headers=auth_headers)
        resp = client.get("/v1/browser/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["sessions"] == []
    finally:
        _browser_mod._sessions.update(original)
