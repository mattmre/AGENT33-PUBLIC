"""Tests for per-tenant rate limiting with token bucket and quota tracking (S42)."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from agent33.security.rate_limiter import (
    TIER_CONFIGS,
    RateLimiter,
    RateLimitMiddleware,
    RateLimitTier,
)

# ---------------------------------------------------------------------------
# Unit tests: RateLimiter core logic
# ---------------------------------------------------------------------------


class TestTokenBucketAlgorithm:
    """Test the token bucket refill, depletion, and burst behavior."""

    def test_initial_state_has_full_tokens(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.STANDARD)
        allowed, headers = limiter.check_rate_limit("tenant-1")
        assert allowed is True
        assert headers["X-RateLimit-Limit"] == str(
            TIER_CONFIGS[RateLimitTier.STANDARD].requests_per_minute
        )

    def test_burst_allows_rapid_requests_up_to_burst_size(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.FREE)
        burst_size = TIER_CONFIGS[RateLimitTier.FREE].burst_size
        results = []
        for _ in range(burst_size):
            allowed, _ = limiter.check_rate_limit("tenant-burst")
            results.append(allowed)
        assert all(results), f"Expected {burst_size} allowed requests, got {results}"

    def test_burst_exceeded_returns_denied(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.FREE)
        burst_size = TIER_CONFIGS[RateLimitTier.FREE].burst_size
        # Exhaust burst tokens
        for _ in range(burst_size):
            limiter.check_rate_limit("tenant-exhaust")
        # Next request should be denied (no time to refill)
        allowed, headers = limiter.check_rate_limit("tenant-exhaust")
        assert allowed is False
        assert "Retry-After" in headers
        assert int(headers["Retry-After"]) >= 1

    def test_tokens_refill_over_time(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.FREE)
        burst_size = TIER_CONFIGS[RateLimitTier.FREE].burst_size
        # Exhaust all burst tokens
        for _ in range(burst_size):
            limiter.check_rate_limit("tenant-refill")
        # Verify denied
        allowed, _ = limiter.check_rate_limit("tenant-refill")
        assert allowed is False

        # Simulate time passing for token refill
        # refill_rate = requests_per_minute / 60 tokens/sec
        # We need at least 1 token, so wait = 1 / refill_rate seconds
        config = TIER_CONFIGS[RateLimitTier.FREE]
        refill_rate = config.requests_per_minute / 60.0
        wait_time = 1.0 / refill_rate + 0.1  # a bit extra

        with patch("agent33.security.rate_limiter.time") as mock_time:
            # Set monotonic to simulate elapsed time
            base_time = time.monotonic()
            mock_time.monotonic.return_value = base_time + wait_time
            # Manually refill: adjust last_refill to base_time so elapsed = wait_time
            state = limiter._states["tenant-refill"]
            state.last_refill = base_time
            # Also set reset windows far in the future so they don't trigger
            state.minute_reset = base_time + 600
            state.hour_reset = base_time + 36000
            state.daily_reset = base_time + 864000
            # Reset counters to not hit per-minute limits
            state.request_count_minute = 0
            state.request_count_hour = 0
            state.request_count_daily = 0

            allowed, _ = limiter.check_rate_limit("tenant-refill")
            assert allowed is True


class TestPerTenantIsolation:
    """Test that rate limit state is isolated per tenant."""

    def test_different_tenants_have_independent_limits(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.FREE)
        burst_size = TIER_CONFIGS[RateLimitTier.FREE].burst_size
        # Exhaust tenant-a
        for _ in range(burst_size):
            limiter.check_rate_limit("tenant-a")
        allowed_a, _ = limiter.check_rate_limit("tenant-a")
        assert allowed_a is False

        # tenant-b should still be allowed
        allowed_b, _ = limiter.check_rate_limit("tenant-b")
        assert allowed_b is True

    def test_quota_tracks_per_tenant(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.STANDARD)
        # Make 3 requests for tenant-x, 1 for tenant-y
        for _ in range(3):
            limiter.check_rate_limit("tenant-x")
        limiter.check_rate_limit("tenant-y")

        quota_x = limiter.get_tenant_quota("tenant-x")
        quota_y = limiter.get_tenant_quota("tenant-y")
        assert quota_x.used_this_minute == 3
        assert quota_y.used_this_minute == 1


class TestTierEnforcement:
    """Test that different tiers have different limits."""

    def test_free_tier_has_lower_limits_than_standard(self) -> None:
        free_config = TIER_CONFIGS[RateLimitTier.FREE]
        standard_config = TIER_CONFIGS[RateLimitTier.STANDARD]
        assert free_config.requests_per_minute < standard_config.requests_per_minute
        assert free_config.daily_quota < standard_config.daily_quota
        assert free_config.burst_size < standard_config.burst_size

    def test_premium_tier_has_higher_limits_than_standard(self) -> None:
        standard_config = TIER_CONFIGS[RateLimitTier.STANDARD]
        premium_config = TIER_CONFIGS[RateLimitTier.PREMIUM]
        assert premium_config.requests_per_minute > standard_config.requests_per_minute
        assert premium_config.daily_quota > standard_config.daily_quota

    def test_unlimited_tier_always_allows(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.UNLIMITED)
        for _ in range(100):
            allowed, headers = limiter.check_rate_limit("tenant-unlimited")
            assert allowed is True
            assert headers["X-RateLimit-Limit"] == "unlimited"

    def test_set_tenant_tier_changes_limits(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.FREE)
        free_burst = TIER_CONFIGS[RateLimitTier.FREE].burst_size

        # Exhaust free tier burst
        for _ in range(free_burst):
            limiter.check_rate_limit("tenant-upgrade")
        allowed, _ = limiter.check_rate_limit("tenant-upgrade")
        assert allowed is False

        # Upgrade to premium — state is reset, so full burst available
        limiter.set_tenant_tier("tenant-upgrade", RateLimitTier.PREMIUM)
        premium_burst = TIER_CONFIGS[RateLimitTier.PREMIUM].burst_size
        results = []
        for _ in range(premium_burst):
            allowed, _ = limiter.check_rate_limit("tenant-upgrade")
            results.append(allowed)
        assert all(results)

    def test_explicit_tier_overrides_default(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.STANDARD)
        limiter.set_tenant_tier("tenant-free", RateLimitTier.FREE)

        quota = limiter.get_tenant_quota("tenant-free")
        assert quota.tier == "free"
        assert quota.limit_this_minute == TIER_CONFIGS[RateLimitTier.FREE].requests_per_minute


class TestRateLimitHeaders:
    """Test that correct X-RateLimit-* headers are returned."""

    def test_allowed_request_includes_limit_and_remaining(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.STANDARD)
        allowed, headers = limiter.check_rate_limit("tenant-hdr")
        assert allowed is True
        assert "X-RateLimit-Limit" in headers
        assert "X-RateLimit-Remaining" in headers
        assert "X-RateLimit-Reset" in headers

        limit = int(headers["X-RateLimit-Limit"])
        remaining = int(headers["X-RateLimit-Remaining"])
        assert limit == TIER_CONFIGS[RateLimitTier.STANDARD].requests_per_minute
        assert remaining == limit - 1  # one request consumed

    def test_denied_request_includes_retry_after(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.FREE)
        burst = TIER_CONFIGS[RateLimitTier.FREE].burst_size
        for _ in range(burst):
            limiter.check_rate_limit("tenant-deny-hdr")
        allowed, headers = limiter.check_rate_limit("tenant-deny-hdr")
        assert allowed is False
        assert "Retry-After" in headers
        assert int(headers["Retry-After"]) >= 1

    def test_remaining_decrements_with_each_request(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.STANDARD)
        _, headers1 = limiter.check_rate_limit("tenant-decrement")
        _, headers2 = limiter.check_rate_limit("tenant-decrement")
        remaining1 = int(headers1["X-RateLimit-Remaining"])
        remaining2 = int(headers2["X-RateLimit-Remaining"])
        assert remaining2 == remaining1 - 1


class TestQuotaTracking:
    """Test quota tracking accuracy."""

    def test_get_tenant_quota_default(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.STANDARD)
        quota = limiter.get_tenant_quota("new-tenant")
        assert quota.tenant_id == "new-tenant"
        assert quota.tier == "standard"
        assert quota.used_today == 0
        assert quota.used_this_hour == 0
        assert quota.used_this_minute == 0
        assert quota.limit_today == TIER_CONFIGS[RateLimitTier.STANDARD].daily_quota
        assert quota.limit_this_hour == TIER_CONFIGS[RateLimitTier.STANDARD].requests_per_hour

    def test_quota_increments_after_requests(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.STANDARD)
        for _ in range(5):
            limiter.check_rate_limit("tenant-track")
        quota = limiter.get_tenant_quota("tenant-track")
        assert quota.used_this_minute == 5
        assert quota.used_this_hour == 5
        assert quota.used_today == 5

    def test_get_all_quotas_returns_all_tracked(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.STANDARD)
        limiter.check_rate_limit("alpha")
        limiter.check_rate_limit("beta")
        limiter.check_rate_limit("gamma")
        quotas = limiter.get_all_quotas()
        ids = {q.tenant_id for q in quotas}
        assert ids == {"alpha", "beta", "gamma"}

    def test_reset_clears_counters(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.STANDARD)
        for _ in range(10):
            limiter.check_rate_limit("tenant-reset")
        quota_before = limiter.get_tenant_quota("tenant-reset")
        assert quota_before.used_this_minute == 10

        limiter.reset_tenant("tenant-reset")
        quota_after = limiter.get_tenant_quota("tenant-reset")
        assert quota_after.used_this_minute == 0
        assert quota_after.used_this_hour == 0
        assert quota_after.used_today == 0


class TestPerMinuteLimitEnforcement:
    """Test that per-minute counter enforcement works independently of burst."""

    def test_per_minute_limit_blocks_after_exhaustion(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.FREE)
        config = TIER_CONFIGS[RateLimitTier.FREE]
        # The per-minute limit (10) exceeds burst_size (5), so burst will
        # block first. This test verifies the per-minute counter also works.
        # We need to slowly consume requests with token refills to bypass burst.
        # For simplicity, directly manipulate state.
        limiter.check_rate_limit("tenant-pm")  # initialize state
        state = limiter._states["tenant-pm"]
        # Set tokens high enough that burst isn't the bottleneck
        state.tokens = 100.0
        state.max_tokens = 100.0
        # Set minute counter at limit - 1
        state.request_count_minute = config.requests_per_minute - 1
        state.minute_reset = time.monotonic() + 60  # far in the future

        # One more should be allowed (hitting the limit)
        allowed, _ = limiter.check_rate_limit("tenant-pm")
        assert allowed is True

        # Next should be denied by per-minute counter
        allowed, headers = limiter.check_rate_limit("tenant-pm")
        assert allowed is False
        assert "Retry-After" in headers


class TestConcurrentAccess:
    """Test thread safety under concurrent access."""

    def test_concurrent_requests_dont_corrupt_state(self) -> None:
        limiter = RateLimiter(default_tier=RateLimitTier.PREMIUM)
        errors: list[Exception] = []
        results: list[bool] = []
        lock = threading.Lock()

        def make_requests() -> None:
            try:
                for _ in range(50):
                    allowed, _ = limiter.check_rate_limit("concurrent-tenant")
                    with lock:
                        results.append(allowed)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=make_requests) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent access errors: {errors}"
        assert len(results) == 500
        # State should be consistent: request_count_minute should match
        # the number of allowed requests
        quota = limiter.get_tenant_quota("concurrent-tenant")
        allowed_count = sum(1 for r in results if r)
        assert quota.used_this_minute == allowed_count


# ---------------------------------------------------------------------------
# Integration tests: middleware + admin endpoints via ASGI
# ---------------------------------------------------------------------------


@pytest.fixture()
def _app_with_rate_limiter():
    """Create a minimal FastAPI app with auth and rate limit middleware."""
    from fastapi import FastAPI, Request
    from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

    from agent33.api.routes.rate_limits import router as rate_limits_router
    from agent33.security.auth import TokenPayload

    app = FastAPI()

    rate_limiter = RateLimiter(default_tier=RateLimitTier.FREE)
    app.state.rate_limiter = rate_limiter

    # Fake auth middleware that sets a fixed tenant
    class FakeAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(  # type: ignore[override]
            self, request: Request, call_next: RequestResponseEndpoint
        ):
            path = request.url.path
            if path in ("/health", "/docs", "/openapi.json"):
                return await call_next(request)
            request.state.user = TokenPayload(
                sub="test-user",
                scopes=["admin"],
                tenant_id="test-tenant",
            )
            return await call_next(request)

    # Middleware order: RateLimit first (runs second), FakeAuth last (runs first)
    app.add_middleware(RateLimitMiddleware, rate_limiter=rate_limiter)
    app.add_middleware(FakeAuthMiddleware)

    @app.get("/health")
    async def health_endpoint():
        return {"status": "ok"}

    @app.get("/v1/test")
    async def test_endpoint():
        return {"message": "ok"}

    app.include_router(rate_limits_router)

    return app, rate_limiter


@pytest.mark.asyncio
async def test_middleware_returns_429_when_rate_limited(_app_with_rate_limiter) -> None:
    app, limiter = _app_with_rate_limiter
    burst = TIER_CONFIGS[RateLimitTier.FREE].burst_size

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Exhaust burst
        for _ in range(burst):
            resp = await client.get("/v1/test")
            assert resp.status_code == 200

        # Next request should be 429
        resp = await client.get("/v1/test")
        assert resp.status_code == 429
        body = resp.json()
        assert body["detail"] == "Rate limit exceeded"
        assert "Retry-After" in resp.headers


@pytest.mark.asyncio
async def test_middleware_sets_rate_limit_headers_on_success(
    _app_with_rate_limiter,
) -> None:
    app, _ = _app_with_rate_limiter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/test")
        assert resp.status_code == 200
        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers
        assert "X-RateLimit-Reset" in resp.headers


@pytest.mark.asyncio
async def test_middleware_bypasses_health_endpoint(_app_with_rate_limiter) -> None:
    app, limiter = _app_with_rate_limiter
    burst = TIER_CONFIGS[RateLimitTier.FREE].burst_size

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Exhaust rate limit
        for _ in range(burst):
            await client.get("/v1/test")

        # Health should still work even after rate limit exceeded
        for _ in range(5):
            resp = await client.get("/health")
            assert resp.status_code == 200


@pytest.mark.asyncio
async def test_admin_list_quotas(_app_with_rate_limiter) -> None:
    app, limiter = _app_with_rate_limiter
    # Generate some traffic
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/v1/test")
        resp = await client.get("/v1/admin/rate-limits")
        assert resp.status_code == 200
        body = resp.json()
        assert "quotas" in body
        assert len(body["quotas"]) >= 1
        tenant_ids = {q["tenant_id"] for q in body["quotas"]}
        assert "test-tenant" in tenant_ids


@pytest.mark.asyncio
async def test_admin_get_tenant_quota(_app_with_rate_limiter) -> None:
    app, _ = _app_with_rate_limiter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/v1/test")  # generate one request
        resp = await client.get("/v1/admin/rate-limits/test-tenant")
        assert resp.status_code == 200
        body = resp.json()
        assert body["tenant_id"] == "test-tenant"
        assert body["tier"] == "free"
        assert body["used_this_minute"] >= 1


@pytest.mark.asyncio
async def test_admin_set_tier(_app_with_rate_limiter) -> None:
    app, limiter = _app_with_rate_limiter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            "/v1/admin/rate-limits/test-tenant/tier",
            json={"tier": "premium"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["tenant_id"] == "test-tenant"
        assert body["tier"] == "premium"

        # Verify tier changed
        resp = await client.get("/v1/admin/rate-limits/test-tenant")
        assert resp.status_code == 200
        assert resp.json()["tier"] == "premium"


@pytest.mark.asyncio
async def test_admin_reset_tenant(_app_with_rate_limiter) -> None:
    app, limiter = _app_with_rate_limiter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Make some requests
        for _ in range(3):
            await client.get("/v1/test")

        # Reset
        resp = await client.post("/v1/admin/rate-limits/test-tenant/reset")
        assert resp.status_code == 200
        body = resp.json()
        assert body["tenant_id"] == "test-tenant"
        assert body["message"] == "Rate limit counters reset"

        # Verify counters reset — the GET itself counts as 1 request
        resp = await client.get("/v1/admin/rate-limits/test-tenant")
        assert resp.status_code == 200
        # After reset, only this GET request went through, so used_this_minute == 1
        assert resp.json()["used_this_minute"] == 1


@pytest.mark.asyncio
async def test_admin_list_tiers(_app_with_rate_limiter) -> None:
    app, _ = _app_with_rate_limiter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/admin/rate-limits/tiers")
        assert resp.status_code == 200
        body = resp.json()
        assert "tiers" in body
        tier_names = {t["tier"] for t in body["tiers"]}
        assert tier_names == {"free", "standard", "premium", "unlimited"}
        for tier_entry in body["tiers"]:
            assert "config" in tier_entry
            config = tier_entry["config"]
            assert "requests_per_minute" in config
            assert "requests_per_hour" in config
            assert "daily_quota" in config
            assert "burst_size" in config


@pytest.mark.asyncio
async def test_admin_set_invalid_tier_returns_422(_app_with_rate_limiter) -> None:
    app, _ = _app_with_rate_limiter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            "/v1/admin/rate-limits/test-tenant/tier",
            json={"tier": "nonexistent"},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_middleware_handles_missing_tenant_id() -> None:
    """Middleware falls back to 'sub' when tenant_id is empty."""
    from fastapi import FastAPI, Request
    from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

    from agent33.security.auth import TokenPayload

    app = FastAPI()
    rate_limiter = RateLimiter(default_tier=RateLimitTier.STANDARD)
    app.state.rate_limiter = rate_limiter

    class AuthWithNoTenantId(BaseHTTPMiddleware):
        async def dispatch(  # type: ignore[override]
            self, request: Request, call_next: RequestResponseEndpoint
        ):
            request.state.user = TokenPayload(
                sub="fallback-user",
                scopes=["admin"],
                tenant_id="",
            )
            return await call_next(request)

    app.add_middleware(RateLimitMiddleware, rate_limiter=rate_limiter)
    app.add_middleware(AuthWithNoTenantId)

    @app.get("/v1/test")
    async def test_endpoint():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/test")
        assert resp.status_code == 200

    # Check that the fallback "sub" was used as tenant_id
    quota = rate_limiter.get_tenant_quota("fallback-user")
    assert quota.used_this_minute == 1


@pytest.mark.asyncio
async def test_rate_limit_resets_after_tier_upgrade(_app_with_rate_limiter) -> None:
    """After upgrading tier, tenant can make requests again."""
    app, limiter = _app_with_rate_limiter
    burst = TIER_CONFIGS[RateLimitTier.FREE].burst_size

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Exhaust free tier burst
        for _ in range(burst):
            resp = await client.get("/v1/test")
            assert resp.status_code == 200

        resp = await client.get("/v1/test")
        assert resp.status_code == 429

        # Upgrade to unlimited via direct limiter call (since the HTTP endpoint
        # itself is also rate-limited and would get a 429)
        limiter.set_tenant_tier("test-tenant", RateLimitTier.UNLIMITED)

        # Should be allowed now
        resp = await client.get("/v1/test")
        assert resp.status_code == 200
