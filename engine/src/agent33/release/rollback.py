"""Rollback tracking and decision matrix.

Implements rollback procedures from ``core/orchestrator/RELEASE_CADENCE.md``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agent33.release.models import (
    RollbackRecord,
    RollbackStatus,
    RollbackType,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# Rollback decision matrix from RELEASE_CADENCE.md
# Maps (severity, impact) to recommended rollback type and approval level
_DECISION_MATRIX: dict[tuple[str, str], tuple[RollbackType, str]] = {
    ("critical", "high"): (RollbackType.IMMEDIATE, "on-call"),
    ("critical", "medium"): (RollbackType.IMMEDIATE, "on-call"),
    ("critical", "low"): (RollbackType.PLANNED, "team-lead"),
    ("high", "high"): (RollbackType.IMMEDIATE, "team-lead"),
    ("high", "medium"): (RollbackType.PLANNED, "team-lead"),
    ("high", "low"): (RollbackType.PLANNED, "team-lead"),
    ("medium", "high"): (RollbackType.PLANNED, "team-lead"),
    ("medium", "medium"): (RollbackType.PARTIAL, "team-lead"),
    ("medium", "low"): (RollbackType.CONFIG, "engineer"),
    ("low", "high"): (RollbackType.PARTIAL, "engineer"),
    ("low", "medium"): (RollbackType.CONFIG, "engineer"),
    ("low", "low"): (RollbackType.CONFIG, "engineer"),
}


class RollbackManager:
    """Track and manage rollbacks."""

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        self._records: dict[str, RollbackRecord] = {}
        self._on_change = on_change

    def _mark_changed(self) -> None:
        if self._on_change is not None:
            self._on_change()

    # ------------------------------------------------------------------
    # State snapshot / restore (used by durable persistence)
    # ------------------------------------------------------------------

    def snapshot_state(self) -> dict[str, dict[str, object]]:
        """Return a serializable snapshot of internal state."""
        return {
            "records": {
                rollback_id: record.model_dump(mode="json")
                for rollback_id, record in self._records.items()
            },
        }

    def restore_state(self, data: dict[str, object]) -> None:
        """Restore internal state from a previously captured snapshot."""
        from pydantic import ValidationError

        records_payload = data.get("records", {})
        if isinstance(records_payload, dict):
            for rollback_id, record_data in records_payload.items():
                if not isinstance(rollback_id, str):
                    continue
                try:
                    self._records[rollback_id] = RollbackRecord.model_validate(record_data)
                except ValidationError:
                    logger.warning("rollback_restore_failed id=%s", rollback_id)

    def recommend(self, severity: str, impact: str) -> tuple[RollbackType, str]:
        """Get recommended rollback type and approval level.

        Args:
            severity: critical, high, medium, low
            impact: high, medium, low

        Returns:
            (rollback_type, approval_level)
        """
        key = (severity.lower(), impact.lower())
        return _DECISION_MATRIX.get(key, (RollbackType.PLANNED, "team-lead"))

    def create(
        self,
        release_id: str,
        reason: str,
        rollback_type: RollbackType = RollbackType.PLANNED,
        target_version: str = "",
        initiated_by: str = "",
    ) -> RollbackRecord:
        """Create a rollback record."""
        record = RollbackRecord(
            release_id=release_id,
            rollback_type=rollback_type,
            reason=reason,
            target_version=target_version,
            initiated_by=initiated_by,
        )
        self._records[record.rollback_id] = record
        self._mark_changed()
        logger.info(
            "rollback_created id=%s release=%s type=%s",
            record.rollback_id,
            release_id,
            rollback_type.value,
        )
        return record

    def approve(self, rollback_id: str, approved_by: str) -> RollbackRecord | None:
        """Approve a rollback."""
        record = self._records.get(rollback_id)
        if record is None:
            return None
        record.approved_by = approved_by
        record.status = RollbackStatus.IN_PROGRESS
        self._mark_changed()
        return record

    def complete_step(self, rollback_id: str, step_description: str) -> RollbackRecord | None:
        """Record completion of a rollback step."""
        record = self._records.get(rollback_id)
        if record is None:
            return None
        record.steps_completed.append(step_description)
        self._mark_changed()
        return record

    def complete(self, rollback_id: str) -> RollbackRecord | None:
        """Mark a rollback as completed."""
        record = self._records.get(rollback_id)
        if record is None:
            return None
        record.status = RollbackStatus.COMPLETED
        record.completed_at = datetime.now(UTC)
        self._mark_changed()
        logger.info("rollback_completed id=%s", rollback_id)
        return record

    def fail(self, rollback_id: str, error: str) -> RollbackRecord | None:
        """Mark a rollback as failed."""
        record = self._records.get(rollback_id)
        if record is None:
            return None
        record.status = RollbackStatus.FAILED
        record.errors.append(error)
        self._mark_changed()
        return record

    def get(self, rollback_id: str) -> RollbackRecord | None:
        return self._records.get(rollback_id)

    def list_all(
        self,
        release_id: str | None = None,
        status: RollbackStatus | None = None,
        limit: int = 50,
    ) -> list[RollbackRecord]:
        results = list(self._records.values())
        if release_id is not None:
            results = [r for r in results if r.release_id == release_id]
        if status is not None:
            results = [r for r in results if r.status == status]
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]
