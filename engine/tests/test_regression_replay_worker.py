from __future__ import annotations

from agent33.workers.queue import WorkerQueue
from agent33.workers.regression_replay import build_regression_replay_job


def test_regression_replay_job_covers_expected_replay_classes() -> None:
    job = build_regression_replay_job(job_id="replay-1")

    assert job.job_id == "replay-1"
    assert job.kind == "regression-replay"
    assert job.payload["golden_tasks"] is True
    assert job.payload["tool_gateway_changes"] is True
    assert job.payload["policy_changes"] is True
    assert job.payload["workflow_recipes"] is True
    assert job.payload["model_routing_changes"] is True
    assert job.payload["resource_updates"] is True


def test_regression_replay_job_can_be_queued() -> None:
    queue = WorkerQueue()
    queue.enqueue(build_regression_replay_job())

    assert queue.lease(owner="replay-worker") is not None
