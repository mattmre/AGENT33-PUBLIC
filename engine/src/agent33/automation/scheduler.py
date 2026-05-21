"""Workflow scheduler using APScheduler for cron and interval triggers."""

from __future__ import annotations

import dataclasses
import logging
import uuid
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

if TYPE_CHECKING:
    from agent33.automation.scheduler_repository import SchedulerJobRepository

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, slots=True)
class ScheduledJob:
    """Metadata for a scheduled workflow job."""

    job_id: str
    workflow_name: str
    schedule_type: str
    schedule_expr: str
    inputs: dict[str, Any]


class WorkflowScheduler:
    """Schedules workflow executions via cron expressions or fixed intervals.

    Job metadata is delegated to a :class:`SchedulerJobRepository` so that
    storage can be swapped between in-memory (default) and database-backed
    implementations for multi-replica safety.

    A callback must be provided at construction time; it is invoked with
    ``(job_id, workflow_name, inputs)`` whenever a job fires.
    """

    def __init__(
        self,
        on_trigger: Any | None = None,
        job_repository: SchedulerJobRepository | None = None,
    ) -> None:
        from agent33.automation.scheduler_repository import get_scheduler_job_repository

        self._scheduler = AsyncIOScheduler()
        self._job_repo = job_repository or get_scheduler_job_repository()
        self._on_trigger = on_trigger

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        """Start the underlying APScheduler."""
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("WorkflowScheduler started")

    def stop(self) -> None:
        """Shut down the underlying APScheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("WorkflowScheduler stopped")

    # -- scheduling -----------------------------------------------------------

    def schedule_cron(
        self,
        workflow_name: str,
        cron_expr: str,
        inputs: dict[str, Any] | None = None,
    ) -> str:
        """Schedule a workflow to run on a cron expression.

        The *cron_expr* follows the standard five-field format:
        ``minute hour day month day_of_week``.

        Returns the generated job ID.
        """
        inputs = inputs or {}
        job_id = str(uuid.uuid4())
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Expected 5-field cron expression, got: {cron_expr!r}")

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )

        self._scheduler.add_job(
            self._execute,
            trigger=trigger,
            id=job_id,
            args=[job_id, workflow_name, inputs],
        )

        self._job_repo.add_job(
            ScheduledJob(
                job_id=job_id,
                workflow_name=workflow_name,
                schedule_type="cron",
                schedule_expr=cron_expr,
                inputs=inputs,
            )
        )
        logger.info("Scheduled cron job %s for workflow %s", job_id, workflow_name)
        return job_id

    def schedule_interval(
        self,
        workflow_name: str,
        seconds: int,
        inputs: dict[str, Any] | None = None,
    ) -> str:
        """Schedule a workflow to run at a fixed interval.

        Returns the generated job ID.
        """
        inputs = inputs or {}
        job_id = str(uuid.uuid4())

        trigger = IntervalTrigger(seconds=seconds)

        self._scheduler.add_job(
            self._execute,
            trigger=trigger,
            id=job_id,
            args=[job_id, workflow_name, inputs],
        )

        self._job_repo.add_job(
            ScheduledJob(
                job_id=job_id,
                workflow_name=workflow_name,
                schedule_type="interval",
                schedule_expr=f"{seconds}s",
                inputs=inputs,
            )
        )
        logger.info("Scheduled interval job %s for workflow %s", job_id, workflow_name)
        return job_id

    def remove(self, job_id: str) -> bool:
        """Remove a scheduled job by ID. Returns True if the job existed."""
        if self._job_repo.get_job(job_id) is None:
            return False
        self._scheduler.remove_job(job_id)
        self._job_repo.remove_job(job_id)
        logger.info("Removed scheduled job %s", job_id)
        return True

    def list_jobs(self) -> list[ScheduledJob]:
        """Return all registered scheduled jobs."""
        return self._job_repo.list_jobs()

    # -- internal -------------------------------------------------------------

    async def _execute(self, job_id: str, workflow_name: str, inputs: dict[str, Any]) -> None:
        """Fire the callback when a scheduled job triggers."""
        logger.info("Triggering scheduled workflow %s (%s)", workflow_name, job_id)
        if self._on_trigger is not None:
            await self._on_trigger(job_id, workflow_name, inputs)
