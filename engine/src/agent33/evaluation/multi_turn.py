"""Multi-turn evaluation scenarios for agent tool-use assessment.

Defines :class:`MultiTurnScenario` specifications and a
:class:`MultiTurnEvaluator` that drives an agent through a scripted
conversation, recording tool calls and measuring accuracy against
expected behavior.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

RunTurnCallback = Callable[
    [str, list[dict[str, Any]]],
    Coroutine[Any, Any, tuple[str, list["ToolCallRecord"]]],
]
"""Async callback: (user_message, history) -> (assistant_response, tool_calls)."""


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ToolCallExpectation(BaseModel):
    """Expected tool call in a multi-turn scenario."""

    tool_name: str
    required: bool = True
    expected_arguments: dict[str, Any] | None = None
    order: int | None = None


class ToolCallRecord(BaseModel):
    """Record of a tool call made during evaluation."""

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MultiTurnScenario(BaseModel):
    """Definition of a multi-turn evaluation scenario."""

    scenario_id: str
    description: str = ""
    initial_message: str
    expected_tool_calls: list[ToolCallExpectation] = Field(default_factory=list)
    max_turns: int = 10
    success_criteria: str = ""
    tags: list[str] = Field(default_factory=list)


class ToolCallCheckResult(BaseModel):
    """Result of checking actual tool calls against expectations."""

    matched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    unexpected: list[str] = Field(default_factory=list)
    order_violations: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def accuracy(self) -> float:
        """Fraction of expected tool calls that were matched.

        Returns 1.0 if there are no expectations (vacuously true).
        """
        total_expected = len(self.matched) + len(self.missing)
        if total_expected == 0:
            return 1.0
        return len(self.matched) / total_expected


class MultiTurnResult(BaseModel):
    """Result of running a multi-turn evaluation scenario."""

    scenario_id: str
    turns: int = 0
    tool_calls_made: list[ToolCallRecord] = Field(default_factory=list)
    tool_call_accuracy: float = 0.0
    success: bool = False
    duration_ms: float = 0.0
    tokens_used: int = 0


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


class MultiTurnEvaluator:
    """Drives a multi-turn conversation and evaluates tool-use accuracy.

    Parameters
    ----------
    run_turn:
        Async callback that takes a user message and conversation history,
        runs one turn of conversation, and returns the assistant response
        plus any tool calls made.
    """

    def __init__(self, run_turn: RunTurnCallback) -> None:
        self._run_turn = run_turn

    async def evaluate(self, scenario: MultiTurnScenario) -> MultiTurnResult:
        """Run a scenario from start to finish.

        Sends ``scenario.initial_message`` and then continues for up to
        ``scenario.max_turns``, collecting tool calls.  Stops early if the
        assistant response contains no tool calls after the first turn.
        """
        start = time.monotonic()
        history: list[dict[str, Any]] = []
        all_tool_calls: list[ToolCallRecord] = []
        turns = 0

        # Initial turn
        user_msg = scenario.initial_message
        for turn_idx in range(scenario.max_turns):
            turns = turn_idx + 1
            response, tool_calls = await self._run_turn(user_msg, history)

            # Record history
            history.append({"role": "user", "content": user_msg})
            history.append({"role": "assistant", "content": response})
            all_tool_calls.extend(tool_calls)

            # If no tool calls made this turn (after first), consider done
            if not tool_calls and turn_idx > 0:
                break

            # Next user message is the response (agent continues conversation)
            user_msg = response

        # Check tool calls
        check = self._check_tool_calls(all_tool_calls, scenario.expected_tool_calls)

        duration_ms = (time.monotonic() - start) * 1000.0
        return MultiTurnResult(
            scenario_id=scenario.scenario_id,
            turns=turns,
            tool_calls_made=all_tool_calls,
            tool_call_accuracy=check.accuracy,
            success=(
                check.accuracy == 1.0
                and len(check.order_violations) == 0
                and len(check.unexpected) == 0
            ),
            duration_ms=duration_ms,
        )

    @staticmethod
    def _check_tool_calls(
        actual: list[ToolCallRecord],
        expected: list[ToolCallExpectation],
    ) -> ToolCallCheckResult:
        """Compare actual tool calls against expectations.

        Matching logic:
        - A required expectation is matched if any actual call has the
          same tool_name (and matching arguments, if specified).
        - Non-required expectations that are not matched are NOT counted
          as missing.
        - Actual calls not matching any expectation are marked unexpected.
        - Order violations occur when an expectation with ``order`` set
          is matched by a call that appears after a higher-ordered match.
        """
        matched: list[str] = []
        missing: list[str] = []
        order_violations: list[str] = []

        actual_names = [tc.tool_name for tc in actual]
        matched_actual_indices: set[int] = set()

        # Track order: map expectation -> index of matching actual call
        order_map: dict[int, int] = {}  # expectation.order -> actual index

        for exp in expected:
            found_idx: int | None = None
            for i, tc in enumerate(actual):
                if i in matched_actual_indices:
                    continue
                if tc.tool_name != exp.tool_name:
                    continue
                # Check arguments if specified
                if exp.expected_arguments is not None and not _arguments_match(
                    exp.expected_arguments, tc.arguments
                ):
                    continue
                found_idx = i
                break

            if found_idx is not None:
                matched.append(exp.tool_name)
                matched_actual_indices.add(found_idx)
                if exp.order is not None:
                    order_map[exp.order] = found_idx
            elif exp.required:
                missing.append(exp.tool_name)

        # Check ordering: for each pair of ordered expectations, the
        # actual call index should be in ascending order.
        sorted_orders = sorted(order_map.keys())
        for i in range(len(sorted_orders) - 1):
            o1 = sorted_orders[i]
            o2 = sorted_orders[i + 1]
            if order_map[o1] > order_map[o2]:
                order_violations.append(
                    f"Expected order {o1} before {o2}, "
                    f"but actual indices were {order_map[o1]} and {order_map[o2]}"
                )

        # Unexpected: actual calls not matched to any expectation
        unexpected = [
            actual_names[i] for i in range(len(actual)) if i not in matched_actual_indices
        ]

        return ToolCallCheckResult(
            matched=matched,
            missing=missing,
            unexpected=unexpected,
            order_violations=order_violations,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _arguments_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    """Check if expected arguments are a subset of actual arguments."""
    for key, val in expected.items():
        if key not in actual:
            return False
        if actual[key] != val:
            return False
    return True
