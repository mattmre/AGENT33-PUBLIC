"""Base archetype and registry."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AgentArchetype(BaseModel, ABC):
    """Base class for agent archetypes.

    Archetypes provide pre-configured defaults for common agent patterns.
    All defaults can be overridden via create().
    """

    archetype_name: str
    description: str
    default_role: str
    default_capabilities: list[str] = Field(default_factory=list)
    default_tools: list[str] = Field(default_factory=list)
    default_constraints: list[str] = Field(default_factory=list)

    @abstractmethod
    def create(self, name: str, **overrides: Any) -> dict[str, Any]:
        """Create an agent definition dict from this archetype.

        Args:
            name: Agent name/ID.
            **overrides: Any field to override defaults.

        Returns:
            Dict suitable for AgentDefinition construction.
        """
        ...

    def _build_definition(self, name: str, **overrides: Any) -> dict[str, Any]:
        """Build a base definition dict with defaults and overrides."""
        definition: dict[str, Any] = {
            "name": name,
            "role": overrides.pop("role", self.default_role),
            "capabilities": overrides.pop("capabilities", list(self.default_capabilities)),
            "constraints": overrides.pop("constraints", list(self.default_constraints)),
            "archetype": self.archetype_name,
        }

        # Merge tools — overrides can extend, not just replace
        tools = list(self.default_tools)
        extra_tools = overrides.pop("extra_tools", [])
        if extra_tools:
            tools.extend(extra_tools)
        if "tools" in overrides:
            tools = overrides.pop("tools")
        definition["tools"] = tools

        # Apply remaining overrides
        definition.update(overrides)
        return definition


class ArchetypeRegistry:
    """Registry for agent archetypes."""

    def __init__(self) -> None:
        self._archetypes: dict[str, AgentArchetype] = {}

    def register(self, archetype: AgentArchetype) -> None:
        """Register an archetype."""
        logger.info("Registering archetype: %s", archetype.archetype_name)
        self._archetypes[archetype.archetype_name] = archetype

    def get(self, name: str) -> AgentArchetype | None:
        """Get an archetype by name."""
        return self._archetypes.get(name)

    def list_all(self) -> list[AgentArchetype]:
        """List all registered archetypes."""
        return list(self._archetypes.values())

    def create_agent(
        self,
        archetype_name: str,
        agent_name: str,
        **overrides: Any,
    ) -> dict[str, Any]:
        """Create an agent definition from a named archetype."""
        archetype = self._archetypes.get(archetype_name)
        if archetype is None:
            msg = f"Unknown archetype: {archetype_name}"
            raise ValueError(msg)
        return archetype.create(agent_name, **overrides)
