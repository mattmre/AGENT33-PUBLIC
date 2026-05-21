"""CA-030: Workflow Migration Tooling."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

MigrationFn = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class MigrationStep:
    """A single migration between two versions."""

    from_version: str
    to_version: str
    upgrade_fn: MigrationFn
    downgrade_fn: MigrationFn | None = None


class WorkflowMigration:
    """Manages versioned workflow definition migrations.

    Migration functions are registered per version pair and applied
    sequentially to transform definitions between versions.
    """

    def __init__(self) -> None:
        self._migrations: dict[tuple[str, str], MigrationStep] = {}

    def register(
        self,
        from_version: str,
        to_version: str,
        upgrade_fn: MigrationFn,
        downgrade_fn: MigrationFn | None = None,
    ) -> None:
        """Register a migration between two versions.

        Parameters
        ----------
        from_version:
            Source version string (e.g. ``"1.0.0"``).
        to_version:
            Target version string.
        upgrade_fn:
            Callable that transforms the definition dict forward.
        downgrade_fn:
            Optional callable for reverse migration.
        """
        step = MigrationStep(
            from_version=from_version,
            to_version=to_version,
            upgrade_fn=upgrade_fn,
            downgrade_fn=downgrade_fn,
        )
        self._migrations[(from_version, to_version)] = step

    def _find_path(self, from_v: str, to_v: str) -> list[tuple[str, str]]:
        """Find the migration path between two versions."""
        if from_v == to_v:
            return []

        # BFS over version graph
        from collections import deque

        graph: dict[str, list[str]] = {}
        for f, t in self._migrations:
            graph.setdefault(f, []).append(t)

        visited: set[str] = {from_v}
        queue: deque[tuple[str, list[tuple[str, str]]]] = deque()
        queue.append((from_v, []))

        while queue:
            current, path = queue.popleft()
            for neighbor in graph.get(current, []):
                if neighbor == to_v:
                    return [*path, (current, neighbor)]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, [*path, (current, neighbor)]))

        raise ValueError(f"No migration path from {from_v} to {to_v}")

    def upgrade(
        self,
        definition: dict[str, Any],
        from_version: str,
        to_version: str,
    ) -> dict[str, Any]:
        """Upgrade a workflow definition between versions.

        Parameters
        ----------
        definition:
            The raw workflow definition dict.
        from_version:
            Current version.
        to_version:
            Target version.

        Returns
        -------
        dict[str, Any]
            The migrated definition.
        """
        path = self._find_path(from_version, to_version)
        result = dict(definition)
        for f, t in path:
            step = self._migrations[(f, t)]
            result = step.upgrade_fn(result)
            result["version"] = t
        return result

    def downgrade(
        self,
        definition: dict[str, Any],
        from_version: str,
        to_version: str,
    ) -> dict[str, Any]:
        """Downgrade a workflow definition between versions.

        Parameters
        ----------
        definition:
            The raw workflow definition dict.
        from_version:
            Current version.
        to_version:
            Target version.

        Returns
        -------
        dict[str, Any]
            The downgraded definition.

        Raises
        ------
        ValueError
            If any step in the path lacks a downgrade function.
        """
        path = self._find_path(to_version, from_version)
        # Reverse the path for downgrade
        result = dict(definition)
        for f, t in reversed(path):
            step = self._migrations[(f, t)]
            if step.downgrade_fn is None:
                raise ValueError(f"No downgrade function for {f} -> {t}")
            result = step.downgrade_fn(result)
            result["version"] = f
        return result

    def validate_migration(
        self,
        from_version: str,
        to_version: str,
    ) -> bool:
        """Check whether a migration path exists and all steps have functions.

        Returns
        -------
        bool
            True if a valid path exists.
        """
        try:
            self._find_path(from_version, to_version)
            return True
        except ValueError:
            return False
