"""Execution replay for workflow debugging."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator


@dataclass
class ReplayStep:
    """A recorded execution step."""

    workflow_id: str
    step_id: str
    state_snapshot: dict[str, Any]
    action_type: str = ""
    elapsed_ms: float = 0.0
    status: str = "success"
    error: str | None = None


class ExecutionReplay:
    """Records workflow state snapshots and replays them."""

    def __init__(self) -> None:
        self._steps: list[ReplayStep] = []

    def record_step(
        self,
        workflow_id: str,
        step_id: str,
        state_snapshot: dict[str, Any],
        *,
        action_type: str = "",
        elapsed_ms: float = 0.0,
        status: str = "success",
        error: str | None = None,
    ) -> None:
        """Record a state snapshot for a workflow step."""
        self._steps.append(
            ReplayStep(
                workflow_id=workflow_id,
                step_id=step_id,
                state_snapshot=copy.deepcopy(state_snapshot),
                action_type=action_type,
                elapsed_ms=elapsed_ms,
                status=status,
                error=error,
            )
        )

    def get_steps(self, workflow_id: str) -> list[ReplayStep]:
        """Return all recorded steps for a workflow run."""
        return [copy.copy(s) for s in self._steps if s.workflow_id == workflow_id]

    def replay(self, workflow_id: str) -> Generator[tuple[str, dict[str, Any]], None, None]:
        """Yield (step_id, state) tuples for replaying a workflow."""
        for step in self._steps:
            if step.workflow_id == workflow_id:
                yield step.step_id, copy.deepcopy(step.state_snapshot)
