"""Signoff state machine for the two-layer review workflow.

Valid transitions are defined in ``core/orchestrator/TWO_LAYER_REVIEW.md``
§ Signoff States.
"""

from __future__ import annotations

from agent33.review.models import SignoffState

# ---------------------------------------------------------------------------
# Transition table
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[SignoffState, frozenset[SignoffState]] = {
    SignoffState.DRAFT: frozenset({SignoffState.READY}),
    SignoffState.READY: frozenset({SignoffState.L1_REVIEW}),
    SignoffState.L1_REVIEW: frozenset(
        {
            SignoffState.L1_APPROVED,
            SignoffState.L1_CHANGES_REQUESTED,
        }
    ),
    SignoffState.L1_CHANGES_REQUESTED: frozenset({SignoffState.DRAFT}),
    SignoffState.L1_APPROVED: frozenset(
        {
            SignoffState.L2_REVIEW,
            SignoffState.APPROVED,
        }
    ),
    SignoffState.L2_REVIEW: frozenset(
        {
            SignoffState.L2_APPROVED,
            SignoffState.L2_CHANGES_REQUESTED,
        }
    ),
    SignoffState.L2_CHANGES_REQUESTED: frozenset({SignoffState.DRAFT}),
    SignoffState.L2_APPROVED: frozenset({SignoffState.APPROVED}),
    SignoffState.APPROVED: frozenset(
        {
            SignoffState.MERGED,
            SignoffState.CHANGES_REQUESTED,
            SignoffState.DEFERRED,
        }
    ),
    SignoffState.CHANGES_REQUESTED: frozenset({SignoffState.READY}),
    SignoffState.DEFERRED: frozenset({SignoffState.READY}),
    SignoffState.MERGED: frozenset(),
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""

    def __init__(self, from_state: SignoffState, to_state: SignoffState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Invalid transition: {from_state.value} -> {to_state.value}")


class SignoffStateMachine:
    """Enforce valid state transitions for review records."""

    @staticmethod
    def can_transition(from_state: SignoffState, to_state: SignoffState) -> bool:
        """Return ``True`` if the transition is valid."""
        allowed = _VALID_TRANSITIONS.get(from_state, frozenset())
        return to_state in allowed

    @staticmethod
    def valid_next_states(state: SignoffState) -> frozenset[SignoffState]:
        """Return the set of states reachable from *state*."""
        return _VALID_TRANSITIONS.get(state, frozenset())

    @staticmethod
    def transition(from_state: SignoffState, to_state: SignoffState) -> SignoffState:
        """Attempt a transition; raise :class:`InvalidTransitionError` if invalid."""
        if not SignoffStateMachine.can_transition(from_state, to_state):
            raise InvalidTransitionError(from_state, to_state)
        return to_state
