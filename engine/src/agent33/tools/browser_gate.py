"""Safety gate for browser and computer-use tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from agent33.config import settings

if TYPE_CHECKING:
    from agent33.tools.base import ToolContext

_READ_ACTIONS = {
    "browser": {"screenshot", "extract_text", "wait_for", "get_elements", "list_sessions"},
    "computer_use": {"screenshot", "cursor_position"},
}


@dataclass(frozen=True, slots=True)
class BrowserComputerUseGateDecision:
    """Gate decision with operator-review evidence."""

    allowed: bool
    reason: str
    evidence: list[str]
    action_class: str

    def evidence_line(self) -> str:
        return "browser-computer-use-gate:" + ";".join(self.evidence)


def evaluate_browser_computer_use_gate(
    tool_name: str,
    action: str,
    context: ToolContext,
    *,
    url: str = "",
) -> BrowserComputerUseGateDecision:
    """Return whether browser/computer-use execution is allowed."""
    normalized_action = action or "navigate"
    action_class = (
        "read" if normalized_action in _READ_ACTIONS.get(tool_name, set()) else "interactive"
    )
    evidence = [
        f"tool:{tool_name}",
        f"action:{normalized_action}",
        f"class:{action_class}",
        f"tenant:{context.tenant_id or 'none'}",
    ]

    if not settings.browser_computer_use_enabled:
        return BrowserComputerUseGateDecision(
            allowed=False,
            reason="Browser/computer-use tools are disabled by feature flag.",
            evidence=[*evidence, "feature_flag:disabled"],
            action_class=action_class,
        )

    # Domain allowlist check for navigate actions
    if normalized_action == "navigate" and context.domain_allowlist:
        nav_url = url or ""
        url_domain = _extract_domain(nav_url)
        if url_domain and not any(
            url_domain.endswith(d.lstrip("*.")) for d in context.domain_allowlist
        ):
            return BrowserComputerUseGateDecision(
                allowed=False,
                reason=f"Domain '{url_domain}' is not in the browser allowlist.",
                evidence=[
                    *evidence,
                    f"domain_allowlist:{context.domain_allowlist}",
                    "policy:domain_blocked",
                ],
                action_class=action_class,
            )

    if action_class == "read":
        return BrowserComputerUseGateDecision(
            allowed=True,
            reason="Read-only browser/computer-use action allowed.",
            evidence=[*evidence, "feature_flag:enabled", "policy:read-only"],
            action_class=action_class,
        )

    policy = _resolve_policy(tool_name, normalized_action, context)
    if policy == "allow":
        return BrowserComputerUseGateDecision(
            allowed=True,
            reason="Interactive browser/computer-use action allowed by explicit policy.",
            evidence=[*evidence, "feature_flag:enabled", "policy:allow"],
            action_class=action_class,
        )

    return BrowserComputerUseGateDecision(
        allowed=False,
        reason="Interactive browser/computer-use actions require an explicit allow policy.",
        evidence=[*evidence, "feature_flag:enabled", f"policy:{policy or 'missing'}"],
        action_class=action_class,
    )


def _resolve_policy(tool_name: str, action: str, context: ToolContext) -> str:
    candidates = (
        f"{tool_name}:{action}",
        f"{tool_name}:*",
        tool_name,
        "browser_computer_use",
    )
    for key in candidates:
        value = context.tool_policies.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def _extract_domain(url: str) -> str:
    """Return the hostname from *url*, or empty string if not parseable."""
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""
