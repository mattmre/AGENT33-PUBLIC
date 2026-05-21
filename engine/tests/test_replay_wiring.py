"""Tests that verify replay recording covers all secondary execution paths.

Gaps addressed:
- GAP 1: Condition evaluates to False (step skipped) — replay was not recorded.
- GAP 2: Condition expression throws an exception — replay was not recorded.
- GAP 3: Pre-hook aborts the step — replay was not recorded.

Each test confirms that ``ExecutionReplay.record_step`` is called for the
affected step *regardless* of how execution exits that step.
"""

from __future__ import annotations

import dataclasses
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from agent33.hooks.models import HookEventType, WorkflowHookContext
from agent33.observability.replay import ExecutionReplay
from agent33.workflows.definition import (
    StepAction,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowStep,
)
from agent33.workflows.executor import WorkflowExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_workflow(
    step: WorkflowStep,
    *,
    run_id: str = "test-run",
    replay: ExecutionReplay | None = None,
    hook_registry: Any | None = None,
) -> WorkflowExecutor:
    """Return an executor wrapping a single-step sequential workflow."""
    definition = WorkflowDefinition(
        name="test-workflow",
        version="1.0.0",
        execution=WorkflowExecution(),
        steps=[step],
    )
    return WorkflowExecutor(
        definition,
        run_id=run_id,
        replay=replay,
        hook_registry=hook_registry,
    )


def _aborting_hook_registry() -> Any:
    """Return a minimal hook registry whose pre-hook always aborts."""

    @dataclasses.dataclass
    class _AbortingChainRunner:
        """Synchronous chain runner that immediately aborts."""

        async def run(self, ctx: WorkflowHookContext) -> WorkflowHookContext:
            ctx.abort = True
            ctx.abort_reason = "test abort"
            return ctx

    class _Registry:
        def get_chain_runner(
            self,
            event_type: str,
            tenant_id: str = "",
            *args: Any,
            **kwargs: Any,
        ) -> _AbortingChainRunner:
            if event_type == HookEventType.WORKFLOW_STEP_PRE:
                return _AbortingChainRunner()
            # Post-hook: no-op runner
            noop = AsyncMock()
            noop.run = AsyncMock(return_value=MagicMock(abort=False))
            return noop

    return _Registry()


# ---------------------------------------------------------------------------
# GAP 1: step skipped because condition evaluates to False
# ---------------------------------------------------------------------------


async def test_replay_records_step_skipped_by_condition_false() -> None:
    """When a step's condition is False the replay must still record the step."""
    replay = ExecutionReplay()
    step = WorkflowStep(
        id="gated_step",
        action=StepAction.TRANSFORM,
        inputs={"data": 1},
        # Plain expression (no {{ }}) → compile_expression → Python False
        condition="1 == 2",
    )
    executor = _simple_workflow(step, replay=replay)
    result = await executor.execute()

    # The workflow itself should succeed (skipped is not failed)
    assert result.status.value == "success"

    # The step result inside the workflow should be "skipped"
    step_results = {sr.step_id: sr for sr in result.step_results}
    assert step_results["gated_step"].status == "skipped"

    # Replay must have recorded the step with status "skipped"
    recorded = replay.get_steps("test-run")
    assert len(recorded) == 1, f"Expected 1 replay entry, got {len(recorded)}: {recorded}"
    assert recorded[0].step_id == "gated_step"
    assert recorded[0].status == "skipped"
    assert recorded[0].workflow_id == "test-run"


async def test_replay_records_step_skipped_by_condition_false_no_replay_is_noop() -> None:
    """When replay=None, condition-false skip must not raise."""
    step = WorkflowStep(
        id="gated_step",
        action=StepAction.TRANSFORM,
        inputs={"data": 1},
        condition="1 == 2",
    )
    executor = _simple_workflow(step, replay=None)
    result = await executor.execute()
    # Workflow should still succeed without a replay service
    assert result.status.value == "success"
    step_results = {sr.step_id: sr for sr in result.step_results}
    assert step_results["gated_step"].status == "skipped"


# ---------------------------------------------------------------------------
# GAP 2: condition expression raises an exception
# ---------------------------------------------------------------------------


async def test_replay_records_step_failed_by_condition_error() -> None:
    """When a step's condition expression raises, the replay must record 'failed'."""
    replay = ExecutionReplay()
    # This Jinja2 expression references an undefined variable, causing evaluation failure.
    step = WorkflowStep(
        id="bad_condition_step",
        action=StepAction.TRANSFORM,
        inputs={"data": 1},
        condition="{{ undefined_var | some_bad_filter }}",
    )
    executor = _simple_workflow(step, replay=replay)
    result = await executor.execute()

    # Workflow should report the step as failed
    step_results = {sr.step_id: sr for sr in result.step_results}
    assert step_results["bad_condition_step"].status == "failed"
    assert "Condition evaluation error" in (step_results["bad_condition_step"].error or "")

    # Replay must have recorded the failed step
    recorded = replay.get_steps("test-run")
    assert len(recorded) == 1, f"Expected 1 replay entry, got {len(recorded)}: {recorded}"
    assert recorded[0].step_id == "bad_condition_step"
    assert recorded[0].status == "failed"
    assert recorded[0].error is not None
    assert "Condition evaluation error" in recorded[0].error


async def test_replay_records_condition_error_correct_action_type() -> None:
    """Condition-error replay entry carries the correct action_type field."""
    replay = ExecutionReplay()
    step = WorkflowStep(
        id="bad_cond",
        action=StepAction.VALIDATE,
        inputs={},
        condition="{{ undefined_var | bad }}",
    )
    executor = _simple_workflow(step, replay=replay)
    await executor.execute()

    recorded = replay.get_steps("test-run")
    assert recorded[0].action_type == StepAction.VALIDATE.value


async def test_replay_condition_error_no_replay_is_noop() -> None:
    """When replay=None, condition expression errors must not raise."""
    step = WorkflowStep(
        id="bad_cond",
        action=StepAction.TRANSFORM,
        inputs={"data": 1},
        condition="{{ undefined_var | bad }}",
    )
    executor = _simple_workflow(step, replay=None)
    result = await executor.execute()
    step_results = {sr.step_id: sr for sr in result.step_results}
    assert step_results["bad_cond"].status == "failed"


# ---------------------------------------------------------------------------
# GAP 3: pre-hook aborts the step
# ---------------------------------------------------------------------------


async def test_replay_records_step_failed_by_hook_abort() -> None:
    """When a pre-hook aborts execution, the replay must record 'failed'."""
    replay = ExecutionReplay()
    hook_registry = _aborting_hook_registry()
    step = WorkflowStep(
        id="hooked_step",
        action=StepAction.TRANSFORM,
        inputs={"data": 99},
    )
    executor = _simple_workflow(step, replay=replay, hook_registry=hook_registry)
    result = await executor.execute()

    # The step must be reported as failed due to hook abort
    step_results = {sr.step_id: sr for sr in result.step_results}
    assert step_results["hooked_step"].status == "failed"
    assert "Hook aborted" in (step_results["hooked_step"].error or "")
    assert "test abort" in (step_results["hooked_step"].error or "")

    # Replay must have recorded the failed step
    recorded = replay.get_steps("test-run")
    assert len(recorded) == 1, f"Expected 1 replay entry, got {len(recorded)}: {recorded}"
    assert recorded[0].step_id == "hooked_step"
    assert recorded[0].status == "failed"
    assert recorded[0].error is not None
    assert "Hook aborted" in recorded[0].error
    assert recorded[0].workflow_id == "test-run"


async def test_replay_hook_abort_carries_correct_action_type() -> None:
    """Hook-abort replay entry carries the correct action_type field."""
    replay = ExecutionReplay()
    step = WorkflowStep(
        id="hooked_step",
        action=StepAction.RUN_COMMAND,
        inputs={},
        command="echo hi",
    )
    executor = _simple_workflow(step, replay=replay, hook_registry=_aborting_hook_registry())
    await executor.execute()

    recorded = replay.get_steps("test-run")
    assert recorded[0].action_type == StepAction.RUN_COMMAND.value


async def test_replay_hook_abort_no_replay_is_noop() -> None:
    """When replay=None, hook-abort path must not raise."""
    step = WorkflowStep(
        id="hooked_step",
        action=StepAction.TRANSFORM,
        inputs={"data": 1},
    )
    executor = _simple_workflow(step, replay=None, hook_registry=_aborting_hook_registry())
    result = await executor.execute()
    step_results = {sr.step_id: sr for sr in result.step_results}
    assert step_results["hooked_step"].status == "failed"


# ---------------------------------------------------------------------------
# Regression: previously-covered paths still work (success + all-retries-fail)
# ---------------------------------------------------------------------------


async def test_replay_records_successful_step() -> None:
    """Baseline: successful steps are still recorded (regression guard)."""
    replay = ExecutionReplay()
    step = WorkflowStep(
        id="ok_step",
        action=StepAction.TRANSFORM,
        inputs={"data": 7},
    )
    executor = _simple_workflow(step, replay=replay)
    result = await executor.execute()

    assert result.status.value == "success"
    recorded = replay.get_steps("test-run")
    assert len(recorded) == 1
    assert recorded[0].step_id == "ok_step"
    assert recorded[0].status == "success"


async def test_replay_records_failed_step_after_all_retries() -> None:
    """Baseline: steps that exhaust all retries are still recorded as failed."""
    replay = ExecutionReplay()
    # max_attempts=1 means a single attempt with no retry delay.
    # RUN_COMMAND with a nonexistent command will fail on first (and only) attempt.
    step = WorkflowStep(
        id="fail_step",
        action=StepAction.RUN_COMMAND,
        command="__nonexistent_command_xyz__",
        inputs={},
        retry={"max_attempts": 1},
    )
    executor = _simple_workflow(step, replay=replay)
    result = await executor.execute()

    step_results = {sr.step_id: sr for sr in result.step_results}
    assert step_results["fail_step"].status == "failed"

    recorded = replay.get_steps("test-run")
    assert len(recorded) == 1
    assert recorded[0].step_id == "fail_step"
    assert recorded[0].status == "failed"
