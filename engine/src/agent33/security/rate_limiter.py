"""Per-tenant rate limiting with token bucket algorithm and quota tracking."""

from __future__ import annotations

import logging
import threading
import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier system
# ---------------------------------------------------------------------------


class RateLimitTier(StrEnum):
    """Service level tiers for rate limiting."""

    FREE = "free"
    STANDARD = "standard"
    PREMIUM = "premium"
    UNLIMITED = "unlimited"


class TierConfig(BaseModel):
    """Rate limit configuration for a single tier."""

    requests_per_minute: int
    requests_per_hour: int
    daily_quota: int
    burst_size: int


# Default tier configurations
TIER_CONFIGS: dict[RateLimitTier, TierConfig] = {
    RateLimitTier.FREE: TierConfig(
        requests_per_minute=10,
        requests_per_hour=200,
        daily_quota=1000,
        burst_size=5,
    ),
    RateLimitTier.STANDARD: TierConfig(
        requests_per_minute=60,
        requests_per_hour=2000,
        daily_quota=10000,
        burst_size=15,
    ),
    RateLimitTier.PREMIUM: TierConfig(
        requests_per_minute=200,
        requests_per_hour=10000,
        daily_quota=50000,
        burst_size=50,
    ),
    RateLimitTier.UNLIMITED: TierConfig(
        requests_per_minute=0,  # 0 = unlimited
        requests_per_hour=0,
        daily_quota=0,
        burst_size=0,
    ),
}

# ---------------------------------------------------------------------------
# State models
# ---------------------------------------------------------------------------


class RateLimitState(BaseModel):
    """Per-tenant rate limit state using token bucket algorithm."""

    tokens: float
    max_tokens: float
    refill_rate: float  # tokens per second
    last_refill: float  # time.monotonic() value
    request_count_minute: int = 0
    request_count_hour: int = 0
    request_count_daily: int = 0
    minute_reset: float = 0.0  # time.monotonic() value
    hour_reset: float = 0.0
    daily_reset: float = 0.0


class TenantQuota(BaseModel):
    """Quota snapshot for a tenant."""

    tenant_id: str
    tier: str
    used_today: int
    limit_today: int
    used_this_hour: int
    limit_this_hour: int
    used_this_minute: int
    limit_this_minute: int


# ---------------------------------------------------------------------------
# Core rate limiter
# ---------------------------------------------------------------------------


class RateLimiter:
    """Thread-safe, in-memory per-tenant rate limiter using token bucket."""

    def __init__(self, default_tier: RateLimitTier = RateLimitTier.STANDARD) -> None:
        self._default_tier = default_tier
        self._lock = threading.Lock()
        self._states: dict[str, RateLimitState] = {}
        self._tiers: dict[str, RateLimitTier] = {}

    @property
    def default_tier(self) -> RateLimitTier:
        return self._default_tier

    @default_tier.setter
    def default_tier(self, tier: RateLimitTier) -> None:
        self._default_tier = tier

    def _get_tier(self, tenant_id: str) -> RateLimitTier:
        return self._tiers.get(tenant_id, self._default_tier)

    def _get_tier_config(self, tier: RateLimitTier) -> TierConfig:
        return TIER_CONFIGS[tier]

    def _ensure_state(self, tenant_id: str, tier: RateLimitTier) -> RateLimitState:
        """Return existing state or create a new one for the tenant."""
        if tenant_id in self._states:
            return self._states[tenant_id]
        config = self._get_tier_config(tier)
        now = time.monotonic()
        # For unlimited tier, use a large token count that never depletes
        if tier == RateLimitTier.UNLIMITED:
            state = RateLimitState(
                tokens=1_000_000.0,
                max_tokens=1_000_000.0,
                refill_rate=1_000_000.0,
                last_refill=now,
                minute_reset=now + 60,
                hour_reset=now + 3600,
                daily_reset=now + 86400,
            )
        else:
            # Token bucket: max_tokens = burst_size, refill_rate = requests_per_minute / 60
            max_tokens = float(config.burst_size)
            refill_rate = config.requests_per_minute / 60.0
            state = RateLimitState(
                tokens=max_tokens,
                max_tokens=max_tokens,
                refill_rate=refill_rate,
                last_refill=now,
                minute_reset=now + 60,
                hour_reset=now + 3600,
                daily_reset=now + 86400,
            )
        self._states[tenant_id] = state
        return state

    def _refill_tokens(self, state: RateLimitState) -> None:
        """Refill tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - state.last_refill
        if elapsed > 0:
            new_tokens = elapsed * state.refill_rate
            state.tokens = min(state.max_tokens, state.tokens + new_tokens)
            state.last_refill = now

    def _reset_expired_windows(self, state: RateLimitState) -> None:
        """Reset sliding window counters when their period expires."""
        now = time.monotonic()
        if now >= state.minute_reset:
            state.request_count_minute = 0
            state.minute_reset = now + 60
        if now >= state.hour_reset:
            state.request_count_hour = 0
            state.hour_reset = now + 3600
        if now >= state.daily_reset:
            state.request_count_daily = 0
            state.daily_reset = now + 86400

    def check_rate_limit(
        self,
        tenant_id: str,
        tier: RateLimitTier | None = None,
    ) -> tuple[bool, dict[str, str]]:
        """Check whether a request from *tenant_id* is allowed.

        Returns ``(allowed, headers)`` where *headers* is a dict of
        rate-limit response headers to include in the HTTP response.
        """
        with self._lock:
            effective_tier = tier or self._get_tier(tenant_id)
            config = self._get_tier_config(effective_tier)
            state = self._ensure_state(tenant_id, effective_tier)

            # Unlimited tier always allows
            if effective_tier == RateLimitTier.UNLIMITED:
                return True, {
                    "X-RateLimit-Limit": "unlimited",
                    "X-RateLimit-Remaining": "unlimited",
                    "X-RateLimit-Reset": "0",
                }

            self._refill_tokens(state)
            self._reset_expired_windows(state)

            # Check per-minute limit
            if (
                config.requests_per_minute > 0
                and state.request_count_minute >= config.requests_per_minute
            ):
                retry_after = max(1, int(state.minute_reset - time.monotonic()))
                return False, {
                    "X-RateLimit-Limit": str(config.requests_per_minute),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(state.minute_reset)),
                    "Retry-After": str(retry_after),
                }

            # Check per-hour limit
            if (
                config.requests_per_hour > 0
                and state.request_count_hour >= config.requests_per_hour
            ):
                retry_after = max(1, int(state.hour_reset - time.monotonic()))
                return False, {
                    "X-RateLimit-Limit": str(config.requests_per_hour),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(state.hour_reset)),
                    "Retry-After": str(retry_after),
                }

            # Check daily quota
            if config.daily_quota > 0 and state.request_count_daily >= config.daily_quota:
                retry_after = max(1, int(state.daily_reset - time.monotonic()))
                return False, {
                    "X-RateLimit-Limit": str(config.daily_quota),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(state.daily_reset)),
                    "Retry-After": str(retry_after),
                }

            # Check token bucket (burst control)
            if state.tokens < 1.0:
                # Compute how long until at least one token refills
                wait_seconds = max(1, int((1.0 - state.tokens) / state.refill_rate))
                return False, {
                    "X-RateLimit-Limit": str(config.requests_per_minute),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(state.minute_reset)),
                    "Retry-After": str(wait_seconds),
                }

            # Consume one token and increment counters
            state.tokens -= 1.0
            state.request_count_minute += 1
            state.request_count_hour += 1
            state.request_count_daily += 1

            remaining_minute = max(0, config.requests_per_minute - state.request_count_minute)
            return True, {
                "X-RateLimit-Limit": str(config.requests_per_minute),
                "X-RateLimit-Remaining": str(remaining_minute),
                "X-RateLimit-Reset": str(int(state.minute_reset)),
            }

    def get_tenant_quota(self, tenant_id: str) -> TenantQuota:
        """Return quota snapshot for a tenant."""
        with self._lock:
            tier = self._get_tier(tenant_id)
            config = self._get_tier_config(tier)
            state = self._states.get(tenant_id)
            if state is None:
                return TenantQuota(
                    tenant_id=tenant_id,
                    tier=tier.value,
                    used_today=0,
                    limit_today=config.daily_quota,
                    used_this_hour=0,
                    limit_this_hour=config.requests_per_hour,
                    used_this_minute=0,
                    limit_this_minute=config.requests_per_minute,
                )
            self._reset_expired_windows(state)
            return TenantQuota(
                tenant_id=tenant_id,
                tier=tier.value,
                used_today=state.request_count_daily,
                limit_today=config.daily_quota,
                used_this_hour=state.request_count_hour,
                limit_this_hour=config.requests_per_hour,
                used_this_minute=state.request_count_minute,
                limit_this_minute=config.requests_per_minute,
            )

    def set_tenant_tier(self, tenant_id: str, tier: RateLimitTier) -> None:
        """Set the rate limit tier for a tenant.

        This clears existing state so the new tier limits take effect
        immediately.
        """
        with self._lock:
            self._tiers[tenant_id] = tier
            # Remove old state so it gets re-created with new tier limits
            self._states.pop(tenant_id, None)
            logger.info(
                "tenant_tier_updated",
                extra={"tenant_id": tenant_id, "tier": tier.value},
            )

    def get_all_quotas(self) -> list[TenantQuota]:
        """Return quota snapshots for all tracked tenants."""
        with self._lock:
            # Collect all known tenant IDs from both tiers and states
            tenant_ids = set(self._tiers.keys()) | set(self._states.keys())

        # Call get_tenant_quota outside the lock to avoid re-entrance issues
        # (get_tenant_quota acquires the lock internally)
        return [self.get_tenant_quota(tid) for tid in sorted(tenant_ids)]

    def reset_tenant(self, tenant_id: str) -> None:
        """Reset all counters and token bucket state for a tenant."""
        with self._lock:
            self._states.pop(tenant_id, None)
            logger.info(
                "tenant_rate_limit_reset",
                extra={"tenant_id": tenant_id},
            )

    def reset_all(self) -> None:
        """Reset all per-tenant state.  Useful in tests."""
        with self._lock:
            self._states.clear()


# ---------------------------------------------------------------------------
# Starlette middleware
# ---------------------------------------------------------------------------

# Paths that bypass rate limiting
_BYPASS_PATHS: set[str] = {
    "/health",
    "/healthz",
    "/readyz",
    "/health/channels",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
}

_BYPASS_PREFIXES: tuple[str, ...] = (
    "/docs/",
    "/redoc/",
    "/v1/dashboard/",
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces per-tenant rate limits.

    Must be added *after* ``AuthMiddleware`` in the middleware stack so that
    ``request.state.user`` is available for tenant identification.
    """

    def __init__(self, app: Any, rate_limiter: RateLimiter) -> None:
        super().__init__(app)
        self._rate_limiter = rate_limiter

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Skip rate limiting for health, docs, and dashboard paths
        if path in _BYPASS_PATHS or path.startswith(_BYPASS_PREFIXES):
            return await call_next(request)

        # Skip preflight requests
        if request.method == "OPTIONS":
            return await call_next(request)

        # Extract tenant_id from auth context
        user = getattr(request.state, "user", None)
        if user is None:
            # No auth context — let auth middleware handle the 401
            return await call_next(request)

        tenant_id: str = str(getattr(user, "tenant_id", None) or getattr(user, "sub", "anonymous"))

        allowed, headers = self._rate_limiter.check_rate_limit(tenant_id)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers=headers,
            )

        response: Response = await call_next(request)
        # Attach rate limit headers to successful responses
        for key, value in headers.items():
            response.headers[key] = value
        return response
