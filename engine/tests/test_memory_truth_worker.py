from __future__ import annotations

from agent33.workers.memory_truth import build_memory_truth_review_job
from agent33.workers.queue import WorkerQueue


def test_memory_truth_review_job_requests_all_review_classes() -> None:
    job = build_memory_truth_review_job(job_id="review-1")

    assert job.job_id == "review-1"
    assert job.kind == "memory-truth-review"
    assert job.payload == {
        "review_low_confidence": True,
        "review_contradictions": True,
        "review_stale_facts": True,
        "review_unverified_claims": True,
    }


def test_memory_truth_review_job_can_be_leased() -> None:
    queue = WorkerQueue()
    queue.enqueue(build_memory_truth_review_job())

    leased = queue.lease(owner="memory-worker")

    assert leased is not None
    assert leased.kind == "memory-truth-review"
