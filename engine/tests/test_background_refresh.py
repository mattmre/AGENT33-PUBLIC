from __future__ import annotations

from agent33.workers.queue import WorkerJobStatus, WorkerQueue
from agent33.workers.refresh import build_background_refresh_jobs


def test_background_refresh_jobs_cover_doctor_resources_providers_and_routes() -> None:
    jobs = build_background_refresh_jobs(prefix="cycle-1")

    assert [job.kind for job in jobs] == [
        "doctor-snapshot",
        "resource-compatibility-refresh",
        "provider-health-refresh",
        "stale-route-detection",
    ]
    assert jobs[0].job_id == "cycle-1-doctor"


def test_background_refresh_jobs_can_be_enqueued_and_leased() -> None:
    queue = WorkerQueue()
    for job in build_background_refresh_jobs(prefix="cycle-1"):
        queue.enqueue(job)

    leased = queue.lease(owner="refresh-worker")

    assert leased is not None
    assert leased.kind == "doctor-snapshot"
    assert leased.status == WorkerJobStatus.LEASED
