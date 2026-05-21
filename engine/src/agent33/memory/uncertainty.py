"""Memory uncertainty and contradiction ledger."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class MemoryTruthState(StrEnum):
    INFERRED = "inferred"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"
    CONTRADICTED = "contradicted"


class MemoryTruthRecord(BaseModel):
    memory_id: str
    state: MemoryTruthState
    evidence_uri: str = ""
    related_memory_ids: list[str] = Field(default_factory=list)
    note: str = ""


class MemoryTruthLedger:
    def __init__(self) -> None:
        self._records: list[MemoryTruthRecord] = []

    def record(self, item: MemoryTruthRecord) -> MemoryTruthRecord:
        self._records.append(item)
        return item

    def list_records(self, *, state: MemoryTruthState | None = None) -> list[MemoryTruthRecord]:
        records = list(self._records)
        if state is not None:
            records = [record for record in records if record.state == state]
        return records

    def contradictions_for(self, memory_id: str) -> list[MemoryTruthRecord]:
        return [
            record
            for record in self._records
            if record.state == MemoryTruthState.CONTRADICTED
            and (record.memory_id == memory_id or memory_id in record.related_memory_ids)
        ]
