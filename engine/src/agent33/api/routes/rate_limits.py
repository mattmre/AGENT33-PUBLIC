"""Admin endpoints for per-tenant rate limit management."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from agent33.security.permissions import require_scope
from agent33.security.rate_limiter import (
    TIER_CONFIGS,
    RateLimiter,
    RateLimitTier,
    TenantQuota,
    TierConfig,
)

router = APIRouter(prefix="/v1/admin/rate-limits", tags=["rate-limits"])


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------


def get_rate_limiter(request: Request) -> RateLimiter:
    """Return the app-scoped rate limiter."""
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiter not initialized",
        )
    return limiter


RateLimiterDependency = Annotated[RateLimiter, Depends(get_rate_limiter)]


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SetTierRequest(BaseModel):
    """Request body for updating a tenant's rate limit tier."""

    tier: RateLimitTier


class TierConfigResponse(BaseModel):
    """Response model for a single tier configuration."""

    tier: str
    config: TierConfig


class TierListResponse(BaseModel):
    """Response listing all available tiers and their configurations."""

    tiers: list[TierConfigResponse]


class QuotaListResponse(BaseModel):
    """Response listing quota snapshots for all tenants."""

    quotas: list[TenantQuota]


class ResetResponse(BaseModel):
    """Response confirming a tenant's rate limit counters were reset."""

    tenant_id: str
    message: str


class TierUpdateResponse(BaseModel):
    """Response confirming a tenant's tier was updated."""

    tenant_id: str
    tier: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=QuotaListResponse,
    dependencies=[require_scope("admin")],
)
async def list_quotas(limiter: RateLimiterDependency) -> QuotaListResponse:
    """List quota snapshots for all tracked tenants."""
    return QuotaListResponse(quotas=limiter.get_all_quotas())


@router.get(
    "/tiers",
    response_model=TierListResponse,
    dependencies=[require_scope("admin")],
)
async def list_tiers(limiter: RateLimiterDependency) -> TierListResponse:
    """List all available rate limit tiers and their configurations."""
    items = [
        TierConfigResponse(tier=tier.value, config=config) for tier, config in TIER_CONFIGS.items()
    ]
    return TierListResponse(tiers=items)


@router.get(
    "/{tenant_id}",
    response_model=TenantQuota,
    dependencies=[require_scope("admin")],
)
async def get_tenant_quota(
    tenant_id: str,
    limiter: RateLimiterDependency,
) -> TenantQuota:
    """Get quota snapshot for a specific tenant."""
    return limiter.get_tenant_quota(tenant_id)


@router.put(
    "/{tenant_id}/tier",
    response_model=TierUpdateResponse,
    dependencies=[require_scope("admin")],
)
async def set_tenant_tier(
    tenant_id: str,
    body: SetTierRequest,
    limiter: RateLimiterDependency,
) -> TierUpdateResponse:
    """Set the rate limit tier for a tenant."""
    limiter.set_tenant_tier(tenant_id, body.tier)
    return TierUpdateResponse(tenant_id=tenant_id, tier=body.tier.value)


@router.post(
    "/{tenant_id}/reset",
    response_model=ResetResponse,
    dependencies=[require_scope("admin")],
)
async def reset_tenant(
    tenant_id: str,
    limiter: RateLimiterDependency,
) -> ResetResponse:
    """Reset all rate limit counters for a tenant."""
    limiter.reset_tenant(tenant_id)
    return ResetResponse(tenant_id=tenant_id, message="Rate limit counters reset")
