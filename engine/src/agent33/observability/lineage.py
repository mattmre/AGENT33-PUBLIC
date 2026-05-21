"""Execution lineage tracking for workflow steps."""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent33.services.orchestration_state import OrchestrationStateStore

logger = logging.getLogger(__name__)

_NAMESPACE = "execution_lineage"


@dataclass
class LineageRecord:
    """Single lineage entry for one workflow step."""

    workflow_id: str
    step_id: str
    action: str
    inputs_hash: str
    outputs_hash: str
    parent_id: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class ExecutionLineage:
    """Records and queries execution lineage for workflows."""

    def __init__(self, state_store: OrchestrationStateStore | None = None) -> None:
        self._records: list[LineageRecord] = []
        self._state_store = state_store
        if state_store is None:
            logger.warning(
                "execution_lineage_no_state_store: records will not persist across restarts"
            )
        self._load_state()

    def _persist_state(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            _NAMESPACE,
            {"records": [dataclasses.asdict(r) for r in self._records]},
        )

    def _load_state(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace(_NAMESPACE)
        records_data = payload.get("records", [])
        if not isinstance(records_data, list):
            return
        for item in records_data:
            if not isinstance(item, dict):
                continue
            try:
                self._records.append(LineageRecord(**item))
            except Exception as exc:
                logger.warning("lineage_record_restore_failed: %s", exc)

    def record(
        self,
        workflow_id: str,
        step_id: str,
        action: str,
        inputs_hash: str,
        outputs_hash: str,
        parent_id: str | None = None,
    ) -> LineageRecord:
        """Record a lineage entry and return it."""
        entry = LineageRecord(
            workflow_id=workflow_id,
            step_id=step_id,
            action=action,
            inputs_hash=inputs_hash,
            outputs_hash=outputs_hash,
            parent_id=parent_id,
        )
        self._records.append(entry)
        self._persist_state()
        return entry

    def query(self, workflow_id: str) -> list[LineageRecord]:
        """Return all lineage records for a workflow."""
        return [r for r in self._records if r.workflow_id == workflow_id]
