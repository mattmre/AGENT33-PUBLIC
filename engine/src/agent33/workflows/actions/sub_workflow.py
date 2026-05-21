"""Action that executes a sub-workflow inline."""

from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING, Any

import structlog

logger = structlog.get_logger()

if TYPE_CHECKING:
    from agent33.observability.replay import ExecutionReplay
    from agent33.workflows.checkpoint import CheckpointManager

# Track nesting depth via a context variable so concurrent requests
# don't interfere with each other.
_nesting_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "sub_workflow_depth", default=0
)

_MAX_NESTING_DEPTH = 10


async def execute(
    workflow_definition: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    dry_run: bool = False,
    tenant_id: str = "",
    run_id: str | None = None,
    replay: ExecutionReplay | None = None,
    checkpoint_manager: CheckpointManager | None = None,
    hook_registry: Any | None = None,
    agent_registry: Any | None = None,
    model_router: Any | None = None,
) -> dict[str, Any]:
    """Execute a nested workflow defined inline.

    The sub-workflow is parsed into a
    :class:`~agent33.workflows.definition.WorkflowDefinition` and
    executed via a fresh
    :class:`~agent33.workflows.executor.WorkflowExecutor`.

    Uses a context variable to track nesting depth and prevent
    unbounded recursion (max depth: 10).

    Args:
        workflow_definition: A dict matching the WorkflowDefinition
            schema (must include ``name``, ``version``, ``steps``).
        inputs: Input data forwarded to the sub-workflow.
        dry_run: If True, log but skip actual execution.
        tenant_id: Tenant context inherited from the parent workflow.
        run_id: Traceable child run identifier for replay/checkpoint records.
        replay: Replay recorder inherited from the parent workflow executor.
        checkpoint_manager: Checkpoint manager inherited from the parent executor.
        hook_registry: Hook registry inherited from the parent executor.
        agent_registry: Agent registry inherited from the parent executor.
        model_router: Model router inherited from the parent executor.

    Returns:
        A dict with ``status``, ``outputs``, ``steps_executed``,
        and ``duration_ms``.

    Raises:
        ValueError: If *workflow_definition* is not provided.
        RuntimeError: If max nesting depth is exceeded.
    """
    if not workflow_definition:
        raise ValueError("sub-workflow action requires a 'workflow_definition'")

    current_depth = _nesting_depth.get()
    if current_depth >= _MAX_NESTING_DEPTH:
        raise RuntimeError(f"Sub-workflow nesting depth exceeded (max {_MAX_NESTING_DEPTH})")

    step_count = len(workflow_definition.get("steps", []))
    logger.info(
        "sub_workflow",
        step_count=step_count,
        nesting_depth=current_depth + 1,
        dry_run=dry_run,
    )

    if dry_run:
        return {"dry_run": True, "step_count": step_count}

    # Lazy imports to avoid circular dependency between workflows
    # and actions modules.
    from agent33.workflows.definition import WorkflowDefinition
    from agent33.workflows.executor import WorkflowExecutor

    token = _nesting_depth.set(current_depth + 1)
    try:
        sub_def = WorkflowDefinition(**workflow_definition)
        executor = WorkflowExecutor(
            sub_def,
            tenant_id=tenant_id,
            run_id=run_id,
            replay=replay,
            checkpoint_manager=checkpoint_manager,
            hook_registry=hook_registry,
            agent_registry=agent_registry,
            model_router=model_router,
        )
        result = await executor.execute(inputs or {})
    finally:
        _nesting_depth.reset(token)

    return {
        "status": result.status.value,
        "outputs": result.outputs,
        "steps_executed": result.steps_executed,
        "duration_ms": result.duration_ms,
    }
