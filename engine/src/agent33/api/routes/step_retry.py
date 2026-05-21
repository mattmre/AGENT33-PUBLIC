"""Per-step retry route — POST /v1/workflows/{run_id}/steps/{step_id}/retry."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/workflows", tags=["step-retry"])


class StepRetryRequest(BaseModel):
    """Payload for retrying a single workflow step."""

    action: str
    """StepAction value, e.g. ``"validate"``, ``"transform"``, ``"run_command"``."""
    inputs: dict[str, Any] = {}
    """Resolved inputs passed directly to the action handler."""
    state: dict[str, Any] = {}
    """Execution state snapshot to use as initial context."""


@router.post(
    "/{run_id}/steps/{step_id}/retry",
    dependencies=[require_scope("operator:write")],
)
async def retry_workflow_step(
    run_id: str,
    step_id: str,
    body: StepRetryRequest,
    request: Request,
) -> dict[str, Any]:
    """Re-run a single workflow step with the provided inputs.

    Builds a minimal one-step ``WorkflowDefinition`` and executes it through
    the normal ``WorkflowExecutor`` pipeline so that hooks and retry logic are
    honoured.  The step result is returned directly.
    """
    from agent33.workflows.definition import StepAction, WorkflowDefinition, WorkflowStep
    from agent33.workflows.executor import WorkflowExecutor

    try:
        action_enum = StepAction(body.action)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown step action '{body.action}'. Valid values: "
            + ", ".join(a.value for a in StepAction),
        ) from exc

    step = WorkflowStep(id=step_id, action=action_enum, inputs=body.inputs)
    definition = WorkflowDefinition(
        name="step-retry",
        version="1.0.0",
        steps=[step],
    )
    retry_run_id = f"{run_id}-step-retry-{step_id}-{uuid4().hex}"[-128:]
    execution_replay = getattr(request.app.state, "execution_replay", None)
    checkpoint_manager = getattr(request.app.state, "checkpoint_manager", None)
    retry_state = dict(body.state)
    retry_state["__retry_metadata"] = {
        "parent_run_id": run_id,
        "step_id": step_id,
        "retry_run_id": retry_run_id,
    }
    executor = WorkflowExecutor(
        definition=definition,
        agent_registry=getattr(request.app.state, "agent_registry", None),
        model_router=getattr(request.app.state, "model_router", None),
        run_id=retry_run_id,
        replay=execution_replay,
        checkpoint_manager=checkpoint_manager,
        resume_from_checkpoint=False,
    )
    result = await executor.execute(inputs=retry_state)
    sr = result.step_results[0] if result.step_results else None
    return {
        "run_id": run_id,
        "retry_run_id": retry_run_id,
        "step_id": step_id,
        "status": sr.status if sr else "failed",
        "outputs": sr.outputs if sr else {},
        "error": sr.error if sr else "no steps executed",
        "duration_ms": sr.duration_ms if sr else 0.0,
        "replay_enabled": execution_replay is not None,
        "checkpoint_enabled": checkpoint_manager is not None,
    }
