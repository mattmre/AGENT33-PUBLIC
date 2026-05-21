"""Session analytics and insights API routes.

Phase 57 -- Hermes Adoption Roadmap.

Architecture & Planning H-03: Tenant isolation is enforced by deriving the tenant_id
from the caller's JWT/API-key token.  Only callers with the ``admin``
scope may view data belonging to a different tenant.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from agent33.observability.insights import InsightsEngine, InsightsReport
from agent33.observability.metrics import CostTracker, MetricsCollector
from agent33.security.permissions import (
    _get_token_payload,
    check_permission,
    require_scope,
)

router = APIRouter(prefix="/v1/insights", tags=["insights"])

# Module-level singletons; replaced at app startup via set_insights_engine().
_metrics = MetricsCollector()
_cost_tracker: CostTracker | None = None
_engine = InsightsEngine(_metrics, _cost_tracker)


def set_insights_engine(engine: InsightsEngine) -> None:
    """Swap the global insights engine (called during app init)."""
    global _engine
    _engine = engine


def set_insights_dependencies(
    metrics: MetricsCollector,
    cost_tracker: CostTracker | None = None,
) -> None:
    """Set the metrics collector and cost tracker, rebuilding the engine."""
    global _metrics, _cost_tracker, _engine
    _metrics = metrics
    _cost_tracker = cost_tracker
    _engine = InsightsEngine(_metrics, _cost_tracker)


def _serialize_report(report: InsightsReport) -> dict[str, Any]:
    """Convert an InsightsReport to a JSON-safe dictionary."""
    return {
        "total_sessions": report.total_sessions,
        "total_tokens": report.total_tokens,
        "total_cost_usd": float(report.total_cost_usd),
        "avg_session_duration_seconds": report.avg_session_duration_seconds,
        "tool_usage": report.tool_usage,
        "model_usage": report.model_usage,
        "daily_activity": report.daily_activity,
        "period_days": report.period_days,
        "generated_at": report.generated_at,
    }


def _resolve_tenant_id(request: Request, query_tenant_id: str | None) -> str | None:
    """Derive the effective tenant_id for the insights query.

    Rules (Architecture & Planning H-03):
    1. The caller's own tenant_id is extracted from the JWT/API-key token.
    2. If the caller has ``admin`` scope, they may optionally specify a
       different ``tenant_id`` via query parameter.
    3. Non-admin callers are always scoped to their own tenant.  If they
       pass a query ``tenant_id`` that differs from their token, the
       request is rejected with 403.
    4. If the caller's token has no tenant_id (empty string) and they are
       not admin, data is scoped to ``tenant_id=None`` (all records
       without a tenant prefix -- the ``global`` scope).

    Returns ``None`` to indicate "no tenant filter" (admin viewing all).
    """
    payload = _get_token_payload(request)
    caller_tenant: str = payload.tenant_id or ""
    is_admin: bool = check_permission("admin", payload.scopes)

    if is_admin:
        # Admin callers may override the tenant filter, or omit it to see all.
        if query_tenant_id is not None:
            return query_tenant_id
        return None  # admin with no filter sees everything

    # Non-admin callers are locked to their own tenant.
    if query_tenant_id is not None and query_tenant_id != caller_tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view insights for a different tenant",
        )

    return caller_tenant if caller_tenant else None


@router.get(
    "",
    dependencies=[require_scope("agents:read")],
)
async def get_insights(
    request: Request,
    days: int = Query(default=30, ge=1, le=365, description="Lookback period in days"),
    tenant_id: str | None = Query(default=None, description="Optional tenant filter (admin only)"),
) -> dict[str, Any]:
    """Return a consolidated analytics report.

    Aggregates session counts, token usage, cost attribution, tool/model
    breakdowns, and daily activity histograms for the requested period.

    The ``tenant_id`` is derived from the caller's authentication token.
    Admin-scoped callers may optionally pass a ``tenant_id`` query
    parameter to view a specific tenant's data or omit it to see all
    tenants.  Non-admin callers are always restricted to their own
    tenant's data.
    """
    effective_tenant = _resolve_tenant_id(request, tenant_id)
    report = _engine.generate(days=days, tenant_id=effective_tenant)
    return _serialize_report(report)
