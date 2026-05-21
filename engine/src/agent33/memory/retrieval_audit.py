"""Audit records for memories/resources retrieved into a run."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class RetrievalUsefulness(StrEnum):
    HELPFUL = "helpful"
    STALE = "stale"
    CONTRADICTED = "contradicted"
    UNUSED = "unused"


class RetrievalAuditRecord(BaseModel):
    run_id: str
    item_id: str
    item_type: str
    usefulness: RetrievalUsefulness = RetrievalUsefulness.UNUSED
    evidence_uri: str = ""
    notes: list[str] = Field(default_factory=list)


class RetrievalAuditLog:
    def __init__(self) -> None:
        self._records: list[RetrievalAuditRecord] = []

    def record(self, item: RetrievalAuditRecord) -> RetrievalAuditRecord:
        self._records.append(item)
        return item

    def list_for_run(self, run_id: str) -> list[RetrievalAuditRecord]:
        return [record for record in self._records if record.run_id == run_id]
