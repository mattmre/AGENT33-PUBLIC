"""Router archetype for 1-of-N agent dispatch."""

from __future__ import annotations

from typing import Any

from agent33.agents.archetypes.base import AgentArchetype


class RouterArchetype(AgentArchetype):
    """1-of-N agent dispatch router.

    Pre-configured to analyze requests and route them
    to the most appropriate specialist agent.
    """

    archetype_name: str = "router"
    description: str = "Request routing to specialist agents"
    default_role: str = (
        "You are a routing agent. Analyze the user's request and "
        "determine which specialist agent is best suited to handle "
        "it. Provide clear reasoning for your routing decision."
    )
    default_capabilities: list[str] = [
        "orchestration",
        "classification",
    ]
    default_tools: list[str] = []
    default_constraints: list[str] = [
        "Always explain routing decisions",
        "Consider all available agents before routing",
        "Escalate to human if no agent is suitable",
    ]

    def create(self, name: str, **overrides: Any) -> dict[str, Any]:
        """Create a router agent definition."""
        return self._build_definition(name, **overrides)
