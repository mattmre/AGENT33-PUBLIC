"""Group chat host archetype."""

from __future__ import annotations

from typing import Any

from agent33.agents.archetypes.base import AgentArchetype


class GroupChatHostArchetype(AgentArchetype):
    """Multi-agent conversation facilitator.

    Pre-configured to moderate multi-agent discussions,
    manage speaker turns, and synthesize conclusions.
    """

    archetype_name: str = "group-chat-host"
    description: str = "Multi-agent conversation facilitator"
    default_role: str = (
        "You are a discussion facilitator managing a multi-agent "
        "conversation. Ensure all participants contribute "
        "meaningfully, keep the discussion on topic, and "
        "synthesize conclusions from the group's inputs."
    )
    default_capabilities: list[str] = [
        "orchestration",
        "communication",
        "summarization",
    ]
    default_tools: list[str] = []
    default_constraints: list[str] = [
        "Ensure equitable participation among agents",
        "Keep discussions focused on the original task",
        "Summarize key findings after discussion rounds",
    ]

    def create(self, name: str, **overrides: Any) -> dict[str, Any]:
        """Create a group chat host agent definition."""
        return self._build_definition(name, **overrides)
