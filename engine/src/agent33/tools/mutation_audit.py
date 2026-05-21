"""Durable audit trail for governed file mutations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, ValidationError

if TYPE_CHECKING:
    from agent33.services.orchestration_state import OrchestrationStateStore


def _new_mutation_id() -> str:
    return f"MUT-{uuid.uuid4().hex[:12]}"


class MutationAuditFileRecord(BaseModel):
    """Per-file details for a mutation attempt."""

    action: str
    path: str
    new_path: str = ""
    added_lines: int = 0
    removed_lines: int = 0
    before_sha256: str = ""
    after_sha256: str = ""


class MutationAuditRecord(BaseModel):
    """Single mutation audit record."""

    mutation_id: str = Field(default_factory=_new_mutation_id)
    tool_name: str = "apply_patch"
    requested_by: str = ""
    tenant_id: str = ""
    dry_run: bool = False
    status: str = "applied"
    success: bool = True
    summary: str = ""
    error: str = ""
    approval_id: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    files: list[MutationAuditFileRecord] = Field(default_factory=list)


class MutationAuditStore:
    """In-memory audit store with optional durable namespace backing."""

    _NAMESPACE = "tool_mutations"

    def __init__(
        self,
        state_store: OrchestrationStateStore | None = None,
        *,
        max_records: int = 1000,
    ) -> None:
        self._state_store = state_store
        self._max_records = max(1, max_records)
        self._records: list[MutationAuditRecord] = []
        self._load_state()

    def record(self, record: MutationAuditRecord) -> MutationAuditRecord:
        """Append and persist a mutation record."""
        self._records.append(record)
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records :]
        self._persist_state()
        return record

    def list_records(self, *, tenant_id: str = "", limit: int = 100) -> list[MutationAuditRecord]:
        """Return newest-first records, optionally filtered by tenant."""
        items = list(self._records)
        if tenant_id:
            items = [item for item in items if item.tenant_id == tenant_id]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[: max(1, limit)]

    def get_record(self, mutation_id: str, *, tenant_id: str = "") -> MutationAuditRecord | None:
        """Return a single record by ID, respecting tenant filtering."""
        for record in self._records:
            if record.mutation_id != mutation_id:
                continue
            if tenant_id and record.tenant_id != tenant_id:
                return None
            return record
        return None

    def _persist_state(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            self._NAMESPACE,
            {"records": [record.model_dump(mode="json") for record in self._records]},
        )

    def _load_state(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace(self._NAMESPACE)
        records_payload = payload.get("records", [])
        if not isinstance(records_payload, list):
            return
        loaded: list[MutationAuditRecord] = []
        for item in records_payload:
            try:
                loaded.append(MutationAuditRecord.model_validate(item))
            except ValidationError:
                continue
        self._records = loaded[-self._max_records :]
