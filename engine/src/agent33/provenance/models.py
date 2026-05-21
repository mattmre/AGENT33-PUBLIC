"""Provenance data models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ProvenanceSource(StrEnum):
    """Categories of provenance-worthy events."""

    SESSION_SPAWN = "session.spawn"
    TOOL_EXECUTION = "tool.execution"
    CONFIG_CHANGE = "config.change"
    PACK_INSTALL = "pack.install"
    BACKUP_CREATE = "backup.create"
    WORKFLOW_RUN = "workflow.run"


class ProvenanceReceipt(BaseModel):
    """Immutable record of a provenance-worthy event."""

    receipt_id: str = Field(default_factory=lambda: uuid4().hex)
    source: ProvenanceSource
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actor: str = ""
    tenant_id: str = ""
    session_id: str = ""
    trace_id: str = ""
    parent_receipt_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditTimelineEntry(BaseModel):
    """Single entry in a human-readable audit timeline."""

    timestamp: datetime
    source: ProvenanceSource
    actor: str
    summary: str
    receipt_id: str


class AuditBundle(BaseModel):
    """Exportable collection of audit timeline entries."""

    bundle_id: str
    created_at: datetime
    entries: list[AuditTimelineEntry]
    total_entries: int
    export_format: str = "json"
