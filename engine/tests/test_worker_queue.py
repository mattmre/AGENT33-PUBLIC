from __future__ import annotations

from agent33.workers.queue import WorkerJob, WorkerJobStatus, WorkerQueue


def test_worker_queue_leases_and_completes_job() -> None:
    queue = WorkerQueue()
    queue.enqueue(WorkerJob(job_id="job-1", kind="doctor-refresh"))

    leased = queue.lease(owner="worker-a")

    assert leased is not None
    assert leased.status == WorkerJobStatus.LEASED
    assert leased.owner == "worker-a"
    assert leased.attempts == 1
    completed = queue.complete("job-1", {"ok": True})
    assert completed is not None
    assert completed.status == WorkerJobStatus.COMPLETED
    assert completed.result == {"ok": True}


def test_worker_queue_dead_letters_after_max_attempts() -> None:
    queue = WorkerQueue()
    queue.enqueue(WorkerJob(job_id="job-1", kind="replay", max_attempts=1))
    assert queue.lease(owner="worker-a") is not None

    failed = queue.fail("job-1", "boom")

    assert failed is not None
    assert failed.status == WorkerJobStatus.DEAD_LETTER
    assert failed.error == "boom"


def test_worker_queue_cancels_job() -> None:
    queue = WorkerQueue()
    queue.enqueue(WorkerJob(job_id="job-1", kind="memory-review"))

    cancelled = queue.cancel("job-1")

    assert cancelled is not None
    assert cancelled.status == WorkerJobStatus.CANCELLED
