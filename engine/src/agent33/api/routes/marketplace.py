"""FastAPI router for marketplace pack discovery and installation."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from agent33.packs.api_models import (
    CategoryCreateRequest,
    CategoryUpdateRequest,
    CurationReviewRequest,
    CurationSubmitRequest,
    DeprecateRequest,
    InstallResponse,
    MarketplaceInstallRequest,
    MarketplacePackDetail,
    MarketplacePackSummary,
    MarketplacePackVersionInfo,
)
from agent33.packs.categories import CategoryRegistry
from agent33.packs.curation import InvalidCurationTransitionError
from agent33.packs.curation_service import CurationService
from agent33.packs.models import PackSource
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/marketplace", tags=["marketplace"])


def _get_pack_marketplace(request: Request) -> Any:
    """Retrieve the marketplace catalog from app state."""
    return getattr(request.app.state, "pack_marketplace", None)


def _get_pack_registry(request: Request) -> Any:
    """Retrieve the pack registry from app state."""
    return getattr(request.app.state, "pack_registry", None)


def _record_to_summary(record: Any) -> MarketplacePackSummary:
    """Convert a marketplace record to API summary form."""
    latest = next(
        (version for version in record.versions if version.version == record.latest_version),
        record.versions[0] if record.versions else None,
    )
    return MarketplacePackSummary(
        name=record.name,
        description=record.description,
        author=record.author,
        tags=record.tags,
        category=record.category,
        latest_version=record.latest_version,
        versions_count=len(record.versions),
        sources=sorted({version.source_name for version in record.versions}),
        trust_level=latest.trust_level if latest else None,
    )


def _record_to_detail(record: Any) -> MarketplacePackDetail:
    """Convert a marketplace record to API detail form."""
    return MarketplacePackDetail(
        name=record.name,
        description=record.description,
        author=record.author,
        tags=record.tags,
        category=record.category,
        latest_version=record.latest_version,
        versions=[
            MarketplacePackVersionInfo(
                version=item.version,
                description=item.description,
                author=item.author,
                tags=item.tags,
                category=item.category,
                skills_count=item.skills_count,
                source_name=item.source_name,
                source_type=item.source_type,
                trust_level=item.trust_level,
            )
            for item in record.versions
        ],
        sources=sorted({version.source_name for version in record.versions}),
    )


@router.get("/packs", dependencies=[require_scope("agents:read")])
async def list_marketplace_packs(request: Request) -> dict[str, Any]:
    """List marketplace packs."""
    marketplace = _get_pack_marketplace(request)
    if marketplace is None:
        raise HTTPException(status_code=503, detail="Marketplace catalog not initialized")

    packs = marketplace.list_packs()
    return {
        "packs": [_record_to_summary(pack).model_dump() for pack in packs],
        "count": len(packs),
    }


@router.post("/refresh", dependencies=[require_scope("admin")])
async def refresh_marketplace(request: Request) -> dict[str, Any]:
    """Refresh all configured marketplace sources."""
    marketplace = _get_pack_marketplace(request)
    if marketplace is None:
        raise HTTPException(status_code=503, detail="Marketplace catalog not initialized")
    await run_in_threadpool(marketplace.refresh)
    packs = marketplace.list_packs()
    return {"refreshed": True, "count": len(packs)}


@router.get("/packs/{name}", dependencies=[require_scope("agents:read")])
async def get_marketplace_pack(name: str, request: Request) -> dict[str, Any]:
    """Get detail for a marketplace pack."""
    marketplace = _get_pack_marketplace(request)
    if marketplace is None:
        raise HTTPException(status_code=503, detail="Marketplace catalog not initialized")

    pack = marketplace.get_pack(name)
    if pack is None:
        raise HTTPException(status_code=404, detail=f"Marketplace pack '{name}' not found")
    return _record_to_detail(pack).model_dump()


@router.get("/packs/{name}/versions", dependencies=[require_scope("agents:read")])
async def list_marketplace_versions(name: str, request: Request) -> dict[str, Any]:
    """List all versions for a marketplace pack."""
    marketplace = _get_pack_marketplace(request)
    if marketplace is None:
        raise HTTPException(status_code=503, detail="Marketplace catalog not initialized")

    versions = marketplace.list_versions(name)
    if not versions:
        raise HTTPException(status_code=404, detail=f"Marketplace pack '{name}' not found")
    return {
        "name": name,
        "versions": [
            MarketplacePackVersionInfo(
                version=item.version,
                description=item.description,
                author=item.author,
                tags=item.tags,
                category=item.category,
                skills_count=item.skills_count,
                source_name=item.source_name,
                source_type=item.source_type,
                trust_level=item.trust_level,
            ).model_dump()
            for item in versions
        ],
        "count": len(versions),
    }


@router.get("/search", dependencies=[require_scope("agents:read")])
async def search_marketplace(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query"),
) -> dict[str, Any]:
    """Search marketplace packs."""
    marketplace = _get_pack_marketplace(request)
    if marketplace is None:
        raise HTTPException(status_code=503, detail="Marketplace catalog not initialized")

    results = marketplace.search(q)
    return {
        "results": [_record_to_summary(pack).model_dump() for pack in results],
        "count": len(results),
        "query": q,
    }


@router.post("/install", status_code=201, dependencies=[require_scope("agents:write")])
async def install_marketplace_pack(
    body: MarketplaceInstallRequest,
    request: Request,
) -> dict[str, Any]:
    """Install a pack from the configured marketplace."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")
    if not getattr(registry, "has_marketplace", False):
        raise HTTPException(status_code=503, detail="Marketplace catalog not initialized")

    marketplace = _get_pack_marketplace(request)
    if marketplace is None:
        raise HTTPException(status_code=503, detail="Marketplace catalog not initialized")

    result = registry.install(PackSource(source_type="marketplace", **body.model_dump()))
    response = InstallResponse(
        success=result.success,
        pack_name=result.pack_name,
        version=result.version,
        skills_loaded=result.skills_loaded,
        errors=result.errors,
        warnings=result.warnings,
    )

    if not result.success:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Failed to install marketplace pack '{result.pack_name}'",
                "errors": result.errors,
            },
        )

    return response.model_dump()


# ---------------------------------------------------------------------------
# Curation helpers
# ---------------------------------------------------------------------------


def _get_curation_service(request: Request) -> CurationService:
    """Retrieve the curation service from app state."""
    svc: CurationService | None = getattr(request.app.state, "curation_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Curation service not initialized")
    return svc


def _get_category_registry(request: Request) -> CategoryRegistry:
    """Retrieve the category registry from app state."""
    reg: CategoryRegistry | None = getattr(request.app.state, "category_registry", None)
    if reg is None:
        raise HTTPException(status_code=503, detail="Category registry not initialized")
    return reg


# ---------------------------------------------------------------------------
# Curation endpoints
# ---------------------------------------------------------------------------


@router.post("/curation/submit", status_code=201, dependencies=[require_scope("agents:write")])
async def submit_for_curation(
    body: CurationSubmitRequest,
    request: Request,
) -> dict[str, Any]:
    """Submit a pack for marketplace curation."""
    svc = _get_curation_service(request)
    try:
        record = svc.submit(body.pack_name, body.version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return record.model_dump(mode="json")


@router.post(
    "/curation/{name}/review",
    dependencies=[require_scope("admin")],
)
async def review_curation(
    name: str,
    body: CurationReviewRequest,
    request: Request,
) -> dict[str, Any]:
    """Start review and complete it with a decision."""
    svc = _get_curation_service(request)
    try:
        svc.start_review(name, body.reviewer_id)
        record = svc.complete_review(
            name, body.decision, notes=body.notes, reviewer_id=body.reviewer_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidCurationTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return record.model_dump(mode="json")


@router.get("/curation/{name}", dependencies=[require_scope("agents:read")])
async def get_curation(name: str, request: Request) -> dict[str, Any]:
    """Get curation record for a pack."""
    svc = _get_curation_service(request)
    record = svc.get_curation(name)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No curation record for '{name}'")
    return record.model_dump(mode="json")


@router.get("/curation", dependencies=[require_scope("agents:read")])
async def list_curated(
    request: Request,
    status: str = Query(default="", description="Filter by curation status"),
) -> dict[str, Any]:
    """List curation records with optional status filter."""
    from agent33.packs.curation import CurationStatus

    svc = _get_curation_service(request)
    filter_status = None
    if status:
        try:
            filter_status = CurationStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status!r}") from None
    records = svc.list_curated(status=filter_status)
    return {
        "records": [r.model_dump(mode="json") for r in records],
        "count": len(records),
    }


@router.post("/curation/{name}/feature", dependencies=[require_scope("admin")])
async def feature_pack(name: str, request: Request) -> dict[str, Any]:
    """Toggle featured status on a curated pack."""
    svc = _get_curation_service(request)
    try:
        record = svc.get_curation(name)
        if record is None:
            raise HTTPException(status_code=404, detail=f"No curation record for '{name}'")
        record = svc.unfeature(name) if record.featured else svc.feature(name)
    except InvalidCurationTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return record.model_dump(mode="json")


@router.post("/curation/{name}/verify", dependencies=[require_scope("admin")])
async def verify_pack_curation(name: str, request: Request) -> dict[str, Any]:
    """Mark a pack as verified."""
    svc = _get_curation_service(request)
    try:
        record = svc.verify(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return record.model_dump(mode="json")


@router.post("/curation/{name}/deprecate", dependencies=[require_scope("admin")])
async def deprecate_pack(
    name: str,
    request: Request,
    body: DeprecateRequest | None = None,
) -> dict[str, Any]:
    """Deprecate a curated pack."""
    svc = _get_curation_service(request)
    reason = body.reason if body else ""
    try:
        record = svc.deprecate(name, reason)
    except (ValueError, InvalidCurationTransitionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return record.model_dump(mode="json")


@router.post("/curation/{name}/unlist", dependencies=[require_scope("admin")])
async def unlist_pack(name: str, request: Request) -> dict[str, Any]:
    """Unlist a curated pack."""
    svc = _get_curation_service(request)
    try:
        record = svc.unlist(name)
    except (ValueError, InvalidCurationTransitionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return record.model_dump(mode="json")


@router.get("/quality/{name}/review-signals", dependencies=[require_scope("agents:read")])
async def get_quality_review_signals(name: str, request: Request) -> dict[str, Any]:
    """Return operator-facing curation blockers, recommendations, and feature posture."""
    svc = _get_curation_service(request)
    try:
        signals = svc.review_signals(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return signals.model_dump(mode="json")


@router.get("/quality/{name}", dependencies=[require_scope("agents:read")])
async def get_quality_assessment(name: str, request: Request) -> dict[str, Any]:
    """Run quality assessment on a pack."""
    svc = _get_curation_service(request)
    try:
        assessment = svc.assess_quality(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return assessment.model_dump(mode="json")


@router.get("/featured", dependencies=[require_scope("agents:read")])
async def list_featured(request: Request) -> dict[str, Any]:
    """List featured packs."""
    svc = _get_curation_service(request)
    records = svc.list_curated(featured_only=True)
    return {
        "records": [r.model_dump(mode="json") for r in records],
        "count": len(records),
    }


# ---------------------------------------------------------------------------
# Category endpoints
# ---------------------------------------------------------------------------


@router.get("/categories", dependencies=[require_scope("agents:read")])
async def list_categories(request: Request) -> dict[str, Any]:
    """List marketplace categories."""
    reg = _get_category_registry(request)
    cats = reg.list_categories()
    return {
        "categories": [c.model_dump(mode="json") for c in cats],
        "count": len(cats),
    }


@router.post("/categories", status_code=201, dependencies=[require_scope("admin")])
async def create_category(
    body: CategoryCreateRequest,
    request: Request,
) -> dict[str, Any]:
    """Create a new marketplace category."""
    from agent33.packs.categories import MarketplaceCategory

    reg = _get_category_registry(request)
    cat = MarketplaceCategory(
        slug=body.slug,
        label=body.label,
        description=body.description,
        parent_slug=body.parent_slug,
    )
    try:
        reg.add_category(cat)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return cat.model_dump(mode="json")


@router.put("/categories/{slug}", dependencies=[require_scope("admin")])
async def update_category(
    slug: str,
    body: CategoryUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    """Update a marketplace category."""
    reg = _get_category_registry(request)
    try:
        updated = reg.update_category(
            slug,
            label=body.label,
            description=body.description,
            parent_slug=body.parent_slug,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return updated.model_dump(mode="json")


@router.delete("/categories/{slug}", dependencies=[require_scope("admin")])
async def delete_category(slug: str, request: Request) -> dict[str, Any]:
    """Delete a marketplace category."""
    reg = _get_category_registry(request)
    try:
        reg.remove_category(slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": True, "slug": slug}
