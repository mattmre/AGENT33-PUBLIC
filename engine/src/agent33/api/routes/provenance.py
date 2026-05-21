"""Provenance, audit export, and runtime API endpoints.

Includes the original receipt/timeline/export endpoints plus upstream agent OS T10
additions: hashed receipt queries, chain traversal, JSON/CSV export,
and runtime guard diagnostics.
"""

from __future__ import annotations

import logging
from datetime import datetime  # noqa: TC003
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from agent33.provenance.audit_export import AuditExportRecord, ExportFilters, ExportFormat

if TYPE_CHECKING:
    from agent33.ops.runtime_guard import RuntimeInfo
from agent33.provenance.models import (
    AuditBundle,
    AuditTimelineEntry,
    ProvenanceReceipt,
    ProvenanceSource,
)
from agent33.provenance.receipts import EntityType, HashedReceipt
from agent33.security.permissions import require_scope

router = APIRouter(tags=["provenance"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_collector(request: Request) -> Any:
    collector = getattr(request.app.state, "provenance_collector", None)
    if collector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Provenance collector not initialized",
        )
    return collector


def _get_timeline_service(request: Request) -> Any:
    svc = getattr(request.app.state, "audit_timeline_service", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audit timeline service not initialized",
        )
    return svc


def _get_exporter(request: Request) -> Any:
    exporter = getattr(request.app.state, "audit_exporter", None)
    if exporter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audit exporter not initialized",
        )
    return exporter


def _get_receipt_store(request: Request) -> Any:
    store = getattr(request.app.state, "receipt_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Receipt store not initialized",
        )
    return store


def _get_receipt_exporter(request: Request) -> Any:
    exporter = getattr(request.app.state, "receipt_exporter", None)
    if exporter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Receipt exporter not initialized",
        )
    return exporter


def _get_runtime_guard(request: Request) -> Any:
    guard = getattr(request.app.state, "runtime_guard", None)
    if guard is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runtime guard not initialized",
        )
    return guard


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ReceiptListResponse(BaseModel):
    """Paginated list of provenance receipts."""

    receipts: list[ProvenanceReceipt]
    count: int


class HashedReceiptListResponse(BaseModel):
    """List of hashed provenance receipts (T10)."""

    receipts: list[HashedReceipt]
    count: int


class HashedReceiptChainResponse(BaseModel):
    """Provenance chain response (T10)."""

    chain: list[HashedReceipt]
    length: int


class TimelineResponse(BaseModel):
    """Audit timeline response."""

    entries: list[AuditTimelineEntry]
    count: int


class VersionResponse(BaseModel):
    """Runtime version information."""

    version: str
    git_short_hash: str
    python_version: str
    platform: str


class ExportRequest(BaseModel):
    """Body for triggering an audit export."""

    tenant_id: str = ""
    since: datetime | None = None
    until: datetime | None = None


ExportRequest.model_rebuild()


class ReceiptExportRequest(BaseModel):
    """Body for triggering a hashed receipt export (T10)."""

    format: ExportFormat = ExportFormat.JSON
    since: datetime | None = None
    until: datetime | None = None
    entity_type: str | None = None
    actor: str = ""
    session_id: str = ""


class ReceiptExportResponse(BaseModel):
    """Response for a receipt export operation (T10)."""

    export_id: str
    created_at: datetime
    format: ExportFormat
    receipt_count: int
    data: str


class RuntimeInfoResponse(BaseModel):
    """Runtime diagnostics response (T10)."""

    pid: int = 0
    uptime_seconds: float = 0.0
    memory_rss_mb: float = 0.0
    python_version: str = ""
    package_version: str = ""
    platform: str = ""
    invariants: list[dict[str, Any]] = Field(default_factory=list)
    all_invariants_ok: bool = True


ReceiptExportRequest.model_rebuild()


# ---------------------------------------------------------------------------
# Provenance receipt endpoints (original)
# ---------------------------------------------------------------------------


@router.get(
    "/v1/provenance/receipts",
    response_model=ReceiptListResponse,
    dependencies=[require_scope("provenance:read")],
)
async def list_receipts(
    request: Request,
    source: ProvenanceSource | None = None,
    session_id: str = "",
    tenant_id: str = "",
    since: datetime | None = None,
    limit: int = 100,
) -> ReceiptListResponse:
    """List provenance receipts with optional filters."""
    collector = _get_collector(request)
    receipts = collector.query(
        source=source,
        session_id=session_id,
        tenant_id=tenant_id,
        since=since,
        limit=limit,
    )
    return ReceiptListResponse(receipts=receipts, count=len(receipts))


@router.get(
    "/v1/provenance/receipts/{receipt_id}",
    response_model=ProvenanceReceipt,
    dependencies=[require_scope("provenance:read")],
)
async def get_receipt(
    request: Request,
    receipt_id: str,
) -> ProvenanceReceipt:
    """Retrieve a single provenance receipt by ID."""
    collector = _get_collector(request)
    receipt = collector.get(receipt_id)
    if receipt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Receipt {receipt_id} not found",
        )
    result: ProvenanceReceipt = receipt
    return result


# ---------------------------------------------------------------------------
# Hashed receipt endpoints (T10)
# ---------------------------------------------------------------------------


@router.get(
    "/v1/provenance/hashed-receipts",
    response_model=HashedReceiptListResponse,
    dependencies=[require_scope("provenance:read")],
)
async def list_hashed_receipts(
    request: Request,
    entity_type: EntityType | None = None,
    session_id: str = "",
    actor: str = "",
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
) -> HashedReceiptListResponse:
    """List hashed provenance receipts with optional filters."""
    store = _get_receipt_store(request)
    receipts = store.list_all(
        entity_type=entity_type,
        actor=actor,
        session_id=session_id,
        since=since,
        until=until,
        limit=limit,
    )
    return HashedReceiptListResponse(receipts=receipts, count=len(receipts))


@router.get(
    "/v1/provenance/hashed-receipts/{receipt_id}",
    response_model=HashedReceipt,
    dependencies=[require_scope("provenance:read")],
)
async def get_hashed_receipt(
    request: Request,
    receipt_id: str,
) -> HashedReceipt:
    """Retrieve a single hashed provenance receipt by ID."""
    store = _get_receipt_store(request)
    receipt = store.get(receipt_id)
    if receipt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hashed receipt {receipt_id} not found",
        )
    result: HashedReceipt = receipt
    return result


@router.get(
    "/v1/provenance/hashed-receipts/{receipt_id}/chain",
    response_model=HashedReceiptChainResponse,
    dependencies=[require_scope("provenance:read")],
)
async def get_hashed_receipt_chain(
    request: Request,
    receipt_id: str,
) -> HashedReceiptChainResponse:
    """Get the full provenance chain for a hashed receipt."""
    store = _get_receipt_store(request)
    chain = store.get_chain(receipt_id)
    if not chain:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hashed receipt {receipt_id} not found",
        )
    return HashedReceiptChainResponse(chain=chain, length=len(chain))


# ---------------------------------------------------------------------------
# Receipt export (T10)
# ---------------------------------------------------------------------------


@router.post(
    "/v1/provenance/hashed-export",
    response_model=ReceiptExportResponse,
    dependencies=[require_scope("provenance:export")],
)
async def export_hashed_receipts(
    request: Request,
    body: ReceiptExportRequest,
) -> ReceiptExportResponse:
    """Export hashed receipts as JSON or CSV."""
    exporter = _get_receipt_exporter(request)
    filters = ExportFilters(
        since=body.since,
        until=body.until,
        entity_type=body.entity_type,
        actor=body.actor,
        session_id=body.session_id,
    )
    if body.format == ExportFormat.CSV:
        record: AuditExportRecord = exporter.export_csv(filters)
    else:
        record = exporter.export_json(filters)
    return ReceiptExportResponse(
        export_id=record.export_id,
        created_at=record.created_at,
        format=record.format,
        receipt_count=record.receipt_count,
        data=record.data,
    )


@router.get(
    "/v1/provenance/hashed-export/{export_id}",
    response_model=ReceiptExportResponse,
    dependencies=[require_scope("provenance:export")],
)
async def get_hashed_export(
    request: Request,
    export_id: str,
) -> ReceiptExportResponse:
    """Retrieve a previously completed export record."""
    exporter = _get_receipt_exporter(request)
    record = exporter.get_export(export_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Export {export_id} not found",
        )
    return ReceiptExportResponse(
        export_id=record.export_id,
        created_at=record.created_at,
        format=record.format,
        receipt_count=record.receipt_count,
        data=record.data,
    )


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


@router.get(
    "/v1/provenance/timeline",
    response_model=TimelineResponse,
    dependencies=[require_scope("provenance:read")],
)
async def timeline(
    request: Request,
    tenant_id: str = "",
    since: datetime | None = None,
    limit: int = 100,
) -> TimelineResponse:
    """Build a human-readable audit timeline."""
    svc = _get_timeline_service(request)
    entries = svc.build(tenant_id=tenant_id, since=since, limit=limit)
    return TimelineResponse(entries=entries, count=len(entries))


# ---------------------------------------------------------------------------
# Export (original)
# ---------------------------------------------------------------------------


@router.post(
    "/v1/provenance/export",
    response_model=AuditBundle,
    dependencies=[require_scope("provenance:export")],
)
async def export_audit(
    request: Request,
    body: ExportRequest,
) -> AuditBundle:
    """Generate and return an audit bundle."""
    exporter = _get_exporter(request)
    bundle: AuditBundle = exporter.export(
        tenant_id=body.tenant_id,
        since=body.since,
        until=body.until,
    )
    return bundle


# ---------------------------------------------------------------------------
# Runtime version
# ---------------------------------------------------------------------------


@router.get(
    "/v1/runtime/version",
    response_model=VersionResponse,
    dependencies=[require_scope("provenance:read")],
)
async def runtime_version(
    request: Request,
) -> VersionResponse:
    """Return runtime version info (package version, git hash, Python, platform)."""
    info = getattr(request.app.state, "runtime_version_info", None)
    if info is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runtime version info not available",
        )
    return VersionResponse(
        version=info.version,
        git_short_hash=info.git_short_hash,
        python_version=info.python_version,
        platform=info.platform,
    )


# ---------------------------------------------------------------------------
# Ops: Runtime guard (T10)
# ---------------------------------------------------------------------------


@router.get(
    "/v1/ops/runtime",
    response_model=RuntimeInfoResponse,
    dependencies=[require_scope("operator:read")],
)
async def ops_runtime_info(
    request: Request,
) -> RuntimeInfoResponse:
    """Return runtime info and startup invariant status."""
    guard = _get_runtime_guard(request)
    info: RuntimeInfo = guard.get_runtime_info()
    return RuntimeInfoResponse(
        pid=info.pid,
        uptime_seconds=info.uptime_seconds,
        memory_rss_mb=info.memory_rss_mb,
        python_version=info.python_version,
        package_version=info.package_version,
        platform=info.platform,
        invariants=[inv.model_dump() for inv in info.invariants],
        all_invariants_ok=info.all_invariants_ok,
    )
