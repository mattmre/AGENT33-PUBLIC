"""Workflow executor that runs steps according to the DAG schedule."""

from __future__ import annotations

import asyncio
import inspect
import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel, Field

from agent33.workflows.actions import (
    conditional,
    execute_code,
    http_request,
    invoke_agent,
    parallel_group,
    route,
    run_command,
    sub_workflow,
    transform,
    validate,
    wait,
)
from agent33.workflows.dag import DAGBuilder
from agent33.workflows.definition import (
    ExecutionMode,
    StepAction,
    WorkflowDefinition,
    WorkflowStep,
)
from agent33.workflows.events import resolve_active_schema_version
from agent33.workflows.expressions import ExpressionEvaluator

if TYPE_CHECKING:
    from collections.abc import Callable

    from agent33.observability.replay import ExecutionReplay
    from agent33.workflows.checkpoint import CheckpointManager
    from agent33.workflows.events import WorkflowEvent

logger = structlog.get_logger()

_CHECKPOINT_META_KEY = "__workflow_checkpoint"


class WorkflowStatus(StrEnum):
    """Terminal status of a workflow execution."""

    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    SKIPPED = "skipped"


class StepResult(BaseModel):
    """Result of executing a single step."""

    step_id: str
    status: str
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0


class WorkflowResult(BaseModel):
    """Result of a complete workflow execution."""

    outputs: dict[str, Any] = Field(default_factory=dict)
    steps_executed: list[str] = Field(default_factory=list)
    step_results: list[StepResult] = Field(default_factory=list)
    duration_ms: float = 0.0
    status: WorkflowStatus = WorkflowStatus.SUCCESS


class WorkflowExecutor:
    """Executes a workflow definition by building a DAG and running steps.

    Supports sequential, parallel, and dependency-aware execution modes.
    Handles conditionals, retries, timeouts, and state passing between steps.
    """

    def __init__(
        self,
        definition: WorkflowDefinition,
        hook_registry: Any | None = None,
        tenant_id: str = "",
        agent_registry: Any | None = None,
        model_router: Any | None = None,
        run_id: str | None = None,
        event_sink: Callable[[WorkflowEvent], Any] | None = None,
        replay: ExecutionReplay | None = None,
        checkpoint_manager: CheckpointManager | None = None,
        resume_from_checkpoint: bool = True,
    ) -> None:
        self._definition = definition
        self._evaluator = ExpressionEvaluator()
        self._steps: dict[str, WorkflowStep] = {s.id: s for s in definition.steps}
        self._hook_registry = hook_registry
        self._tenant_id = tenant_id
        self._agent_registry = agent_registry
        self._model_router = model_router
        self._run_id = run_id or definition.name
        self._event_sink = event_sink
        self._replay = replay
        self._checkpoint_manager = checkpoint_manager
        self._resume_from_checkpoint = resume_from_checkpoint
        self._schema_version = resolve_active_schema_version()

    async def _load_checkpoint_state(
        self,
        inputs: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], set[str]]:
        """Return initial state plus checkpoint-completed step IDs for this run."""
        state: dict[str, Any] = dict(inputs or {})
        if self._checkpoint_manager is None or not self._resume_from_checkpoint:
            return state, set()

        checkpoint = await self._checkpoint_manager.load_checkpoint(self._run_id)
        if checkpoint is None:
            return state, set()

        checkpoint_state = dict(checkpoint)
        metadata = checkpoint_state.pop(_CHECKPOINT_META_KEY, {})
        completed_raw = metadata.get("completed_steps", []) if isinstance(metadata, dict) else []
        completed = {str(step_id) for step_id in completed_raw if str(step_id) in self._steps}
        state.update(checkpoint_state)
        return state, completed

    async def _save_checkpoint_state(
        self,
        *,
        step_id: str,
        state: dict[str, Any],
        completed_step_ids: set[str],
    ) -> None:
        """Persist resumable workflow state after a successful step."""
        if self._checkpoint_manager is None:
            return

        completed_in_definition_order = [
            step.id for step in self._definition.steps if step.id in completed_step_ids
        ]
        payload = dict(state)
        payload[_CHECKPOINT_META_KEY] = {
            "completed_steps": completed_in_definition_order,
            "last_step_id": step_id,
        }
        await self._checkpoint_manager.save_checkpoint(self._run_id, step_id, payload)

    def _checkpoint_restored_result(
        self,
        step: WorkflowStep,
        state: dict[str, Any],
    ) -> StepResult:
        """Build a non-executed step result from checkpointed state."""
        restored_outputs = state.get(step.id, {})
        outputs = (
            restored_outputs
            if isinstance(restored_outputs, dict)
            else {"result": restored_outputs}
        )
        return StepResult(
            step_id=step.id,
            status="skipped",
            outputs=outputs,
            duration_ms=0.0,
        )

    def _resolve_step_inputs(self, step: WorkflowStep, state: dict[str, Any]) -> dict[str, Any]:
        """Resolve step inputs without forcing invoke-agent prompt text into expressions."""
        if step.action != StepAction.INVOKE_AGENT:
            return self._evaluator.resolve_inputs(step.inputs, state)

        def resolve_agent_value(value: Any) -> Any:
            if isinstance(value, str) and ("{{" in value or "{%" in value):
                return self._evaluator.render_template(value, state)
            if isinstance(value, dict):
                return {key: resolve_agent_value(child) for key, child in value.items()}
            if isinstance(value, list):
                return [resolve_agent_value(child) for child in value]
            return value

        return {key: resolve_agent_value(value) for key, value in step.inputs.items()}

    async def _emit_event(
        self,
        event_type: str,
        *,
        step_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Fire a workflow event to the configured sink (if any)."""
        if self._event_sink is None:
            return

        from agent33.workflows.events import WorkflowEvent, WorkflowEventType

        event = WorkflowEvent(
            event_type=WorkflowEventType(event_type),
            run_id=self._run_id,
            workflow_name=self._definition.name,
            step_id=step_id,
            data=data or {},
            schema_version=self._schema_version,
        )
        result = self._event_sink(event)
        if inspect.isawaitable(result):
            await result

    async def execute(self, inputs: dict[str, Any] | None = None) -> WorkflowResult:
        """Execute the workflow with the given inputs.

        Args:
            inputs: Initial input data for the workflow.

        Returns:
            A WorkflowResult with outputs, executed steps, duration, and status.
        """
        start = time.monotonic()
        state, completed_step_ids = await self._load_checkpoint_state(inputs)
        step_results: list[StepResult] = []
        steps_executed: list[str] = []
        execution = self._definition.execution
        failed = False
        error_message: str | None = None

        await self._emit_event(
            "workflow_started",
            data={
                "step_count": len(self._definition.steps),
                "resumed_step_count": len(completed_step_ids),
            },
        )

        try:
            if execution.mode == ExecutionMode.SEQUENTIAL:
                for step in self._definition.steps:
                    if step.id in completed_step_ids:
                        result = self._checkpoint_restored_result(step, state)
                        step_results.append(result)
                        await self._emit_event(
                            "step_skipped",
                            step_id=step.id,
                            data={"reason": "checkpoint_resume"},
                        )
                        continue

                    result = await self._execute_step(step, state, execution.dry_run)
                    step_results.append(result)
                    state[step.id] = result.outputs
                    if result.status == "success":
                        completed_step_ids.add(step.id)
                        await self._save_checkpoint_state(
                            step_id=step.id,
                            state=state,
                            completed_step_ids=completed_step_ids,
                        )
                    steps_executed.append(step.id)

                    if result.status == "failed":
                        failed = True
                        error_message = result.error or error_message
                        if execution.fail_fast:
                            break
                        if not execution.continue_on_error:
                            break
            else:
                # dependency-aware or parallel: use DAG
                dag = DAGBuilder(self._definition.steps).build()
                groups = dag.parallel_groups()
                parallel_limit = execution.parallel_limit

                for group in groups:
                    if len(group) == 1:
                        for sid in group:
                            if sid in completed_step_ids:
                                result = self._checkpoint_restored_result(self._steps[sid], state)
                                step_results.append(result)
                                await self._emit_event(
                                    "step_skipped",
                                    step_id=sid,
                                    data={"reason": "checkpoint_resume"},
                                )
                                continue

                            result = await self._execute_step(
                                self._steps[sid], state, execution.dry_run
                            )
                            step_results.append(result)
                            state[sid] = result.outputs
                            if result.status == "success":
                                completed_step_ids.add(sid)
                                await self._save_checkpoint_state(
                                    step_id=sid,
                                    state=state,
                                    completed_step_ids=completed_step_ids,
                                )
                            steps_executed.append(sid)
                            if result.status == "failed":
                                failed = True
                                error_message = result.error or error_message
                                if execution.fail_fast:
                                    break
                        if failed and execution.fail_fast:
                            break
                    else:
                        restored_results: list[tuple[str, StepResult]] = []
                        group_to_run: list[str] = []
                        for sid in group:
                            if sid in completed_step_ids:
                                restored_results.append(
                                    (
                                        sid,
                                        self._checkpoint_restored_result(self._steps[sid], state),
                                    )
                                )
                            else:
                                group_to_run.append(sid)

                        for sid, restored in restored_results:
                            step_results.append(restored)
                            await self._emit_event(
                                "step_skipped",
                                step_id=sid,
                                data={"reason": "checkpoint_resume"},
                            )

                        if not group_to_run:
                            continue

                        # Run group in parallel with concurrency limit
                        _sem = asyncio.Semaphore(parallel_limit)

                        async def _run_limited(
                            sid: str,
                            semaphore: asyncio.Semaphore = _sem,
                        ) -> StepResult:
                            async with semaphore:
                                return await self._execute_step(
                                    self._steps[sid], state, execution.dry_run
                                )

                        tasks = [_run_limited(sid) for sid in group_to_run]
                        results = await asyncio.gather(*tasks, return_exceptions=True)

                        for sid, res in zip(group_to_run, results, strict=True):
                            if isinstance(res, BaseException):
                                sr = StepResult(
                                    step_id=sid,
                                    status="failed",
                                    error=str(res),
                                )
                                step_results.append(sr)
                                state[sid] = {}
                                failed = True
                                error_message = sr.error or error_message
                            else:
                                step_results.append(res)
                                state[sid] = res.outputs
                                if res.status == "failed":
                                    failed = True
                                    error_message = res.error or error_message
                                elif res.status == "success":
                                    completed_step_ids.add(sid)
                                    await self._save_checkpoint_state(
                                        step_id=sid,
                                        state=state,
                                        completed_step_ids=completed_step_ids,
                                    )
                            steps_executed.append(sid)

                        if failed and execution.fail_fast:
                            break

        except Exception as exc:
            logger.error("workflow_execution_error", error=str(exc))
            failed = True
            error_message = str(exc)

        elapsed_ms = (time.monotonic() - start) * 1000

        # Determine overall status
        if failed:
            any_success = any(r.status == "success" for r in step_results)
            status = WorkflowStatus.PARTIAL if any_success else WorkflowStatus.FAILED
        else:
            status = WorkflowStatus.SUCCESS

        # Collect final outputs from the last executed steps
        final_outputs: dict[str, Any] = {}
        for sr in step_results:
            if sr.status in {"success", "skipped"}:
                final_outputs.update(sr.outputs)

        if error_message is None:
            error_message = next(
                (sr.error for sr in reversed(step_results) if sr.status == "failed" and sr.error),
                None,
            )

        if failed:
            await self._emit_event(
                "workflow_failed",
                data={
                    "status": status.value,
                    "duration_ms": round(elapsed_ms, 2),
                    "error": error_message,
                },
            )
        else:
            await self._emit_event(
                "workflow_completed",
                data={
                    "status": status.value,
                    "duration_ms": round(elapsed_ms, 2),
                    "steps_executed": len(steps_executed),
                },
            )

        return WorkflowResult(
            outputs=final_outputs,
            steps_executed=steps_executed,
            step_results=step_results,
            duration_ms=round(elapsed_ms, 2),
            status=status,
        )

    async def _execute_step(
        self,
        step: WorkflowStep,
        state: dict[str, Any],
        dry_run: bool,
    ) -> StepResult:
        """Execute a single step with retry and timeout handling."""
        start = time.monotonic()

        # Evaluate condition
        if step.condition:
            try:
                should_run = self._evaluator.evaluate_condition(step.condition, state)
                if not should_run:
                    await self._emit_event(
                        "step_skipped",
                        step_id=step.id,
                        data={"reason": "condition_false"},
                    )
                    skipped_result = StepResult(
                        step_id=step.id,
                        status="skipped",
                        outputs={"skipped": True, "reason": "condition_false"},
                    )
                    if self._replay is not None:
                        self._replay.record_step(
                            self._run_id,
                            step.id,
                            state,
                            action_type=step.action.value,
                            elapsed_ms=0.0,
                            status="skipped",
                        )
                    return skipped_result
            except Exception as exc:
                await self._emit_event(
                    "step_failed",
                    step_id=step.id,
                    data={"error": f"Condition evaluation error: {exc}"},
                )
                condition_error_result = StepResult(
                    step_id=step.id,
                    status="failed",
                    error=f"Condition evaluation error: {exc}",
                )
                if self._replay is not None:
                    self._replay.record_step(
                        self._run_id,
                        step.id,
                        state,
                        action_type=step.action.value,
                        elapsed_ms=0.0,
                        status="failed",
                        error=condition_error_result.error,
                    )
                return condition_error_result

        # Resolve inputs
        resolved_inputs = self._resolve_step_inputs(step, state)

        # --- Hook: workflow.step.pre ---
        if self._hook_registry is not None:
            from agent33.hooks.models import HookEventType, WorkflowHookContext

            pre_runner = self._hook_registry.get_chain_runner(
                HookEventType.WORKFLOW_STEP_PRE, self._tenant_id
            )
            wf_hook_ctx = WorkflowHookContext(
                event_type=HookEventType.WORKFLOW_STEP_PRE,
                tenant_id=self._tenant_id,
                metadata={},
                workflow_name=self._definition.name,
                step_id=step.id,
                step_action=step.action.value,
                inputs=resolved_inputs,
                state=dict(state),
            )
            wf_hook_ctx = await pre_runner.run(wf_hook_ctx)
            if wf_hook_ctx.abort:
                hook_abort_result = StepResult(
                    step_id=step.id,
                    status="failed",
                    error=f"Hook aborted: {wf_hook_ctx.abort_reason}",
                )
                if self._replay is not None:
                    self._replay.record_step(
                        self._run_id,
                        step.id,
                        state,
                        action_type=step.action.value,
                        elapsed_ms=0.0,
                        status="failed",
                        error=hook_abort_result.error,
                    )
                return hook_abort_result
            resolved_inputs = wf_hook_ctx.inputs

        max_attempts = step.retry.max_attempts
        delay = step.retry.delay_seconds
        last_error: str | None = None

        await self._emit_event(
            "step_started",
            step_id=step.id,
            data={"action": step.action.value, "max_attempts": max_attempts},
        )

        for attempt in range(1, max_attempts + 1):
            try:
                coro = self._dispatch_action(step, resolved_inputs, state, dry_run)

                if step.timeout_seconds:
                    outputs = await asyncio.wait_for(coro, timeout=float(step.timeout_seconds))
                else:
                    outputs = await coro

                elapsed = (time.monotonic() - start) * 1000
                step_result = StepResult(
                    step_id=step.id,
                    status="success",
                    outputs=outputs,
                    duration_ms=round(elapsed, 2),
                )

                # --- Hook: workflow.step.post ---
                if self._hook_registry is not None:
                    from agent33.hooks.models import HookEventType, WorkflowHookContext

                    post_runner = self._hook_registry.get_chain_runner(
                        HookEventType.WORKFLOW_STEP_POST, self._tenant_id
                    )
                    wf_hook_ctx = WorkflowHookContext(
                        event_type=HookEventType.WORKFLOW_STEP_POST,
                        tenant_id=self._tenant_id,
                        metadata={},
                        workflow_name=self._definition.name,
                        step_id=step.id,
                        step_action=step.action.value,
                        inputs=resolved_inputs,
                        state=dict(state),
                        result=step_result,
                        duration_ms=step_result.duration_ms,
                    )
                    await post_runner.run(wf_hook_ctx)

                await self._emit_event(
                    "step_completed",
                    step_id=step.id,
                    data={"duration_ms": step_result.duration_ms},
                )

                if self._replay is not None:
                    self._replay.record_step(
                        self._run_id,
                        step.id,
                        state,
                        action_type=step.action.value,
                        elapsed_ms=step_result.duration_ms,
                        status="success",
                    )
                return step_result

            except TimeoutError:
                last_error = f"Step timed out after {step.timeout_seconds}s"
                logger.warning("step_timeout", step_id=step.id, attempt=attempt)
            except Exception as exc:
                last_error = str(exc)
                logger.warning("step_error", step_id=step.id, attempt=attempt, error=last_error)

            if attempt < max_attempts:
                await self._emit_event(
                    "step_retrying",
                    step_id=step.id,
                    data={
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "error": last_error,
                    },
                )
                await asyncio.sleep(delay)

        elapsed = (time.monotonic() - start) * 1000
        await self._emit_event(
            "step_failed",
            step_id=step.id,
            data={"error": last_error, "duration_ms": round(elapsed, 2)},
        )
        failure_result = StepResult(
            step_id=step.id,
            status="failed",
            error=last_error,
            duration_ms=round(elapsed, 2),
        )
        if self._replay is not None:
            self._replay.record_step(
                self._run_id,
                step.id,
                state,
                action_type=step.action.value,
                elapsed_ms=failure_result.duration_ms,
                status="failed",
                error=last_error,
            )
        return failure_result

    async def _dispatch_action(
        self,
        step: WorkflowStep,
        resolved_inputs: dict[str, Any],
        state: dict[str, Any],
        dry_run: bool,
    ) -> dict[str, Any]:
        """Dispatch execution to the appropriate action handler."""
        action = step.action

        if action == StepAction.INVOKE_AGENT:
            return await invoke_agent.execute(
                agent=step.agent,
                inputs=resolved_inputs,
                dry_run=dry_run,
            )

        if action == StepAction.RUN_COMMAND:
            return await run_command.execute(
                command=step.command,
                inputs=resolved_inputs,
                timeout_seconds=step.timeout_seconds,
                dry_run=dry_run,
            )

        if action == StepAction.VALIDATE:
            return await validate.execute(
                inputs=resolved_inputs,
                dry_run=dry_run,
            )

        if action == StepAction.TRANSFORM:
            return await transform.execute(
                inputs=resolved_inputs,
                dry_run=dry_run,
            )

        if action == StepAction.CONDITIONAL:
            result = await conditional.execute(
                condition=step.condition,
                inputs={**state, **resolved_inputs},
                dry_run=dry_run,
            )
            # Execute the appropriate branch sub-steps
            branch = result.get("branch", "then")
            branch_steps = step.then_steps if branch == "then" else step.else_steps
            branch_outputs: dict[str, Any] = dict(result)
            for sub_step in branch_steps:
                sub_result = await self._execute_step(sub_step, state, dry_run)
                state[sub_step.id] = sub_result.outputs
                branch_outputs[sub_step.id] = sub_result.outputs
            return branch_outputs

        if action == StepAction.PARALLEL_GROUP:
            sub_ids = [s.id for s in step.steps]
            # Register sub-steps temporarily
            for s in step.steps:
                self._steps[s.id] = s

            async def _run_sub(sid: str) -> dict[str, Any]:
                sub_step = self._steps[sid]
                r = await self._execute_step(sub_step, state, dry_run)
                state[sid] = r.outputs
                return r.outputs

            return await parallel_group.execute(
                sub_step_ids=sub_ids,
                run_step=_run_sub,
                dry_run=dry_run,
            )

        if action == StepAction.WAIT:
            return await wait.execute(
                inputs={**state, **resolved_inputs},
                duration_seconds=step.duration_seconds,
                wait_condition=step.wait_condition,
                timeout_seconds=step.timeout_seconds,
                dry_run=dry_run,
            )

        if action == StepAction.EXECUTE_CODE:
            return await execute_code.execute(
                tool_id=step.tool_id,
                adapter_id=step.adapter_id,
                inputs=resolved_inputs,
                sandbox=step.sandbox,
                dry_run=dry_run,
            )

        if action == StepAction.HTTP_REQUEST:
            return await http_request.execute(
                url=step.url,
                method=step.http_method,
                headers=step.http_headers,
                body=step.http_body,
                timeout_seconds=step.timeout_seconds or 30,
                inputs=resolved_inputs,
                dry_run=dry_run,
            )

        if action == StepAction.SUB_WORKFLOW:
            sub_run_id = f"{self._run_id}:sub:{step.id}"
            return await sub_workflow.execute(
                workflow_definition=step.sub_workflow,
                inputs=resolved_inputs,
                dry_run=dry_run,
                tenant_id=self._tenant_id,
                run_id=sub_run_id[-128:],
                replay=self._replay,
                checkpoint_manager=self._checkpoint_manager,
                hook_registry=self._hook_registry,
                agent_registry=self._agent_registry,
                model_router=self._model_router,
            )

        if action == StepAction.ROUTE:
            return await route.execute(
                query=step.query,
                candidates=step.route_candidates,
                model=step.route_model,
                inputs=resolved_inputs,
                dry_run=dry_run,
            )

        if action == StepAction.GROUP_CHAT:
            if step.group_chat is None:
                raise ValueError("group_chat config required for GROUP_CHAT action")
            from agent33.workflows.actions.group_chat import (
                GroupChatConfig,
            )
            from agent33.workflows.actions.group_chat import (
                execute as gc_execute,
            )

            gc_config = GroupChatConfig(**step.group_chat)
            gc_context: dict[str, Any] = {
                "agent_registry": self._agent_registry,
                "model_router": self._model_router,
            }
            return await gc_execute(gc_config, gc_context)

        raise ValueError(f"Unknown action: {action}")


# ---------------------------------------------------------------------------
# CA-043: Backpressure Signaling
# ---------------------------------------------------------------------------


class BackpressureController:
    """Concurrency limiter that emits backpressure signals.

    Upstream producers can check ``is_pressured()`` or await
    ``wait_for_capacity()`` before submitting more work.
    """

    def __init__(self, max_tokens: int = 10) -> None:
        self._max_tokens = max_tokens
        self._tokens = max_tokens
        self._lock = asyncio.Lock()
        self._capacity_event = asyncio.Event()
        self._capacity_event.set()

    async def acquire(self) -> bool:
        """Acquire a token. Returns True if acquired, False if no capacity."""
        async with self._lock:
            if self._tokens > 0:
                self._tokens -= 1
                if self._tokens == 0:
                    self._capacity_event.clear()
                return True
            return False

    async def release(self) -> None:
        """Release a token back to the pool."""
        async with self._lock:
            if self._tokens < self._max_tokens:
                self._tokens += 1
                if self._tokens > 0:
                    self._capacity_event.set()

    def is_pressured(self) -> bool:
        """Return True if the system is under backpressure (no tokens)."""
        return self._tokens == 0

    async def wait_for_capacity(self) -> None:
        """Block until at least one token is available."""
        await self._capacity_event.wait()
