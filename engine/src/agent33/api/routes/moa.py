"""FastAPI router for Mixture-of-Agents (MoA) workflow endpoints.

Provides dedicated API routes for building, estimating, and executing MoA
workflows.  This is a thin API layer over the ``mixture_of_agents`` template
builder (Phase 58).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agent33.security.permissions import require_scope
from agent33.workflows.executor import WorkflowExecutor
from agent33.workflows.templates.mixture_of_agents import (
    build_moa_workflow,
    estimate_moa_cost,
    format_moa_result,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/moa", tags=["moa"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class MoABuildRequest(BaseModel):
    """Request body for building a MoA workflow definition."""

    query: str = Field(..., min_length=1, description="The user query to answer.")
    reference_models: list[str] = Field(
        ..., min_length=1, description="Model IDs for the parallel proposer layer."
    )
    aggregator_model: str = Field(..., min_length=1, description="Model ID for the aggregator.")
    reference_temperature: float = Field(
        default=0.6, ge=0.0, le=2.0, description="Base temperature for proposers."
    )
    aggregator_temperature: float = Field(
        default=0.4, ge=0.0, le=2.0, description="Temperature for the aggregator."
    )
    rounds: int = Field(default=1, ge=1, le=5, description="Number of proposer rounds.")
    temperature_diversity: bool = Field(
        default=False, description="Spread temperatures across proposers."
    )
    temperature_spread: float = Field(
        default=0.3, ge=0.0, le=1.0, description="Half-range for temperature diversity."
    )


class MoAExecuteRequest(MoABuildRequest):
    """Request body for building and executing a MoA workflow."""

    tenant_id: str = Field(default="", description="Tenant ID for execution context.")


class MoACostRequest(BaseModel):
    """Request body for estimating MoA workflow cost."""

    query: str = Field(..., min_length=1, description="The user query.")
    reference_models: list[str] = Field(
        ..., min_length=1, description="Model IDs for the proposer layer."
    )
    aggregator_model: str = Field(..., min_length=1, description="Model ID for the aggregator.")
    rounds: int = Field(default=1, ge=1, le=5, description="Number of proposer rounds.")
    provider: str = Field(default="openai", description="Default provider for pricing lookup.")
    proposer_output_tokens: int = Field(
        default=500, ge=1, description="Estimated output tokens per proposer."
    )
    aggregator_output_tokens: int = Field(
        default=800, ge=1, description="Estimated output tokens for aggregator."
    )


class MoACostResponse(BaseModel):
    """Response body for cost estimation."""

    total_usd: str
    proposer_count: int
    rounds: int
    aggregator_model: str
    status: str
    step_count: int
    per_step_costs: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/build", dependencies=[require_scope("workflows:write")])
async def build_workflow(req: MoABuildRequest) -> dict[str, Any]:
    """Build a MoA workflow definition without executing it.

    Returns the full workflow definition as JSON, ready for registration in
    the workflow registry or direct execution.
    """
    try:
        wf = build_moa_workflow(
            query=req.query,
            reference_models=req.reference_models,
            aggregator_model=req.aggregator_model,
            reference_temperature=req.reference_temperature,
            aggregator_temperature=req.aggregator_temperature,
            rounds=req.rounds,
            temperature_diversity=req.temperature_diversity,
            temperature_spread=req.temperature_spread,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "moa_workflow_built",
        step_count=len(wf.steps),
        rounds=req.rounds,
        temperature_diversity=req.temperature_diversity,
    )
    return {
        "workflow": wf.model_dump(mode="json"),
        "step_count": len(wf.steps),
        "rounds": req.rounds,
    }


@router.post("/estimate", dependencies=[require_scope("workflows:read")])
async def estimate_cost(req: MoACostRequest) -> MoACostResponse:
    """Estimate the cost of a MoA workflow before execution.

    Uses the PricingCatalog (Phase 49) to compute per-step and total cost
    estimates based on query length and assumed output token counts.
    """
    try:
        cost = estimate_moa_cost(
            query=req.query,
            reference_models=req.reference_models,
            aggregator_model=req.aggregator_model,
            rounds=req.rounds,
            provider=req.provider,
            proposer_output_tokens=req.proposer_output_tokens,
            aggregator_output_tokens=req.aggregator_output_tokens,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "moa_cost_estimated",
        total_usd=str(cost.total_usd),
        proposer_count=cost.proposer_count,
        rounds=cost.rounds,
    )

    return MoACostResponse(
        total_usd=str(cost.total_usd),
        proposer_count=cost.proposer_count,
        rounds=cost.rounds,
        aggregator_model=cost.aggregator_model,
        status=cost.status.value,
        step_count=len(cost.per_step),
        per_step_costs=[
            {
                "model": c.model,
                "provider": c.provider,
                "amount_usd": str(c.amount_usd),
                "input_tokens": c.input_tokens,
                "output_tokens": c.output_tokens,
                "status": c.status.value,
            }
            for c in cost.per_step
        ],
    )


@router.post("/execute", dependencies=[require_scope("workflows:execute")])
async def execute_workflow(req: MoAExecuteRequest, request: Request) -> dict[str, Any]:
    """Build and execute a MoA workflow, returning the aggregated response.

    This is an end-to-end convenience endpoint that builds the workflow
    definition, executes it through the standard WorkflowExecutor, and
    returns the aggregated result.
    """
    try:
        wf = build_moa_workflow(
            query=req.query,
            reference_models=req.reference_models,
            aggregator_model=req.aggregator_model,
            reference_temperature=req.reference_temperature,
            aggregator_temperature=req.aggregator_temperature,
            rounds=req.rounds,
            temperature_diversity=req.temperature_diversity,
            temperature_spread=req.temperature_spread,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    run_id = f"moa-{uuid4().hex}"
    execution_replay = getattr(request.app.state, "execution_replay", None)
    checkpoint_manager = getattr(request.app.state, "checkpoint_manager", None)
    executor = WorkflowExecutor(
        definition=wf,
        tenant_id=req.tenant_id,
        run_id=run_id,
        replay=execution_replay,
        checkpoint_manager=checkpoint_manager,
    )

    try:
        result = await executor.execute()
    except Exception as exc:
        logger.error("moa_execute_error", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail=f"MoA workflow execution failed: {exc}",
        ) from exc

    if result.status.value == "failed":
        error_msgs = [sr.error for sr in result.step_results if sr.error]
        raise HTTPException(
            status_code=502,
            detail=f"MoA workflow failed: {'; '.join(error_msgs) or 'unknown error'}",
        )

    aggregated = format_moa_result(result.outputs)

    logger.info(
        "moa_workflow_executed",
        status=result.status.value,
        steps_executed=len(result.steps_executed),
        duration_ms=result.duration_ms,
        rounds=req.rounds,
        run_id=run_id,
        replay_enabled=execution_replay is not None,
        checkpoint_enabled=checkpoint_manager is not None,
    )

    return {
        "run_id": run_id,
        "result": aggregated,
        "status": result.status.value,
        "steps_executed": result.steps_executed,
        "duration_ms": result.duration_ms,
        "rounds": req.rounds,
        "reference_models": req.reference_models,
        "aggregator_model": req.aggregator_model,
        "replay_enabled": execution_replay is not None,
        "checkpoint_enabled": checkpoint_manager is not None,
    }
