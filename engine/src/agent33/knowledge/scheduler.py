"""APScheduler-based cron scheduler for periodic knowledge ingestion."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class KnowledgeIngestionScheduler:
    """Manages APScheduler jobs for periodic knowledge source ingestion.

    Each knowledge source gets its own cron job. The scheduler delegates
    the actual ingestion to a callback, which is typically
    :meth:`KnowledgeIngestionService.ingest_source`.
    """

    def __init__(
        self,
        on_ingest: Callable[[str], Awaitable[Any]],
    ) -> None:
        self._scheduler = AsyncIOScheduler()
        self._on_ingest = on_ingest

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        """Start the APScheduler event loop."""
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("KnowledgeIngestionScheduler started")

    def stop(self) -> None:
        """Shut down the APScheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("KnowledgeIngestionScheduler stopped")

    @property
    def running(self) -> bool:
        """Return True if the underlying scheduler is running."""
        return bool(self._scheduler.running)

    # -- job management -------------------------------------------------------

    def add_source(self, source_id: str, cron_expression: str) -> None:
        """Schedule periodic ingestion for a knowledge source.

        Parameters
        ----------
        source_id:
            Unique identifier for the knowledge source.
        cron_expression:
            Standard 5-field cron expression (minute hour day month day_of_week).
        """
        parts = cron_expression.strip().split()
        if len(parts) != 5:  # noqa: PLR2004
            msg = f"Expected 5-field cron expression, got: {cron_expression!r}"
            raise ValueError(msg)

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )

        job_id = f"knowledge_{source_id}"

        # Remove existing job if present (idempotent re-add)
        existing = self._scheduler.get_job(job_id)
        if existing is not None:
            self._scheduler.remove_job(job_id)

        self._scheduler.add_job(
            self._execute_ingest,
            trigger=trigger,
            id=job_id,
            args=[source_id],
            misfire_grace_time=300,  # 5 min grace period
        )
        logger.info("Scheduled knowledge ingestion job %s: %s", job_id, cron_expression)

    def remove_source(self, source_id: str) -> None:
        """Remove the scheduled ingestion job for a source."""
        job_id = f"knowledge_{source_id}"
        existing = self._scheduler.get_job(job_id)
        if existing is not None:
            self._scheduler.remove_job(job_id)
            logger.info("Removed knowledge ingestion job %s", job_id)

    def has_job(self, source_id: str) -> bool:
        """Return True if a job exists for the given source."""
        return self._scheduler.get_job(f"knowledge_{source_id}") is not None

    def list_jobs(self) -> list[str]:
        """Return the list of active job IDs."""
        return [job.id for job in self._scheduler.get_jobs()]

    async def _execute_ingest(self, source_id: str) -> None:
        """Execute the ingestion callback, swallowing errors to protect the scheduler."""
        try:
            await self._on_ingest(source_id)
        except Exception:
            logger.exception("Knowledge ingestion failed for source %s", source_id)
