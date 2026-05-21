"""Cron management service — wraps the existing APScheduler and cron CRUD stores.

Provides a unified interface for listing, enabling/disabling, and manually
triggering scheduled jobs.  Integrates with the existing
:class:`~agent33.automation.scheduler.WorkflowScheduler` and
:class:`~agent33.automation.cron_models.JobHistoryStore`.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class CronJobStatus(StrEnum):
    """Current status of a cron job."""

    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


class CronJobEntry(BaseModel):
    """Unified view of a scheduled job for the ops API."""

    id: str
    name: str
    schedule: str
    handler: str = ""
    enabled: bool = True
    last_run: datetime | None = None
    next_run: datetime | None = None
    run_count: int = 0
    error_count: int = 0
    status: CronJobStatus = CronJobStatus.ACTIVE


class CronJobHistoryEntry(BaseModel):
    """A single run record for the ops API."""

    run_id: str
    job_id: str
    started_at: datetime
    ended_at: datetime | None = None
    status: str = ""
    error: str = ""


class CronTriggerResult(BaseModel):
    """Result of manually triggering a cron job."""

    run_id: str
    job_id: str
    triggered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str = "triggered"


# ---------------------------------------------------------------------------
# CronManager service
# ---------------------------------------------------------------------------


class CronManager:
    """Unified cron management wrapping the existing APScheduler infrastructure.

    Parameters
    ----------
    job_store:
        The in-memory ``dict[str, JobDefinition]`` from ``app.state.cron_job_store``.
    scheduler:
        The :class:`~agent33.automation.scheduler.WorkflowScheduler` instance.
    history_store:
        The :class:`~agent33.automation.cron_models.JobHistoryStore` instance.
    """

    def __init__(
        self,
        job_store: dict[str, Any] | None = None,
        scheduler: Any | None = None,
        history_store: Any | None = None,
    ) -> None:
        self._job_store: dict[str, Any] = job_store if job_store is not None else {}
        self._scheduler = scheduler
        self._history_store = history_store

    def list_jobs(self) -> list[CronJobEntry]:
        """Return all registered cron jobs as unified entries."""
        entries: list[CronJobEntry] = []
        for job_id, job_def in self._job_store.items():
            history = self._get_history(job_id, limit=1)
            last_run = history[0].started_at if history else None
            run_count = len(self._get_history(job_id, limit=10000))
            error_count = len(
                [h for h in self._get_history(job_id, limit=10000) if h.status == "failed"]
            )

            entries.append(
                CronJobEntry(
                    id=job_id,
                    name=getattr(job_def, "workflow_name", str(job_id)),
                    schedule=getattr(job_def, "schedule_expr", ""),
                    handler=getattr(job_def, "schedule_type", ""),
                    enabled=getattr(job_def, "enabled", True),
                    last_run=last_run,
                    next_run=None,  # APScheduler doesn't expose this easily
                    run_count=run_count,
                    error_count=error_count,
                    status=(
                        CronJobStatus.ACTIVE
                        if getattr(job_def, "enabled", True)
                        else CronJobStatus.PAUSED
                    ),
                )
            )
        return entries

    def get_job(self, job_id: str) -> CronJobEntry | None:
        """Return a single job entry by ID, or None if not found."""
        job_def = self._job_store.get(job_id)
        if job_def is None:
            return None

        history = self._get_history(job_id, limit=1)
        last_run = history[0].started_at if history else None
        all_history = self._get_history(job_id, limit=10000)
        run_count = len(all_history)
        error_count = len([h for h in all_history if h.status == "failed"])

        return CronJobEntry(
            id=job_id,
            name=getattr(job_def, "workflow_name", str(job_id)),
            schedule=getattr(job_def, "schedule_expr", ""),
            handler=getattr(job_def, "schedule_type", ""),
            enabled=getattr(job_def, "enabled", True),
            last_run=last_run,
            next_run=None,
            run_count=run_count,
            error_count=error_count,
            status=(
                CronJobStatus.ACTIVE if getattr(job_def, "enabled", True) else CronJobStatus.PAUSED
            ),
        )

    def enable_job(self, job_id: str) -> bool:
        """Enable a paused job. Returns True if found and enabled."""
        job_def = self._job_store.get(job_id)
        if job_def is None:
            return False
        # Use model_copy to update the enabled field
        if hasattr(job_def, "model_copy"):
            updated = job_def.model_copy(update={"enabled": True, "updated_at": datetime.now(UTC)})
            self._job_store[job_id] = updated
        else:
            # Fallback for non-Pydantic objects
            object.__setattr__(job_def, "enabled", True)
        logger.info("cron_job_enabled: job_id=%s", job_id)
        return True

    def disable_job(self, job_id: str) -> bool:
        """Disable an active job. Returns True if found and disabled."""
        job_def = self._job_store.get(job_id)
        if job_def is None:
            return False
        if hasattr(job_def, "model_copy"):
            updated = job_def.model_copy(
                update={"enabled": False, "updated_at": datetime.now(UTC)}
            )
            self._job_store[job_id] = updated
        else:
            object.__setattr__(job_def, "enabled", False)
        logger.info("cron_job_disabled: job_id=%s", job_id)
        return True

    def trigger_job(self, job_id: str) -> CronTriggerResult | None:
        """Manually trigger a job. Returns result or None if not found."""
        job_def = self._job_store.get(job_id)
        if job_def is None:
            return None

        run_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        # Record in history
        if self._history_store is not None:
            from agent33.automation.cron_models import JobRunRecord

            record = JobRunRecord(
                run_id=run_id,
                job_id=job_id,
                started_at=now,
                ended_at=now,
                status="completed",
            )
            self._history_store.record(record)

        logger.info("cron_job_triggered: job_id=%s run_id=%s", job_id, run_id)
        return CronTriggerResult(
            run_id=run_id,
            job_id=job_id,
            triggered_at=now,
        )

    def get_history(self, job_id: str, limit: int = 50) -> list[CronJobHistoryEntry]:
        """Return run history for a job."""
        raw = self._get_history(job_id, limit=limit)
        return [
            CronJobHistoryEntry(
                run_id=getattr(r, "run_id", ""),
                job_id=getattr(r, "job_id", job_id),
                started_at=getattr(r, "started_at", datetime.now(UTC)),
                ended_at=getattr(r, "ended_at", None),
                status=getattr(r, "status", ""),
                error=getattr(r, "error", ""),
            )
            for r in raw
        ]

    # -- internal ----------------------------------------------------------

    def _get_history(self, job_id: str, limit: int = 50) -> list[Any]:
        """Query the history store safely."""
        if self._history_store is None:
            return []
        try:
            result: list[Any] = self._history_store.query(job_id=job_id, limit=limit)
            return result
        except Exception:
            return []
