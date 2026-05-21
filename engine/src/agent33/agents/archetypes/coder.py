"""Code interpreter archetype."""

from __future__ import annotations

from typing import Any

from agent33.agents.archetypes.base import AgentArchetype


class CoderArchetype(AgentArchetype):
    """Code interpreter agent with file and execution tools.

    Pre-configured with code execution capabilities,
    code tools, and sandbox constraints.
    """

    archetype_name: str = "coder"
    description: str = "Code interpreter with execution capabilities"
    default_role: str = (
        "You are a skilled software engineer. Write clean, tested "
        "code. Use file operations to read and write files. "
        "Execute code to verify it works before presenting results."
    )
    default_capabilities: list[str] = [
        "code_generation",
        "code_execution",
        "file_operations",
    ]
    default_tools: list[str] = [
        "file_read",
        "file_write",
        "shell",
    ]
    default_constraints: list[str] = [
        "Always test code before presenting final results",
        "Follow language-specific best practices",
        "Handle errors gracefully",
    ]

    def create(self, name: str, **overrides: Any) -> dict[str, Any]:
        """Create a coder agent definition."""
        return self._build_definition(name, **overrides)
