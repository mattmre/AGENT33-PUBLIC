"""Build a human-readable audit timeline from provenance receipts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent33.provenance.models import AuditTimelineEntry, ProvenanceSource

if TYPE_CHECKING:
    from datetime import datetime

    from agent33.provenance.collector import ProvenanceCollector


def _summarize(source: ProvenanceSource, metadata: dict[str, object]) -> str:
    """Generate a one-line summary for a receipt."""
    label = source.value.replace(".", " ").title()
    detail = metadata.get("summary") or metadata.get("name") or metadata.get("tool_id") or ""
    if detail:
        return f"{label}: {detail}"
    return label


class AuditTimelineService:
    """Transforms raw provenance receipts into ordered timeline entries."""

    def __init__(self, collector: ProvenanceCollector) -> None:
        self._collector = collector

    def build(
        self,
        *,
        tenant_id: str = "",
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditTimelineEntry]:
        """Return timeline entries sorted newest-first."""
        receipts = self._collector.query(tenant_id=tenant_id, since=since, limit=limit)
        return [
            AuditTimelineEntry(
                timestamp=r.timestamp,
                source=r.source,
                actor=r.actor,
                summary=_summarize(r.source, r.metadata),
                receipt_id=r.receipt_id,
            )
            for r in receipts
        ]
