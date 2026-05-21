"""Training API routes for rollouts, optimization, and metrics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/v1/training", tags=["training"])


class RolloutRequest(BaseModel):
    inputs: dict[str, Any]


class OptimizeRequest(BaseModel):
    current_prompt: str = ""
    iterations: int = 3


class RolloutResponse(BaseModel):
    rollout_id: str
    agent_name: str
    output: str
    reward: float
    span_count: int


class MetricsResponse(BaseModel):
    agent_name: str
    total_rollouts: int
    avg_reward: float
    latest_prompt_version: int | None = None


@router.post("/{agent}/rollout", response_model=RolloutResponse)
async def run_rollout(agent: str, req: RolloutRequest) -> RolloutResponse:
    """Run a single training rollout for an agent."""
    from agent33.main import app

    runner = getattr(app.state, "training_runner", None)
    if runner is None:
        raise HTTPException(503, "Training system not initialized")

    result = await runner.run_rollout(req.inputs)
    return RolloutResponse(**result)


@router.post("/{agent}/optimize")
async def optimize_agent(agent: str, req: OptimizeRequest) -> dict[str, Any]:
    """Trigger optimization loop for an agent."""
    from agent33.main import app

    optimizer = getattr(app.state, "agent_optimizer", None)
    if optimizer is None:
        raise HTTPException(503, "Training system not initialized")

    new_prompt = await optimizer.optimize(agent, req.current_prompt, iterations=req.iterations)
    return {"agent": agent, "new_prompt": new_prompt}


@router.get("/{agent}/rollouts")
async def list_rollouts(agent: str, limit: int = 50) -> dict[str, Any]:
    """List rollouts with rewards."""
    from agent33.main import app

    store = getattr(app.state, "training_store", None)
    if store is None:
        raise HTTPException(503, "Training system not initialized")

    rollouts = await store.get_rollouts(agent, limit=limit)
    return {"agent": agent, "rollouts": rollouts}


@router.get("/{agent}/metrics", response_model=MetricsResponse)
async def get_metrics(agent: str) -> MetricsResponse:
    """Get training metrics for an agent."""
    from agent33.main import app

    store = getattr(app.state, "training_store", None)
    if store is None:
        raise HTTPException(503, "Training system not initialized")

    rollouts = await store.get_rollouts(agent, limit=1000)
    avg_reward = (
        sum(r.get("total_reward", 0) for r in rollouts) / len(rollouts) if rollouts else 0.0
    )

    latest_prompt = await store.get_latest_prompt(agent)
    prompt_version = latest_prompt["version"] if latest_prompt else None

    return MetricsResponse(
        agent_name=agent,
        total_rollouts=len(rollouts),
        avg_reward=avg_reward,
        latest_prompt_version=prompt_version,
    )


@router.post("/{agent}/revert")
async def revert_prompt(agent: str) -> dict[str, Any]:
    """Revert to previous prompt version."""
    from agent33.main import app

    optimizer = getattr(app.state, "agent_optimizer", None)
    if optimizer is None:
        raise HTTPException(503, "Training system not initialized")

    prev = await optimizer.revert(agent)
    if prev is None:
        raise HTTPException(404, "No previous version to revert to")
    return {"agent": agent, "reverted_prompt": prev}
