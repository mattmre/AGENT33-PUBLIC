"""Webhook delivery reliability: retries with exponential backoff, receipts, dead-lettering."""

from __future__ import annotations

import logging
import random
import threading
import time
import uuid
from collections import OrderedDict
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.observability.metrics import MetricsCollector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level metrics collector (wired during app lifespan)
# ---------------------------------------------------------------------------
_metrics: MetricsCollector | None = None


def set_metrics(collector: MetricsCollector) -> None:
    """Install the global metrics collector (called during app lifespan init)."""
    global _metrics  # noqa: PLW0603
    _metrics = collector


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class WebhookDeliveryStatus(StrEnum):
    """Lifecycle status for a webhook delivery."""

    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD_LETTERED = "dead_lettered"


class DeliveryAttempt(BaseModel):
    """Record of a single delivery attempt."""

    attempt_number: int
    timestamp: float = Field(default_factory=time.time)
    status_code: int = 0
    response_body: str = ""
    duration_ms: float = 0.0
    error_message: str = ""


class WebhookDeliveryRecord(BaseModel):
    """Full delivery record including all attempts."""

    delivery_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    webhook_id: str = ""
    url: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    status: WebhookDeliveryStatus = WebhookDeliveryStatus.PENDING
    attempts: list[DeliveryAttempt] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    next_retry_at: float | None = None
    max_retries: int = 5
    current_retry: int = 0


class DeliveryStats(BaseModel):
    """Aggregate delivery health statistics."""

    total: int = 0
    delivered: int = 0
    failed: int = 0
    retrying: int = 0
    dead_lettered: int = 0
    avg_latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class WebhookDeliveryManager:
    """Thread-safe, bounded in-memory webhook delivery manager.

    Supports exponential backoff with jitter, delivery receipts,
    dead-letter queue, and admin purge.
    """

    def __init__(
        self,
        max_retries: int = 5,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 300.0,
        max_records: int = 10_000,
    ) -> None:
        self._max_retries = max_retries
        self._base_delay_seconds = base_delay_seconds
        self._max_delay_seconds = max_delay_seconds
        self._max_records = max_records
        self._records: OrderedDict[str, WebhookDeliveryRecord] = OrderedDict()
        self._lock = threading.Lock()

    # -- backoff calculation --------------------------------------------------

    def compute_backoff(self, attempt: int) -> float:
        """Exponential backoff with jitter: min(base * 2^attempt, max_delay) * jitter."""
        delay = min(
            self._base_delay_seconds * (2**attempt),
            self._max_delay_seconds,
        )
        # Add jitter: random between 50% and 100% of delay
        jitter = random.uniform(0.5, 1.0)  # noqa: S311
        result: float = delay * jitter
        return result

    # -- storage management ---------------------------------------------------

    def _evict_if_needed(self) -> None:
        """Evict oldest delivered records when at capacity (caller holds lock)."""
        while len(self._records) >= self._max_records:
            # First try to evict delivered records (oldest first)
            evicted = False
            for key in list(self._records.keys()):
                if self._records[key].status == WebhookDeliveryStatus.DELIVERED:
                    del self._records[key]
                    evicted = True
                    break
            if not evicted:
                # Fall back to evicting the oldest record regardless of status
                self._records.popitem(last=False)

    # -- enqueue --------------------------------------------------------------

    def enqueue(
        self,
        webhook_id: str,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> str:
        """Queue a webhook delivery and return its delivery_id."""
        record = WebhookDeliveryRecord(
            webhook_id=webhook_id,
            url=url,
            payload=payload,
            headers=headers or {},
            max_retries=self._max_retries,
        )
        with self._lock:
            self._evict_if_needed()
            self._records[record.delivery_id] = record
        logger.info(
            "Webhook delivery enqueued: delivery_id=%s webhook_id=%s url=%s",
            record.delivery_id,
            webhook_id,
            url,
        )
        return record.delivery_id

    # -- attempt delivery -----------------------------------------------------

    def attempt_delivery(self, delivery_id: str) -> DeliveryAttempt:
        """Execute one delivery attempt (simulated -- real HTTP in production).

        This method performs a simulated delivery for the in-memory-only
        implementation.  Production integrations override or wrap this method
        with real ``httpx`` calls.
        """
        with self._lock:
            record = self._records.get(delivery_id)
            if record is None:
                raise KeyError(f"Delivery record not found: {delivery_id}")
            record.status = WebhookDeliveryStatus.IN_FLIGHT
            attempt_number = record.current_retry + 1

        # Simulate delivery -- actual HTTP call would go here
        start = time.monotonic()
        attempt = DeliveryAttempt(attempt_number=attempt_number)
        try:
            # Simulated success for in-memory manager
            elapsed = (time.monotonic() - start) * 1000.0
            attempt.status_code = 200
            attempt.response_body = '{"ok": true}'
            attempt.duration_ms = elapsed
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000.0
            attempt.status_code = 0
            attempt.error_message = str(exc)
            attempt.duration_ms = elapsed

        return attempt

    # -- process result -------------------------------------------------------

    def process_result(self, delivery_id: str, attempt: DeliveryAttempt) -> None:
        """Update delivery record based on an attempt result."""
        with self._lock:
            record = self._records.get(delivery_id)
            if record is None:
                raise KeyError(f"Delivery record not found: {delivery_id}")

            record.attempts.append(attempt)
            record.current_retry = attempt.attempt_number

            success = 200 <= attempt.status_code < 300
            webhook_id = record.webhook_id

            if success:
                record.status = WebhookDeliveryStatus.DELIVERED
                record.next_retry_at = None
                logger.info(
                    "Webhook delivered: delivery_id=%s attempt=%d status=%d",
                    delivery_id,
                    attempt.attempt_number,
                    attempt.status_code,
                )
            elif record.current_retry >= record.max_retries:
                record.status = WebhookDeliveryStatus.DEAD_LETTERED
                record.next_retry_at = None
                logger.warning(
                    "Webhook dead-lettered after %d attempts: delivery_id=%s",
                    record.current_retry,
                    delivery_id,
                )
            else:
                record.status = WebhookDeliveryStatus.RETRYING
                backoff = self.compute_backoff(record.current_retry)
                record.next_retry_at = time.time() + backoff
                logger.info(
                    "Webhook retry scheduled: delivery_id=%s attempt=%d next_retry_in=%.1fs",
                    delivery_id,
                    attempt.attempt_number,
                    backoff,
                )

        # -- Emit metrics (outside the lock) ---------------------------------
        self._emit_delivery_metrics(
            webhook_id=webhook_id,
            success=success,
            duration_seconds=attempt.duration_ms / 1000.0,
        )

    def _emit_delivery_metrics(
        self,
        *,
        webhook_id: str,
        success: bool,
        duration_seconds: float,
    ) -> None:
        """Emit webhook delivery metrics to the metrics collector."""
        collector = _metrics
        if collector is None:
            return
        status = "success" if success else "failure"
        collector.increment(
            "webhook_delivery_total",
            {"webhook_id": webhook_id, "status": status},
        )
        collector.observe(
            "webhook_delivery_duration_seconds",
            duration_seconds,
            {"webhook_id": webhook_id},
        )
        if not success:
            collector.increment(
                "webhook_delivery_failures_total",
                {"webhook_id": webhook_id},
            )

    # -- queries --------------------------------------------------------------

    def get_delivery(self, delivery_id: str) -> WebhookDeliveryRecord | None:
        """Retrieve a delivery record by ID."""
        with self._lock:
            record = self._records.get(delivery_id)
            return record.model_copy() if record else None

    def list_deliveries(
        self,
        status: WebhookDeliveryStatus | None = None,
        webhook_id: str | None = None,
        limit: int = 50,
    ) -> list[WebhookDeliveryRecord]:
        """List delivery records with optional filters."""
        with self._lock:
            results: list[WebhookDeliveryRecord] = []
            for record in reversed(self._records.values()):
                if status is not None and record.status != status:
                    continue
                if webhook_id is not None and record.webhook_id != webhook_id:
                    continue
                results.append(record.model_copy())
                if len(results) >= limit:
                    break
            return results

    def get_stats(self) -> DeliveryStats:
        """Compute aggregate delivery statistics."""
        with self._lock:
            total = len(self._records)
            delivered = 0
            failed = 0
            retrying = 0
            dead_lettered = 0
            latencies: list[float] = []

            for record in self._records.values():
                if record.status == WebhookDeliveryStatus.DELIVERED:
                    delivered += 1
                elif record.status == WebhookDeliveryStatus.FAILED:
                    failed += 1
                elif record.status == WebhookDeliveryStatus.RETRYING:
                    retrying += 1
                elif record.status == WebhookDeliveryStatus.DEAD_LETTERED:
                    dead_lettered += 1

                # Collect latencies from successful attempts
                for attempt in record.attempts:
                    if 200 <= attempt.status_code < 300:
                        latencies.append(attempt.duration_ms)

            avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

            return DeliveryStats(
                total=total,
                delivered=delivered,
                failed=failed,
                retrying=retrying,
                dead_lettered=dead_lettered,
                avg_latency_ms=avg_latency,
            )

    def get_dead_letters(self, limit: int = 50) -> list[WebhookDeliveryRecord]:
        """List dead-lettered deliveries."""
        return self.list_deliveries(
            status=WebhookDeliveryStatus.DEAD_LETTERED,
            limit=limit,
        )

    # -- admin actions --------------------------------------------------------

    def retry_dead_letter(self, delivery_id: str) -> None:
        """Re-enqueue a dead-lettered delivery for another round of attempts."""
        with self._lock:
            record = self._records.get(delivery_id)
            if record is None:
                raise KeyError(f"Delivery record not found: {delivery_id}")
            if record.status != WebhookDeliveryStatus.DEAD_LETTERED:
                raise ValueError(
                    f"Cannot retry delivery in status {record.status}; "
                    "only dead_lettered deliveries can be retried"
                )
            record.status = WebhookDeliveryStatus.PENDING
            record.current_retry = 0
            record.attempts = []
            record.next_retry_at = None
            logger.info("Dead-lettered delivery re-enqueued: delivery_id=%s", delivery_id)

    def purge_delivered(self, older_than_hours: float = 24.0) -> int:
        """Remove successfully delivered records older than the given threshold.

        Returns the number of records purged.
        """
        cutoff = time.time() - (older_than_hours * 3600.0)
        with self._lock:
            to_remove = [
                did
                for did, record in self._records.items()
                if record.status == WebhookDeliveryStatus.DELIVERED and record.created_at < cutoff
            ]
            for did in to_remove:
                del self._records[did]

        if to_remove:
            logger.info(
                "Purged %d delivered webhook records older than %.1fh",
                len(to_remove),
                older_than_hours,
            )
        return len(to_remove)
