"""Tests for webhook delivery reliability: manager lifecycle, retries, dead-lettering, API."""

from __future__ import annotations

import threading
import time

import pytest
from httpx import ASGITransport, AsyncClient

from agent33.automation.webhook_delivery import (
    DeliveryAttempt,
    DeliveryStats,
    WebhookDeliveryManager,
    WebhookDeliveryRecord,
    WebhookDeliveryStatus,
)
from agent33.main import app

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestWebhookDeliveryStatus:
    def test_all_statuses_exist(self) -> None:
        statuses = {s.value for s in WebhookDeliveryStatus}
        assert statuses == {
            "pending",
            "in_flight",
            "delivered",
            "failed",
            "retrying",
            "dead_lettered",
        }


class TestDeliveryAttempt:
    def test_default_fields(self) -> None:
        attempt = DeliveryAttempt(attempt_number=1)
        assert attempt.attempt_number == 1
        assert attempt.status_code == 0
        assert attempt.response_body == ""
        assert attempt.duration_ms == 0.0
        assert attempt.error_message == ""
        assert attempt.timestamp > 0

    def test_full_fields(self) -> None:
        attempt = DeliveryAttempt(
            attempt_number=3,
            status_code=502,
            response_body="Bad Gateway",
            duration_ms=150.5,
            error_message="upstream timeout",
        )
        assert attempt.attempt_number == 3
        assert attempt.status_code == 502
        assert attempt.response_body == "Bad Gateway"
        assert attempt.duration_ms == 150.5
        assert attempt.error_message == "upstream timeout"


class TestWebhookDeliveryRecord:
    def test_default_record(self) -> None:
        record = WebhookDeliveryRecord()
        assert len(record.delivery_id) == 32
        assert record.webhook_id == ""
        assert record.url == ""
        assert record.payload == {}
        assert record.headers == {}
        assert record.status == WebhookDeliveryStatus.PENDING
        assert record.attempts == []
        assert record.created_at > 0
        assert record.next_retry_at is None
        assert record.max_retries == 5
        assert record.current_retry == 0

    def test_record_with_values(self) -> None:
        record = WebhookDeliveryRecord(
            webhook_id="wh-123",
            url="https://example.com/hook",
            payload={"event": "deploy"},
            headers={"Authorization": "Bearer tok"},
            max_retries=3,
        )
        assert record.webhook_id == "wh-123"
        assert record.url == "https://example.com/hook"
        assert record.payload == {"event": "deploy"}
        assert record.headers["Authorization"] == "Bearer tok"
        assert record.max_retries == 3


class TestDeliveryStats:
    def test_default_stats(self) -> None:
        stats = DeliveryStats()
        assert stats.total == 0
        assert stats.delivered == 0
        assert stats.failed == 0
        assert stats.retrying == 0
        assert stats.dead_lettered == 0
        assert stats.avg_latency_ms == 0.0


# ---------------------------------------------------------------------------
# Manager: enqueue and lifecycle tests
# ---------------------------------------------------------------------------


class TestWebhookDeliveryManagerEnqueue:
    def test_enqueue_returns_delivery_id(self) -> None:
        mgr = WebhookDeliveryManager()
        did = mgr.enqueue("wh-1", "https://example.com/hook", {"event": "push"})
        assert isinstance(did, str)
        assert len(did) == 32

    def test_enqueue_creates_pending_record(self) -> None:
        mgr = WebhookDeliveryManager()
        did = mgr.enqueue("wh-1", "https://example.com", {"key": "val"})
        record = mgr.get_delivery(did)
        assert record is not None
        assert record.status == WebhookDeliveryStatus.PENDING
        assert record.webhook_id == "wh-1"
        assert record.url == "https://example.com"
        assert record.payload == {"key": "val"}

    def test_enqueue_with_custom_headers(self) -> None:
        mgr = WebhookDeliveryManager()
        did = mgr.enqueue("wh-2", "https://example.com", {}, headers={"X-Token": "secret"})
        record = mgr.get_delivery(did)
        assert record is not None
        assert record.headers == {"X-Token": "secret"}

    def test_enqueue_uses_configured_max_retries(self) -> None:
        mgr = WebhookDeliveryManager(max_retries=3)
        did = mgr.enqueue("wh-1", "https://example.com", {})
        record = mgr.get_delivery(did)
        assert record is not None
        assert record.max_retries == 3

    def test_get_delivery_returns_none_for_unknown_id(self) -> None:
        mgr = WebhookDeliveryManager()
        assert mgr.get_delivery("nonexistent") is None


# ---------------------------------------------------------------------------
# Manager: delivery attempt + process_result
# ---------------------------------------------------------------------------


class TestWebhookDeliveryManagerDelivery:
    def test_successful_delivery_lifecycle(self) -> None:
        """Enqueue -> attempt -> process(200) -> status = DELIVERED."""
        mgr = WebhookDeliveryManager()
        did = mgr.enqueue("wh-1", "https://example.com/hook", {"event": "deploy"})

        attempt = mgr.attempt_delivery(did)
        assert attempt.attempt_number == 1
        assert attempt.status_code == 200

        mgr.process_result(did, attempt)
        record = mgr.get_delivery(did)
        assert record is not None
        assert record.status == WebhookDeliveryStatus.DELIVERED
        assert len(record.attempts) == 1
        assert record.next_retry_at is None

    def test_failed_delivery_triggers_retry(self) -> None:
        """A 500 response should schedule a retry, not dead-letter."""
        mgr = WebhookDeliveryManager(max_retries=3)
        did = mgr.enqueue("wh-1", "https://example.com", {})

        failed_attempt = DeliveryAttempt(
            attempt_number=1,
            status_code=500,
            response_body="Internal Server Error",
            duration_ms=50.0,
        )
        mgr.process_result(did, failed_attempt)

        record = mgr.get_delivery(did)
        assert record is not None
        assert record.status == WebhookDeliveryStatus.RETRYING
        assert record.current_retry == 1
        assert record.next_retry_at is not None
        assert record.next_retry_at > time.time() - 1  # should be in the future

    def test_max_retries_triggers_dead_letter(self) -> None:
        """After max_retries failures the delivery should be dead-lettered."""
        mgr = WebhookDeliveryManager(max_retries=2)
        did = mgr.enqueue("wh-1", "https://example.com", {})

        # Attempt 1: fail
        mgr.process_result(
            did,
            DeliveryAttempt(attempt_number=1, status_code=503, duration_ms=10.0),
        )
        record = mgr.get_delivery(did)
        assert record is not None
        assert record.status == WebhookDeliveryStatus.RETRYING

        # Attempt 2: fail again (reaches max_retries=2)
        mgr.process_result(
            did,
            DeliveryAttempt(attempt_number=2, status_code=503, duration_ms=10.0),
        )
        record = mgr.get_delivery(did)
        assert record is not None
        assert record.status == WebhookDeliveryStatus.DEAD_LETTERED
        assert record.next_retry_at is None
        assert len(record.attempts) == 2

    def test_delivery_attempt_records_error_message(self) -> None:
        mgr = WebhookDeliveryManager()
        did = mgr.enqueue("wh-1", "https://example.com", {})

        attempt = DeliveryAttempt(
            attempt_number=1,
            status_code=0,
            error_message="Connection refused",
            duration_ms=5.0,
        )
        mgr.process_result(did, attempt)

        record = mgr.get_delivery(did)
        assert record is not None
        assert record.attempts[0].error_message == "Connection refused"
        assert record.attempts[0].status_code == 0

    def test_attempt_delivery_raises_for_unknown_id(self) -> None:
        mgr = WebhookDeliveryManager()
        with pytest.raises(KeyError, match="Delivery record not found"):
            mgr.attempt_delivery("nonexistent")

    def test_process_result_raises_for_unknown_id(self) -> None:
        mgr = WebhookDeliveryManager()
        attempt = DeliveryAttempt(attempt_number=1, status_code=200)
        with pytest.raises(KeyError, match="Delivery record not found"):
            mgr.process_result("nonexistent", attempt)


# ---------------------------------------------------------------------------
# Manager: exponential backoff
# ---------------------------------------------------------------------------


class TestExponentialBackoff:
    def test_backoff_increases_with_attempts(self) -> None:
        mgr = WebhookDeliveryManager(base_delay_seconds=1.0, max_delay_seconds=300.0)
        # backoff = min(base * 2^attempt, max) * jitter
        # Attempt 0: min(1*1, 300) * [0.5, 1.0] = [0.5, 1.0]
        # Attempt 3: min(1*8, 300) * [0.5, 1.0] = [4.0, 8.0]
        b0 = mgr.compute_backoff(0)
        b3 = mgr.compute_backoff(3)
        # b3 should be larger than b0 on average; check minimums
        assert 0.5 <= b0 <= 1.0
        assert 4.0 <= b3 <= 8.0

    def test_backoff_caps_at_max_delay(self) -> None:
        mgr = WebhookDeliveryManager(
            base_delay_seconds=1.0,
            max_delay_seconds=10.0,
        )
        # Attempt 20: min(1*2^20, 10) * jitter = 10 * [0.5, 1.0]
        b20 = mgr.compute_backoff(20)
        assert b20 <= 10.0

    def test_backoff_returns_positive(self) -> None:
        mgr = WebhookDeliveryManager()
        for attempt in range(10):
            assert mgr.compute_backoff(attempt) > 0


# ---------------------------------------------------------------------------
# Manager: stats
# ---------------------------------------------------------------------------


class TestDeliveryStatsComputation:
    def test_empty_stats(self) -> None:
        mgr = WebhookDeliveryManager()
        stats = mgr.get_stats()
        assert stats.total == 0
        assert stats.avg_latency_ms == 0.0

    def test_stats_after_deliveries(self) -> None:
        mgr = WebhookDeliveryManager(max_retries=1)

        # One delivered
        did1 = mgr.enqueue("wh-1", "https://example.com", {})
        mgr.process_result(
            did1,
            DeliveryAttempt(attempt_number=1, status_code=200, duration_ms=50.0),
        )

        # One dead-lettered
        did2 = mgr.enqueue("wh-2", "https://example.com", {})
        mgr.process_result(
            did2,
            DeliveryAttempt(attempt_number=1, status_code=500, duration_ms=30.0),
        )

        # One pending
        mgr.enqueue("wh-3", "https://example.com", {})

        stats = mgr.get_stats()
        assert stats.total == 3
        assert stats.delivered == 1
        assert stats.dead_lettered == 1
        assert stats.avg_latency_ms == 50.0  # only successful attempt counted


# ---------------------------------------------------------------------------
# Manager: dead letter and retry
# ---------------------------------------------------------------------------


class TestDeadLetterManagement:
    def test_get_dead_letters(self) -> None:
        mgr = WebhookDeliveryManager(max_retries=1)

        # Dead-letter one
        did = mgr.enqueue("wh-1", "https://example.com", {"event": "test"})
        mgr.process_result(
            did,
            DeliveryAttempt(attempt_number=1, status_code=500),
        )

        dead = mgr.get_dead_letters()
        assert len(dead) == 1
        assert dead[0].delivery_id == did
        assert dead[0].status == WebhookDeliveryStatus.DEAD_LETTERED

    def test_retry_dead_letter_resets_state(self) -> None:
        mgr = WebhookDeliveryManager(max_retries=1)
        did = mgr.enqueue("wh-1", "https://example.com", {})
        mgr.process_result(
            did,
            DeliveryAttempt(attempt_number=1, status_code=500),
        )

        mgr.retry_dead_letter(did)

        record = mgr.get_delivery(did)
        assert record is not None
        assert record.status == WebhookDeliveryStatus.PENDING
        assert record.current_retry == 0
        assert record.attempts == []
        assert record.next_retry_at is None

    def test_retry_non_dead_letter_raises(self) -> None:
        mgr = WebhookDeliveryManager()
        did = mgr.enqueue("wh-1", "https://example.com", {})
        with pytest.raises(ValueError, match="only dead_lettered"):
            mgr.retry_dead_letter(did)

    def test_retry_unknown_raises(self) -> None:
        mgr = WebhookDeliveryManager()
        with pytest.raises(KeyError, match="Delivery record not found"):
            mgr.retry_dead_letter("nonexistent")


# ---------------------------------------------------------------------------
# Manager: list and filter
# ---------------------------------------------------------------------------


class TestListDeliveries:
    def test_list_returns_newest_first(self) -> None:
        mgr = WebhookDeliveryManager()
        did1 = mgr.enqueue("wh-1", "https://example.com", {})
        did2 = mgr.enqueue("wh-2", "https://example.com", {})

        results = mgr.list_deliveries()
        assert len(results) == 2
        # Newest first (reversed OrderedDict iteration)
        assert results[0].delivery_id == did2
        assert results[1].delivery_id == did1

    def test_list_filters_by_status(self) -> None:
        mgr = WebhookDeliveryManager()
        did1 = mgr.enqueue("wh-1", "https://example.com", {})
        did2 = mgr.enqueue("wh-2", "https://example.com", {})
        mgr.process_result(
            did1,
            DeliveryAttempt(attempt_number=1, status_code=200),
        )

        delivered = mgr.list_deliveries(status=WebhookDeliveryStatus.DELIVERED)
        assert len(delivered) == 1
        assert delivered[0].delivery_id == did1

        pending = mgr.list_deliveries(status=WebhookDeliveryStatus.PENDING)
        assert len(pending) == 1
        assert pending[0].delivery_id == did2

    def test_list_filters_by_webhook_id(self) -> None:
        mgr = WebhookDeliveryManager()
        mgr.enqueue("wh-alpha", "https://example.com", {})
        mgr.enqueue("wh-beta", "https://example.com", {})
        mgr.enqueue("wh-alpha", "https://example.com", {})

        alpha = mgr.list_deliveries(webhook_id="wh-alpha")
        assert len(alpha) == 2
        for r in alpha:
            assert r.webhook_id == "wh-alpha"

    def test_list_respects_limit(self) -> None:
        mgr = WebhookDeliveryManager()
        for i in range(10):
            mgr.enqueue(f"wh-{i}", "https://example.com", {})

        results = mgr.list_deliveries(limit=3)
        assert len(results) == 3


# ---------------------------------------------------------------------------
# Manager: purge
# ---------------------------------------------------------------------------


class TestPurgeDelivered:
    def test_purge_removes_old_delivered(self) -> None:
        mgr = WebhookDeliveryManager()
        did = mgr.enqueue("wh-1", "https://example.com", {})
        mgr.process_result(
            did,
            DeliveryAttempt(attempt_number=1, status_code=200),
        )

        # Manually set created_at to 48 hours ago
        with mgr._lock:
            mgr._records[did].created_at = time.time() - 48 * 3600

        purged = mgr.purge_delivered(older_than_hours=24.0)
        assert purged == 1
        assert mgr.get_delivery(did) is None

    def test_purge_does_not_remove_recent(self) -> None:
        mgr = WebhookDeliveryManager()
        did = mgr.enqueue("wh-1", "https://example.com", {})
        mgr.process_result(
            did,
            DeliveryAttempt(attempt_number=1, status_code=200),
        )

        purged = mgr.purge_delivered(older_than_hours=24.0)
        assert purged == 0
        assert mgr.get_delivery(did) is not None

    def test_purge_does_not_remove_non_delivered(self) -> None:
        mgr = WebhookDeliveryManager()
        did = mgr.enqueue("wh-1", "https://example.com", {})

        # Manually set created_at to 48 hours ago (but status is PENDING)
        with mgr._lock:
            mgr._records[did].created_at = time.time() - 48 * 3600

        purged = mgr.purge_delivered(older_than_hours=24.0)
        assert purged == 0


# ---------------------------------------------------------------------------
# Manager: bounded storage eviction
# ---------------------------------------------------------------------------


class TestBoundedStorage:
    def test_evicts_delivered_first(self) -> None:
        mgr = WebhookDeliveryManager(max_records=3)
        did1 = mgr.enqueue("wh-1", "https://example.com", {})
        mgr.process_result(
            did1,
            DeliveryAttempt(attempt_number=1, status_code=200),
        )
        mgr.enqueue("wh-2", "https://example.com", {})
        mgr.enqueue("wh-3", "https://example.com", {})

        # Should evict did1 (delivered) to make room
        did4 = mgr.enqueue("wh-4", "https://example.com", {})

        assert mgr.get_delivery(did1) is None  # evicted
        assert mgr.get_delivery(did4) is not None

    def test_evicts_oldest_when_no_delivered(self) -> None:
        mgr = WebhookDeliveryManager(max_records=2)
        did1 = mgr.enqueue("wh-1", "https://example.com", {})
        mgr.enqueue("wh-2", "https://example.com", {})

        # Both are PENDING; oldest (did1) should be evicted
        did3 = mgr.enqueue("wh-3", "https://example.com", {})

        assert mgr.get_delivery(did1) is None
        assert mgr.get_delivery(did3) is not None

    def test_storage_never_exceeds_max(self) -> None:
        mgr = WebhookDeliveryManager(max_records=5)
        for i in range(20):
            mgr.enqueue(f"wh-{i}", "https://example.com", {})

        stats = mgr.get_stats()
        assert stats.total <= 5


# ---------------------------------------------------------------------------
# Manager: thread safety
# ---------------------------------------------------------------------------


class TestConcurrentDelivery:
    def test_concurrent_enqueue_is_safe(self) -> None:
        mgr = WebhookDeliveryManager(max_records=500)
        delivery_ids: list[str] = []
        lock = threading.Lock()
        errors: list[Exception] = []

        def enqueue_batch(start: int, count: int) -> None:
            try:
                for i in range(start, start + count):
                    did = mgr.enqueue(f"wh-{i}", "https://example.com", {"i": i})
                    with lock:
                        delivery_ids.append(did)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=enqueue_batch, args=(i * 50, 50)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # All 200 should have been enqueued (max_records=500)
        assert len(delivery_ids) == 200
        # All IDs should be unique
        assert len(set(delivery_ids)) == 200


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


def _install_webhook_delivery(mgr: WebhookDeliveryManager | None = None) -> None:
    """Install webhook delivery manager on app.state for API tests."""
    if mgr is None:
        mgr = WebhookDeliveryManager(max_retries=2)
    app.state.webhook_delivery = mgr


def _auth_headers() -> dict[str, str]:
    """Return headers that pass the AuthMiddleware for testing."""
    import jwt

    from agent33.config import settings

    token = jwt.encode(
        {"sub": "test-user", "tenant_id": "test-tenant", "scopes": ["admin"]},
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


class TestWebhookDeliveryAPI:
    @pytest.mark.asyncio
    async def test_list_deliveries_empty(self) -> None:
        _install_webhook_delivery()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/webhooks/deliveries")
            assert resp.status_code == 200
            body = resp.json()
            assert body["deliveries"] == []
            assert body["count"] == 0

    @pytest.mark.asyncio
    async def test_list_deliveries_with_records(self) -> None:
        mgr = WebhookDeliveryManager()
        mgr.enqueue("wh-1", "https://example.com", {"event": "push"})
        mgr.enqueue("wh-2", "https://example.com", {"event": "deploy"})
        _install_webhook_delivery(mgr)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/webhooks/deliveries")
            assert resp.status_code == 200
            body = resp.json()
            assert body["count"] == 2
            assert len(body["deliveries"]) == 2

    @pytest.mark.asyncio
    async def test_list_deliveries_filter_by_status(self) -> None:
        mgr = WebhookDeliveryManager()
        did1 = mgr.enqueue("wh-1", "https://example.com", {})
        mgr.process_result(did1, DeliveryAttempt(attempt_number=1, status_code=200))
        mgr.enqueue("wh-2", "https://example.com", {})
        _install_webhook_delivery(mgr)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/webhooks/deliveries", params={"status": "delivered"})
            assert resp.status_code == 200
            body = resp.json()
            assert body["count"] == 1
            assert body["deliveries"][0]["status"] == "delivered"

    @pytest.mark.asyncio
    async def test_get_delivery_detail(self) -> None:
        mgr = WebhookDeliveryManager()
        did = mgr.enqueue("wh-1", "https://example.com/hook", {"key": "val"})
        attempt = DeliveryAttempt(attempt_number=1, status_code=200, duration_ms=25.0)
        mgr.process_result(did, attempt)
        _install_webhook_delivery(mgr)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get(f"/v1/webhooks/deliveries/{did}")
            assert resp.status_code == 200
            body = resp.json()
            assert body["delivery_id"] == did
            assert body["status"] == "delivered"
            assert len(body["attempts"]) == 1
            assert body["attempts"][0]["status_code"] == 200

    @pytest.mark.asyncio
    async def test_get_delivery_not_found(self) -> None:
        _install_webhook_delivery()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/webhooks/deliveries/nonexistent")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delivery_stats_endpoint(self) -> None:
        mgr = WebhookDeliveryManager(max_retries=1)
        did = mgr.enqueue("wh-1", "https://example.com", {})
        mgr.process_result(
            did, DeliveryAttempt(attempt_number=1, status_code=200, duration_ms=42.0)
        )
        _install_webhook_delivery(mgr)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/webhooks/deliveries/stats")
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 1
            assert body["delivered"] == 1
            assert body["avg_latency_ms"] == 42.0

    @pytest.mark.asyncio
    async def test_dead_letters_endpoint(self) -> None:
        mgr = WebhookDeliveryManager(max_retries=1)
        did = mgr.enqueue("wh-1", "https://example.com", {})
        mgr.process_result(did, DeliveryAttempt(attempt_number=1, status_code=500))
        _install_webhook_delivery(mgr)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/webhooks/deliveries/dead-letters")
            assert resp.status_code == 200
            body = resp.json()
            assert body["count"] == 1
            assert body["deliveries"][0]["status"] == "dead_lettered"

    @pytest.mark.asyncio
    async def test_retry_dead_letter_endpoint(self) -> None:
        mgr = WebhookDeliveryManager(max_retries=1)
        did = mgr.enqueue("wh-1", "https://example.com", {})
        mgr.process_result(did, DeliveryAttempt(attempt_number=1, status_code=500))
        _install_webhook_delivery(mgr)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.post(f"/v1/webhooks/deliveries/{did}/retry")
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "re-enqueued"
            assert body["delivery_id"] == did

            # Verify it's now pending
            resp2 = await client.get(f"/v1/webhooks/deliveries/{did}")
            assert resp2.status_code == 200
            assert resp2.json()["status"] == "pending"

    @pytest.mark.asyncio
    async def test_retry_pending_returns_409(self) -> None:
        mgr = WebhookDeliveryManager()
        did = mgr.enqueue("wh-1", "https://example.com", {})
        _install_webhook_delivery(mgr)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.post(f"/v1/webhooks/deliveries/{did}/retry")
            assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_retry_not_found_returns_404(self) -> None:
        _install_webhook_delivery()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.post("/v1/webhooks/deliveries/nonexistent/retry")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_purge_endpoint(self) -> None:
        mgr = WebhookDeliveryManager()
        did = mgr.enqueue("wh-1", "https://example.com", {})
        mgr.process_result(did, DeliveryAttempt(attempt_number=1, status_code=200))
        # Backdate to 48 hours
        with mgr._lock:
            mgr._records[did].created_at = time.time() - 48 * 3600
        _install_webhook_delivery(mgr)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.delete(
                "/v1/webhooks/deliveries/purge",
                params={"older_than_hours": 24.0},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["purged"] == 1

    @pytest.mark.asyncio
    async def test_401_without_auth(self) -> None:
        _install_webhook_delivery()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/v1/webhooks/deliveries")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_503_when_manager_missing(self) -> None:
        # Remove the manager from app.state
        if hasattr(app.state, "webhook_delivery"):
            delattr(app.state, "webhook_delivery")

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/webhooks/deliveries")
            assert resp.status_code == 503
            assert "not initialized" in resp.json()["detail"]
