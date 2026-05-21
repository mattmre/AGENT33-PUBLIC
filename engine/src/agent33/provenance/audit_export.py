"""Export provenance data as audit bundles.

Supports both the original :class:`AuditExporter` (works with
:class:`ProvenanceCollector`) and the new :class:`ReceiptExporter`
(works with :class:`ReceiptStore` and supports JSON/CSV output).
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic import BaseModel, Field

from agent33.provenance.models import AuditBundle, AuditTimelineEntry
from agent33.provenance.timeline import _summarize

if TYPE_CHECKING:
    from agent33.provenance.collector import ProvenanceCollector
    from agent33.provenance.receipts import ReceiptStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Original exporter (unchanged API)
# ---------------------------------------------------------------------------


class AuditExporter:
    """Creates exportable audit bundles from collected provenance receipts."""

    def __init__(self, collector: ProvenanceCollector) -> None:
        self._collector = collector

    def export(
        self,
        *,
        tenant_id: str = "",
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> AuditBundle:
        """Build and return an :class:`AuditBundle`.

        *since* and *until* bound the time window.  When *until* is supplied,
        a large ``limit`` is used and results are post-filtered.
        """
        # Fetch a generous upper bound; the deque is capped at max_receipts.
        receipts = self._collector.query(
            tenant_id=tenant_id,
            since=since,
            limit=self._collector._max_receipts,  # noqa: SLF001
        )

        if until is not None:
            receipts = [r for r in receipts if r.timestamp <= until]

        entries = [
            AuditTimelineEntry(
                timestamp=r.timestamp,
                source=r.source,
                actor=r.actor,
                summary=_summarize(r.source, r.metadata),
                receipt_id=r.receipt_id,
            )
            for r in receipts
        ]

        return AuditBundle(
            bundle_id=uuid4().hex,
            created_at=datetime.now(UTC),
            entries=entries,
            total_entries=len(entries),
        )


# ---------------------------------------------------------------------------
# Extended receipt export models
# ---------------------------------------------------------------------------


class ExportFormat(StrEnum):
    """Supported export output formats."""

    JSON = "json"
    CSV = "csv"


class ExportFilters(BaseModel):
    """Filter criteria for receipt exports."""

    since: datetime | None = None
    until: datetime | None = None
    entity_type: str | None = None
    actor: str = ""
    session_id: str = ""


class AuditExportRecord(BaseModel):
    """Record of a completed audit export."""

    export_id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    format: ExportFormat = ExportFormat.JSON
    filters: ExportFilters = Field(default_factory=ExportFilters)
    receipt_count: int = 0
    data: str = ""


# ---------------------------------------------------------------------------
# CSV column names
# ---------------------------------------------------------------------------

_CSV_COLUMNS = [
    "receipt_id",
    "entity_type",
    "entity_id",
    "tenant_id",
    "timestamp",
    "actor",
    "action",
    "inputs_hash",
    "outputs_hash",
    "parent_receipt_id",
    "session_id",
]


# ---------------------------------------------------------------------------
# Receipt exporter (new — works with ReceiptStore)
# ---------------------------------------------------------------------------


class ReceiptExporter:
    """Export :class:`HashedReceipt` data as JSON or CSV.

    Maintains an in-memory log of completed exports for retrieval.
    """

    def __init__(self, store: ReceiptStore) -> None:
        self._store = store
        self._exports: dict[str, AuditExportRecord] = {}

    def _fetch_receipts(self, filters: ExportFilters) -> list[dict[str, Any]]:
        """Query the store with *filters* and return dicts."""
        from agent33.provenance.receipts import EntityType as _EntityType

        entity_type: _EntityType | None = None
        if filters.entity_type:
            entity_type = _EntityType(filters.entity_type)

        receipts = self._store.list_all(
            entity_type=entity_type,
            actor=filters.actor,
            session_id=filters.session_id,
            since=filters.since,
            until=filters.until,
            limit=self._store._max_receipts,  # noqa: SLF001
        )
        return [r.model_dump(mode="json") for r in receipts]

    def export_json(self, filters: ExportFilters | None = None) -> AuditExportRecord:
        """Export filtered receipts as a JSON blob."""
        filters = filters or ExportFilters()
        rows = self._fetch_receipts(filters)
        data = json.dumps(rows, default=str, indent=2)
        record = AuditExportRecord(
            format=ExportFormat.JSON,
            filters=filters,
            receipt_count=len(rows),
            data=data,
        )
        self._exports[record.export_id] = record
        logger.info(
            "receipt_export_json",
            extra={"export_id": record.export_id, "count": record.receipt_count},
        )
        return record

    def export_csv(self, filters: ExportFilters | None = None) -> AuditExportRecord:
        """Export filtered receipts as a CSV string."""
        filters = filters or ExportFilters()
        rows = self._fetch_receipts(filters)

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        data = buf.getvalue()

        record = AuditExportRecord(
            format=ExportFormat.CSV,
            filters=filters,
            receipt_count=len(rows),
            data=data,
        )
        self._exports[record.export_id] = record
        logger.info(
            "receipt_export_csv",
            extra={"export_id": record.export_id, "count": record.receipt_count},
        )
        return record

    def get_export(self, export_id: str) -> AuditExportRecord | None:
        """Retrieve a previously completed export record."""
        return self._exports.get(export_id)
