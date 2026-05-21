"""Cron CRUD models and job history store for Track 9 Operations."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DeliveryMode(StrEnum):
    """How a scheduled job delivers its result."""

    DIRECT = "direct"
    WEBHOOK = "webhook"


class JobDefinition(BaseModel):
    """A scheduled workflow job definition with CRUD semantics."""

    job_id: str
    workflow_name: str
    schedule_type: str  # "cron" | "interval"
    schedule_expr: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    delivery_mode: DeliveryMode = DeliveryMode.DIRECT
    webhook_url: str = ""
    agent_override: str = ""
    model_override: str = ""
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class JobRunRecord(BaseModel):
    """Record of a single job execution."""

    run_id: str
    job_id: str
    started_at: datetime
    ended_at: datetime | None = None
    status: str  # "running" | "completed" | "failed" | "skipped"
    error: str = ""


class JobHistoryStore:
    """In-memory store for job run records with per-job retention limits.

    Thread-safety is not required since the scheduler runs on the asyncio
    event loop.
    """

    def __init__(self, max_records_per_job: int = 100) -> None:
        self._max_records = max_records_per_job
        self._records: dict[str, list[JobRunRecord]] = defaultdict(list)

    def record(self, run: JobRunRecord) -> None:
        """Store a run record, evicting the oldest when the limit is exceeded."""
        records = self._records[run.job_id]
        records.append(run)
        if len(records) > self._max_records:
            self._records[run.job_id] = records[-self._max_records :]

    def query(
        self,
        job_id: str,
        limit: int = 50,
        status: str | None = None,
    ) -> list[JobRunRecord]:
        """Return run records for a job, optionally filtered by status.

        Results are returned most-recent-first.
        """
        records = self._records.get(job_id, [])
        if status is not None:
            records = [r for r in records if r.status == status]
        # Most recent first
        return list(reversed(records))[:limit]

    @property
    def all_job_ids(self) -> list[str]:
        """Return all job IDs that have run history."""
        return list(self._records.keys())
