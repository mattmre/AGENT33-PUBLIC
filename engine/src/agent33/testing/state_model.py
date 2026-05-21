"""CA-058: State Model Testing -- exhaustive state machine exploration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from agent33.workflows.state_machine import StatechartDefinition, StateNode


@dataclass
class ExplorationReport:
    """Report from exhaustive state machine exploration."""

    reachable_states: set[str] = field(default_factory=set)
    unreachable_states: set[str] = field(default_factory=set)
    transitions_explored: int = 0
    deadlock_states: list[str] = field(default_factory=list)
    livelock_candidates: list[str] = field(default_factory=list)
    invariant_violations: list[dict[str, Any]] = field(default_factory=list)


class StateModelTester:
    """Exhaustively explores state machine transitions to find issues.

    Given a ``StatechartDefinition``, enumerates all reachable states,
    checks invariants, and detects deadlocks and potential livelocks.
    """

    def __init__(
        self,
        definition: StatechartDefinition,
        invariants: dict[str, Callable[[str, dict[str, Any]], bool]] | None = None,
    ) -> None:
        """Initialize the tester.

        Parameters
        ----------
        definition:
            The statechart to explore.
        invariants:
            Named predicates ``(state_name, context) -> bool`` that must
            hold at every reachable state.
        """
        self._definition = definition
        self._invariants = invariants or {}

    def explore(self, max_depth: int = 100) -> ExplorationReport:
        """Perform exhaustive exploration of the state machine.

        Parameters
        ----------
        max_depth:
            Maximum transition depth to prevent infinite exploration.

        Returns
        -------
        ExplorationReport
        """
        all_states = set(self._definition.states.keys())
        reachable: set[str] = set()
        transitions_explored = 0
        visit_counts: dict[str, int] = {}
        deadlocks: list[str] = []
        violations: list[dict[str, Any]] = []

        # BFS from initial state
        queue: list[tuple[str, int]] = [(self._definition.initial, 0)]
        visited_transitions: set[tuple[str, str]] = set()

        while queue:
            state_name, depth = queue.pop(0)

            if state_name in reachable and depth > 0:
                # Already explored this state -- track revisits for livelock
                visit_counts[state_name] = visit_counts.get(state_name, 1) + 1
                continue

            reachable.add(state_name)
            visit_counts[state_name] = visit_counts.get(state_name, 0) + 1

            state_node: StateNode | None = self._definition.states.get(state_name)
            if state_node is None:
                continue

            # Check invariants
            for inv_name, inv_fn in self._invariants.items():
                if not inv_fn(state_name, self._definition.context):
                    violations.append(
                        {
                            "invariant": inv_name,
                            "state": state_name,
                        }
                    )

            # Detect deadlocks: non-final state with no outgoing transitions
            if not state_node.final and not state_node.on:
                deadlocks.append(state_name)

            if depth >= max_depth:
                continue

            # Explore transitions
            for _event, transition_def in state_node.on.items():
                if isinstance(transition_def, str):
                    target = transition_def
                else:
                    target = transition_def.target

                trans_key = (state_name, target)
                if trans_key not in visited_transitions:
                    visited_transitions.add(trans_key)
                    transitions_explored += 1
                    queue.append((target, depth + 1))

        # Livelock candidates: states that would be visited many times
        # in cyclic paths (detected by checking for cycles)
        livelock_candidates = self._detect_livelock_candidates(reachable)

        unreachable = all_states - reachable

        return ExplorationReport(
            reachable_states=reachable,
            unreachable_states=unreachable,
            transitions_explored=transitions_explored,
            deadlock_states=deadlocks,
            livelock_candidates=livelock_candidates,
            invariant_violations=violations,
        )

    def _detect_livelock_candidates(self, reachable: set[str]) -> list[str]:
        """Detect states involved in cycles that have no final state exit."""
        candidates: list[str] = []

        for state_name in reachable:
            node = self._definition.states.get(state_name)
            if node is None or node.final:
                continue

            # Check if this state is part of a cycle with no path to final
            if self._is_in_cycle_without_final(state_name):
                candidates.append(state_name)

        return candidates

    def _is_in_cycle_without_final(self, start: str) -> bool:
        """Check if start is in a cycle where no state leads to a final state."""
        # Find all states reachable from start
        visited: set[str] = set()
        stack = [start]
        while stack:
            s = stack.pop()
            if s in visited:
                continue
            visited.add(s)
            node = self._definition.states.get(s)
            if node is None:
                continue
            for transition_def in node.on.values():
                target = (
                    transition_def if isinstance(transition_def, str) else transition_def.target
                )
                stack.append(target)

        # Check if start is reachable from itself (cycle)
        can_return = start in {
            (t if isinstance(t, str) else t.target)
            for s in visited
            if (n := self._definition.states.get(s)) is not None
            for t in n.on.values()
            if (t if isinstance(t, str) else t.target) == start
        }

        if not can_return:
            return False

        # Check if any state in the cycle reaches a final state
        has_final = any(
            (n := self._definition.states.get(s)) is not None and n.final for s in visited
        )

        return not has_final
