"""Agent registry -- discovers and stores agent definitions."""

from __future__ import annotations

import logging
from pathlib import Path

from agent33.agents.definition import (
    AgentDefinition,
    AgentRole,
    AgentStatus,
    CapabilityCategory,
    SpecCapability,
)

logger = logging.getLogger(__name__)


class AgentRegistry:
    """In-memory registry of agent definitions keyed by name."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentDefinition] = {}

    # -- discovery --------------------------------------------------------

    def discover(self, path: str | Path) -> int:
        """Scan *path* for .json agent definitions and load them.

        Returns the number of definitions successfully loaded.
        """
        directory = Path(path)
        if not directory.is_dir():
            raise NotADirectoryError(f"Not a directory: {directory}")

        loaded = 0
        for json_file in sorted(directory.glob("*.json")):
            try:
                definition = AgentDefinition.load_from_file(json_file)
                self._agents[definition.name] = definition
                loaded += 1
                logger.info(
                    "loaded agent definition: %s (v%s)",
                    definition.name,
                    definition.version,
                )
            except Exception:
                logger.exception("failed to load agent definition from %s", json_file)

        return loaded

    # -- CRUD -------------------------------------------------------------

    def register(self, definition: AgentDefinition) -> None:
        """Add or replace an agent definition."""
        self._agents[definition.name] = definition

    def get(self, name: str) -> AgentDefinition | None:
        """Return the definition for *name*, or ``None``."""
        return self._agents.get(name)

    def list_all(self) -> list[AgentDefinition]:
        """Return all registered definitions, sorted by name."""
        return sorted(self._agents.values(), key=lambda d: d.name)

    def remove(self, name: str) -> bool:
        """Remove an agent by name. Returns True if it existed."""
        return self._agents.pop(name, None) is not None

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, name: str) -> bool:
        return name in self._agents

    # -- Search -----------------------------------------------------------

    def get_by_agent_id(self, agent_id: str) -> AgentDefinition | None:
        """Lookup by spec agent ID (e.g. ``AGT-001``)."""
        for defn in self._agents.values():
            if defn.agent_id == agent_id:
                return defn
        return None

    def find_by_role(self, role: AgentRole) -> list[AgentDefinition]:
        """Return all definitions with the given role."""
        return [d for d in self._agents.values() if d.role == role]

    def find_by_spec_capability(
        self,
        cap: SpecCapability,
    ) -> list[AgentDefinition]:
        """Return definitions that declare the given spec capability."""
        return [d for d in self._agents.values() if cap in d.spec_capabilities]

    def find_by_capability_category(
        self,
        category: CapabilityCategory,
    ) -> list[AgentDefinition]:
        """Return definitions with any capability in the category."""
        return [
            d
            for d in self._agents.values()
            if any(c.category == category for c in d.spec_capabilities)
        ]

    def find_by_status(self, status: AgentStatus) -> list[AgentDefinition]:
        """Return definitions with the given lifecycle status."""
        return [d for d in self._agents.values() if d.status == status]

    def search(
        self,
        *,
        role: AgentRole | None = None,
        spec_capability: SpecCapability | None = None,
        category: CapabilityCategory | None = None,
        status: AgentStatus | None = None,
    ) -> list[AgentDefinition]:
        """Multi-criteria AND search across all definitions."""
        results = list(self._agents.values())
        if role is not None:
            results = [d for d in results if d.role == role]
        if spec_capability is not None:
            results = [d for d in results if spec_capability in d.spec_capabilities]
        if category is not None:
            results = [
                d for d in results if any(c.category == category for c in d.spec_capabilities)
            ]
        if status is not None:
            results = [d for d in results if d.status == status]
        return sorted(results, key=lambda d: d.name)
