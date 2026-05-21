"""State machine inspired by XState for workflow orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel, Field, PrivateAttr

if TYPE_CHECKING:
    from collections.abc import Callable

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger()


class Transition(BaseModel):
    """A state machine transition."""

    target: str
    guard: str | None = None
    actions: list[str] = Field(default_factory=list)


class StateNode(BaseModel):
    """A single state in the state machine."""

    on: dict[str, Transition | str] = Field(default_factory=dict)
    entry: list[str] = Field(default_factory=list)
    exit: list[str] = Field(default_factory=list)
    final: bool = False


class StatechartDefinition(BaseModel):
    """Complete statechart definition."""

    id: str
    initial: str
    context: dict[str, Any] = Field(default_factory=dict)
    states: dict[str, StateNode]


class StateMachineResult(BaseModel):
    """Result of running a state machine to completion."""

    final_state: str
    context: dict[str, Any]
    history: list[str]
    actions_executed: list[str]


class StateMachine:
    """Executes a statechart definition with guards, actions, and transitions.

    Guards are string keys mapped to callable predicates that receive the
    current context and return a bool. Actions are string keys mapped to
    callables that receive and may mutate the context dict.
    """

    def __init__(
        self,
        definition: StatechartDefinition,
        guards: dict[str, Callable[[dict[str, Any]], bool]] | None = None,
        actions: dict[str, Callable[[dict[str, Any]], None]] | None = None,
    ) -> None:
        self._definition = definition
        self._guards = guards or {}
        self._actions = actions or {}
        self._current_state = definition.initial
        self._context = dict(definition.context)
        self._history: list[str] = [definition.initial]
        self._actions_executed: list[str] = []

        # Run entry actions for the initial state
        self._run_entry(definition.initial)

    @property
    def current_state(self) -> str:
        return self._current_state

    @property
    def context(self) -> dict[str, Any]:
        return dict(self._context)

    def send(self, event: str) -> str:
        """Send an event to the state machine.

        Args:
            event: The event name.

        Returns:
            The new current state name.

        Raises:
            ValueError: If the current state has no transition for this event.
            RuntimeError: If the machine is in a final state.
        """
        state_node = self._definition.states.get(self._current_state)
        if state_node is None:
            raise RuntimeError(f"Unknown state: {self._current_state}")

        if state_node.final:
            raise RuntimeError(f"Cannot send events to final state '{self._current_state}'")

        transition_def = state_node.on.get(event)
        if transition_def is None:
            raise ValueError(f"No transition for event '{event}' in state '{self._current_state}'")

        # Normalize to Transition
        if isinstance(transition_def, str):
            transition = Transition(target=transition_def)
        else:
            transition = transition_def

        # Check guard
        if transition.guard:
            guard_fn = self._guards.get(transition.guard)
            if guard_fn is None:
                raise ValueError(f"Guard '{transition.guard}' is not registered")
            if not guard_fn(self._context):
                logger.info(
                    "guard_blocked",
                    state=self._current_state,
                    event=event,
                    guard=transition.guard,
                )
                return self._current_state

        # Run exit actions for current state
        self._run_exit(self._current_state)

        # Run transition actions
        for action_name in transition.actions:
            self._execute_action(action_name)

        # Transition
        old_state = self._current_state
        self._current_state = transition.target
        self._history.append(transition.target)

        logger.info(
            "state_transition",
            from_state=old_state,
            event=event,
            to_state=self._current_state,
        )

        # Run entry actions for new state
        self._run_entry(self._current_state)

        return self._current_state

    def is_final(self) -> bool:
        """Check if the machine is in a final state."""
        state_node = self._definition.states.get(self._current_state)
        return state_node is not None and state_node.final

    def result(self) -> StateMachineResult:
        """Return the current state machine result."""
        return StateMachineResult(
            final_state=self._current_state,
            context=dict(self._context),
            history=list(self._history),
            actions_executed=list(self._actions_executed),
        )

    def execute(self, events: list[str]) -> StateMachineResult:
        """Execute a sequence of events and return the result.

        Args:
            events: Ordered list of event names to send.

        Returns:
            The final StateMachineResult.
        """
        for event in events:
            if self.is_final():
                break
            self.send(event)
        return self.result()

    def _run_entry(self, state_name: str) -> None:
        state_node = self._definition.states.get(state_name)
        if state_node:
            for action_name in state_node.entry:
                self._execute_action(action_name)

    def _run_exit(self, state_name: str) -> None:
        state_node = self._definition.states.get(state_name)
        if state_node:
            for action_name in state_node.exit:
                self._execute_action(action_name)

    def _execute_action(self, action_name: str) -> None:
        fn = self._actions.get(action_name)
        if fn is not None:
            fn(self._context)
            self._actions_executed.append(action_name)
        else:
            logger.warning("action_not_found", action=action_name)
            self._actions_executed.append(f"{action_name}:not_found")


# ---------------------------------------------------------------------------
# CA-046: Deep History States
# ---------------------------------------------------------------------------


class HistoryState(BaseModel):
    """A history pseudo-state that remembers previous state configuration.

    When ``deep`` is True, the entire nested state hierarchy is restored
    (deep history). When False, only the top-level child state is restored
    (shallow history).
    """

    id: str
    parent_state: str
    deep: bool = False
    _saved_configuration: dict[str, str] = PrivateAttr(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}

    def save(self, configuration: dict[str, str]) -> None:
        """Save the current state configuration.

        Parameters
        ----------
        configuration:
            Mapping of region/level to active state name.
            For deep history, this includes all nested levels.
        """
        if self.deep:
            self._saved_configuration = dict(configuration)
        else:
            # Shallow: only save top-level
            self._saved_configuration = {k: v for k, v in configuration.items() if "." not in k}

    def restore(self) -> dict[str, str]:
        """Restore the saved state configuration.

        Returns
        -------
        dict[str, str]
            The previously saved configuration, or empty dict if none saved.
        """
        return dict(self._saved_configuration)

    @property
    def has_saved_state(self) -> bool:
        """Return whether a state configuration has been saved."""
        return bool(self._saved_configuration)
