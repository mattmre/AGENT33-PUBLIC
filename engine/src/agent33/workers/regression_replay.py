"""Regression replay worker job planning."""

from __future__ import annotations

from agent33.workers.queue import WorkerJob


def build_regression_replay_job(*, job_id: str = "regression-replay") -> WorkerJob:
    return WorkerJob(
        job_id=job_id,
        kind="regression-replay",
        payload={
            "golden_tasks": True,
            "tool_gateway_changes": True,
            "policy_changes": True,
            "workflow_recipes": True,
            "model_routing_changes": True,
            "resource_updates": True,
        },
    )
