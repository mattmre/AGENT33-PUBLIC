"""Memory/truth review worker job planning."""

from __future__ import annotations

from agent33.workers.queue import WorkerJob


def build_memory_truth_review_job(*, job_id: str = "memory-truth-review") -> WorkerJob:
    return WorkerJob(
        job_id=job_id,
        kind="memory-truth-review",
        payload={
            "review_low_confidence": True,
            "review_contradictions": True,
            "review_stale_facts": True,
            "review_unverified_claims": True,
        },
    )
