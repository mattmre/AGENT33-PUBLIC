"""Directed acyclic graph builder for workflow step dependencies."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent33.workflows.definition import WorkflowStep


class CycleDetectedError(Exception):
    """Raised when a cycle is detected in the workflow DAG."""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__(f"Cycle detected in workflow steps: {' -> '.join(cycle)}")


class DAGBuilder:
    """Builds and analyzes a DAG from workflow steps.

    Constructs an adjacency list from step dependencies, performs topological
    sorting, detects cycles, and identifies groups of steps that can be
    executed concurrently.
    """

    def __init__(self, steps: list[WorkflowStep]) -> None:
        self._steps = {s.id: s for s in steps}
        self._adjacency: dict[str, list[str]] = defaultdict(list)
        self._in_degree: dict[str, int] = {}
        self._topo_order: list[str] | None = None
        self._groups: list[list[str]] | None = None

    def build(self) -> DAGBuilder:
        """Build the adjacency list and compute in-degrees.

        Returns self for method chaining.

        Raises:
            CycleDetectedError: If a cycle is found among steps.
        """
        # Initialize in-degree for every node
        for sid in self._steps:
            self._in_degree.setdefault(sid, 0)

        # Build edges: dependency -> dependent
        for step in self._steps.values():
            for dep in step.depends_on:
                self._adjacency[dep].append(step.id)
                self._in_degree[step.id] = self._in_degree.get(step.id, 0) + 1

        # Validate no cycles by running topological sort eagerly
        self._compute_topo_and_groups()
        return self

    def _compute_topo_and_groups(self) -> None:
        """Run Kahn's algorithm to produce both topological order and parallel groups."""
        in_degree = dict(self._in_degree)
        order: list[str] = []
        groups: list[list[str]] = []

        # Start with all zero in-degree nodes
        queue: deque[str] = deque(sid for sid, deg in in_degree.items() if deg == 0)

        while queue:
            # All items currently in the queue form a parallel group
            group: list[str] = []
            for _ in range(len(queue)):
                node = queue.popleft()
                order.append(node)
                group.append(node)

            groups.append(sorted(group))

            # Decrease in-degree for neighbors of the entire group
            next_queue: list[str] = []
            for node in group:
                for neighbor in self._adjacency[node]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_queue.append(neighbor)

            queue.extend(sorted(next_queue))

        if len(order) != len(self._steps):
            # Find the cycle for a useful error message
            visited = set(order)
            remaining = [sid for sid in self._steps if sid not in visited]
            cycle = self._find_cycle(remaining)
            raise CycleDetectedError(cycle)

        self._topo_order = order
        self._groups = groups

    def _find_cycle(self, candidates: list[str]) -> list[str]:
        """Find and return one cycle among the given candidate node IDs."""
        visiting: set[str] = set()
        visited: set[str] = set()
        path: list[str] = []

        def dfs(node: str) -> list[str] | None:
            visiting.add(node)
            path.append(node)
            for neighbor in self._adjacency[node]:
                if neighbor in visiting:
                    idx = path.index(neighbor)
                    return path[idx:] + [neighbor]
                if neighbor not in visited:
                    result = dfs(neighbor)
                    if result is not None:
                        return result
            path.pop()
            visiting.discard(node)
            visited.add(node)
            return None

        for sid in candidates:
            if sid not in visited:
                cycle = dfs(sid)
                if cycle is not None:
                    return cycle

        return candidates[:2] + [candidates[0]]  # fallback

    def topological_order(self) -> list[str]:
        """Return step IDs in topological order.

        Raises:
            RuntimeError: If build() has not been called.
        """
        if self._topo_order is None:
            raise RuntimeError("Call build() before accessing topological order")
        return list(self._topo_order)

    def parallel_groups(self) -> list[list[str]]:
        """Return groups of step IDs that can execute concurrently.

        Each group is a list of step IDs with no mutual dependencies.
        Groups are ordered so that all dependencies of a group are in
        earlier groups.

        Raises:
            RuntimeError: If build() has not been called.
        """
        if self._groups is None:
            raise RuntimeError("Call build() before accessing parallel groups")
        return [list(g) for g in self._groups]
