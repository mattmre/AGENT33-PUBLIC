"""Compatibility report APIs."""

from __future__ import annotations

from fastapi import APIRouter

from agent33.compatibility.errors import (
    FallbackDecision,
    ProviderErrorClass,
    ProviderErrorRecord,
    classify_provider_error,
    fallback_decision,
)
from agent33.compatibility.recommendations import (
    ResourceRecommendationResult,
    recommend_resources,
)
from agent33.compatibility.reports import (
    CompatibilityReport,
    get_compatibility_report_store,
)
from agent33.compatibility.routing import (
    CompatibilityRouteDecision,
    CompatibilityRouteRequest,
    choose_compatible_route,
)
from agent33.resources.service import get_resource_service
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/compatibility", tags=["compatibility"])


@router.post("/reports", dependencies=[require_scope("tools:execute")])
async def record_compatibility_report(report: CompatibilityReport) -> CompatibilityReport:
    return get_compatibility_report_store().record(report)


@router.get("/reports", dependencies=[require_scope("workflows:read")])
async def list_compatibility_reports(
    model: str = "",
    provider: str = "",
    resource_id: str = "",
    limit: int = 100,
) -> list[CompatibilityReport]:
    return get_compatibility_report_store().list_reports(
        model=model,
        provider=provider,
        resource_id=resource_id,
        limit=limit,
    )


@router.post("/errors/classify", dependencies=[require_scope("workflows:read")])
async def classify_compatibility_error(record: ProviderErrorRecord) -> ProviderErrorRecord:
    error_class = classify_provider_error(record.message, status_code=record.status_code)
    return record.model_copy(update={"error_class": error_class})


@router.get("/errors/decision/{error_class}", dependencies=[require_scope("workflows:read")])
async def get_fallback_decision(error_class: str) -> FallbackDecision:
    return fallback_decision(ProviderErrorClass(error_class))


@router.post("/routing/preview", dependencies=[require_scope("workflows:read")])
async def preview_compatibility_route(
    request: CompatibilityRouteRequest,
) -> CompatibilityRouteDecision:
    return choose_compatible_route(request, reports=get_compatibility_report_store())


@router.get("/recommendations/resources", dependencies=[require_scope("workflows:read")])
async def recommend_compatible_resources(
    query: str = "",
    model: str = "",
    provider: str = "",
    limit: int = 10,
) -> ResourceRecommendationResult:
    return recommend_resources(
        resource_service=get_resource_service(),
        reports=get_compatibility_report_store(),
        query=query,
        model=model,
        provider=provider,
        limit=limit,
    )
