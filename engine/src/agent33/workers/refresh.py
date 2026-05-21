"""Background refresh job planning for doctor, resources, and providers."""

from __future__ import annotations

from agent33.workers.queue import WorkerJob


def build_background_refresh_jobs(*, prefix: str = "refresh") -> list[WorkerJob]:
    return [
        WorkerJob(job_id=f"{prefix}-doctor", kind="doctor-snapshot"),
        WorkerJob(job_id=f"{prefix}-resources", kind="resource-compatibility-refresh"),
        WorkerJob(job_id=f"{prefix}-providers", kind="provider-health-refresh"),
        WorkerJob(job_id=f"{prefix}-routes", kind="stale-route-detection"),
    ]
