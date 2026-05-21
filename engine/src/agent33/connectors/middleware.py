"""Middleware contracts and built-in connector boundary middleware."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol

import structlog

from agent33.connectors.circuit_breaker import CircuitOpenError
from agent33.connectors.models import ConnectorRequest

if TYPE_CHECKING:
    from agent33.connectors.circuit_breaker import CircuitBreaker
    from agent33.connectors.governance import ConnectorGovernancePolicy
    from agent33.connectors.monitoring import ConnectorMetricsCollector

logger = structlog.get_logger()

ConnectorHandler = Callable[[ConnectorRequest], Awaitable[Any]]


class ConnectorMiddleware(Protocol):
    """Callable connector middleware contract."""

    async def __call__(
        self,
        request: ConnectorRequest,
        call_next: ConnectorHandler,
    ) -> Any: ...


class GovernanceMiddleware:
    """Enforce a governance policy before executing a connector call."""

    def __init__(self, policy: ConnectorGovernancePolicy) -> None:
        self._policy = policy

    async def __call__(
        self,
        request: ConnectorRequest,
        call_next: ConnectorHandler,
    ) -> Any:
        decision = self._policy.evaluate(request)
        if not decision.allowed:
            reason = decision.reason or "connector call blocked by governance policy"
            logger.warning(
                "connector_governance_denied",
                connector=request.connector,
                operation=request.operation,
                reason=reason,
            )
            raise PermissionError(reason)
        return await call_next(request)


class CircuitBreakerMiddleware:
    """Protect connector calls with a circuit breaker."""

    def __init__(self, breaker: CircuitBreaker) -> None:
        self._breaker = breaker

    async def __call__(
        self,
        request: ConnectorRequest,
        call_next: ConnectorHandler,
    ) -> Any:
        try:
            self._breaker.before_call()
        except CircuitOpenError:
            logger.warning(
                "connector_circuit_open_rejected",
                connector=request.connector,
                operation=request.operation,
                state=self._breaker.state.value,
            )
            raise
        try:
            result = await call_next(request)
        except Exception:
            self._breaker.record_failure()
            raise
        self._breaker.record_success()
        return result


class TimeoutMiddleware:
    """Enforce per-call connector timeout using request metadata fallback."""

    def __init__(self, timeout_seconds: float) -> None:
        self._timeout_seconds = timeout_seconds

    async def __call__(
        self,
        request: ConnectorRequest,
        call_next: ConnectorHandler,
    ) -> Any:
        timeout = request.metadata.get("timeout_seconds", self._timeout_seconds)
        if timeout is None:
            return await call_next(request)
        timeout_value = float(timeout)
        if timeout_value <= 0:
            return await call_next(request)
        try:
            return await asyncio.wait_for(call_next(request), timeout=timeout_value)
        except TimeoutError as exc:
            logger.warning(
                "connector_timeout",
                connector=request.connector,
                operation=request.operation,
                timeout_seconds=timeout_value,
            )
            raise TimeoutError(
                f"connector call timed out after {timeout_value:.2f}s: "
                f"{request.connector}/{request.operation}"
            ) from exc


class RetryMiddleware:
    """Retry transient connector failures."""

    def __init__(self, max_attempts: int = 2) -> None:
        self._max_attempts = max(1, max_attempts)

    async def __call__(
        self,
        request: ConnectorRequest,
        call_next: ConnectorHandler,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await call_next(request)
            except (PermissionError, CircuitOpenError):
                raise
            except Exception as exc:
                last_error = exc
                logger.info(
                    "connector_retry_attempt",
                    connector=request.connector,
                    operation=request.operation,
                    attempt=attempt,
                    max_attempts=self._max_attempts,
                    error=str(exc),
                )
        assert last_error is not None
        raise last_error


class MetricsMiddleware:
    """Record call count/success/failure/latency in request metadata.

    When a ``ConnectorMetricsCollector`` is provided, call metrics are also
    pushed to the collector for aggregation and monitoring.
    """

    def __init__(
        self,
        collector: ConnectorMetricsCollector | None = None,
    ) -> None:
        self._collector = collector

    async def __call__(
        self,
        request: ConnectorRequest,
        call_next: ConnectorHandler,
    ) -> Any:
        started = time.monotonic()
        metrics = request.metadata.setdefault("boundary_metrics", {})
        metrics["calls"] = int(metrics.get("calls", 0)) + 1
        try:
            result = await call_next(request)
        except Exception:
            latency_ms = round((time.monotonic() - started) * 1000, 2)
            metrics["failure"] = int(metrics.get("failure", 0)) + 1
            metrics["latency_ms"] = latency_ms
            if self._collector is not None:
                self._collector.record_call(
                    request.connector, success=False, latency_ms=latency_ms
                )
            raise
        latency_ms = round((time.monotonic() - started) * 1000, 2)
        metrics["success"] = int(metrics.get("success", 0)) + 1
        metrics["latency_ms"] = latency_ms
        if self._collector is not None:
            self._collector.record_call(request.connector, success=True, latency_ms=latency_ms)
        return result
