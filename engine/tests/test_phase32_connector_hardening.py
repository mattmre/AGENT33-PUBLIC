"""Phase 32 hardening tests: composite chains, progressive backoff,
shared breakers, collector wiring, and structured logging."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent33.connectors.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitOpenError,
    CircuitState,
)
from agent33.connectors.executor import ConnectorExecutor
from agent33.connectors.governance import BlocklistConnectorPolicy
from agent33.connectors.middleware import (
    CircuitBreakerMiddleware,
    GovernanceMiddleware,
    MetricsMiddleware,
    RetryMiddleware,
    TimeoutMiddleware,
)
from agent33.connectors.models import ConnectorRequest
from agent33.connectors.monitoring import ConnectorMetricsCollector

# ======================================================================
# 1. Composite middleware chain
# ======================================================================


class TestCompositeMiddlewareChain:
    """Governance + timeout + retry + circuit breaker + metrics all interact."""

    @pytest.mark.asyncio
    async def test_full_chain_success(self) -> None:
        """All middleware layers execute in order for a successful call."""
        collector = ConnectorMetricsCollector()
        breaker = CircuitBreaker(
            failure_threshold=3,
            half_open_success_threshold=2,
        )
        policy = BlocklistConnectorPolicy()  # allow all

        middlewares = [
            GovernanceMiddleware(policy),
            TimeoutMiddleware(timeout_seconds=5.0),
            RetryMiddleware(max_attempts=2),
            CircuitBreakerMiddleware(breaker),
            MetricsMiddleware(collector=collector),
        ]
        executor = ConnectorExecutor(middlewares)
        request = ConnectorRequest(connector="svc:composite", operation="read")

        async def _handler(_req: ConnectorRequest) -> dict[str, str]:
            return {"status": "ok"}

        result = await executor.execute(request, _handler)

        assert result == {"status": "ok"}
        # Verify metrics were recorded in both places
        assert request.metadata["boundary_metrics"]["success"] == 1
        m = collector.get_connector_metrics("svc:composite")
        assert m["total_calls"] == 1
        assert m["successes"] == 1

    @pytest.mark.asyncio
    async def test_full_chain_governance_blocks_before_handler(self) -> None:
        """Governance denial prevents downstream middleware and handler."""
        collector = ConnectorMetricsCollector()
        breaker = CircuitBreaker(failure_threshold=3)
        policy = BlocklistConnectorPolicy(blocked_connectors=frozenset({"svc:blocked"}))

        middlewares = [
            GovernanceMiddleware(policy),
            TimeoutMiddleware(timeout_seconds=5.0),
            RetryMiddleware(max_attempts=2),
            CircuitBreakerMiddleware(breaker),
            MetricsMiddleware(collector=collector),
        ]
        executor = ConnectorExecutor(middlewares)
        request = ConnectorRequest(connector="svc:blocked", operation="write")

        async def _handler(_req: ConnectorRequest) -> dict[str, str]:
            raise AssertionError("handler should not be reached")

        with pytest.raises(PermissionError, match="connector blocked by policy"):
            await executor.execute(request, _handler)

        # Circuit should not have tripped
        assert breaker.state == CircuitState.CLOSED
        assert breaker.total_trips == 0

    @pytest.mark.asyncio
    async def test_full_chain_circuit_open_prevents_retry(self) -> None:
        """When the circuit is open, retry middleware does not re-attempt."""
        breaker = CircuitBreaker(
            failure_threshold=1,
            half_open_success_threshold=1,
            recovery_timeout_seconds=60.0,
        )
        policy = BlocklistConnectorPolicy()  # allow all
        call_count = 0

        middlewares = [
            GovernanceMiddleware(policy),
            RetryMiddleware(max_attempts=3),
            CircuitBreakerMiddleware(breaker),
            MetricsMiddleware(),
        ]
        executor = ConnectorExecutor(middlewares)

        async def _failing_handler(_req: ConnectorRequest) -> Any:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("downstream failure")

        request = ConnectorRequest(connector="svc:trip", operation="call")

        # First call: handler fails on attempt 1 (trips breaker), then
        # retry attempt 2 hits CircuitOpenError which is non-retryable.
        # The final exception is CircuitOpenError, not the handler error.
        with pytest.raises(CircuitOpenError):
            await executor.execute(request, _failing_handler)
        assert breaker.state == CircuitState.OPEN
        assert call_count == 1

        # Second call: circuit open blocks immediately at the breaker,
        # retry re-raises without calling handler
        request2 = ConnectorRequest(connector="svc:trip", operation="call")
        with pytest.raises(CircuitOpenError):
            await executor.execute(request2, _failing_handler)
        # Handler was NOT called again
        assert call_count == 1


# ======================================================================
# 2. Rapid oscillation
# ======================================================================


class TestRapidOscillation:
    """Trip -> half_open -> immediate failure -> re-trip."""

    def test_rapid_oscillation_increments_total_trips(self) -> None:
        now = 100.0

        def _clock() -> float:
            return now

        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout_seconds=5.0,
            half_open_success_threshold=1,
            max_recovery_timeout_seconds=300.0,
            clock=_clock,
        )

        # Trip 1: CLOSED -> OPEN
        breaker.before_call()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        assert breaker.total_trips == 1

        # Wait for recovery -> HALF_OPEN
        now = 106.0
        breaker.before_call()
        assert breaker.state == CircuitState.HALF_OPEN

        # Immediate failure -> OPEN again (trip 2)
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        assert breaker.total_trips == 2

        # Wait for recovery (now with backoff: 5 * 2^1 = 10s)
        now = 117.0  # 106 + 11 > 10
        breaker.before_call()
        assert breaker.state == CircuitState.HALF_OPEN

        # Immediate failure -> OPEN again (trip 3)
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        assert breaker.total_trips == 3


# ======================================================================
# 3. Progressive backoff
# ======================================================================


class TestProgressiveBackoff:
    """After N trips, recovery timeout grows exponentially."""

    def test_effective_timeout_grows_with_trips(self) -> None:
        breaker = CircuitBreaker(
            recovery_timeout_seconds=10.0,
            max_recovery_timeout_seconds=300.0,
        )
        # No trips yet
        assert breaker.effective_recovery_timeout == 10.0

        # Simulate trips
        breaker.total_trips = 1  # 10 * 2^0 = 10
        assert breaker.effective_recovery_timeout == 10.0

        breaker.total_trips = 2  # 10 * 2^1 = 20
        assert breaker.effective_recovery_timeout == 20.0

        breaker.total_trips = 3  # 10 * 2^2 = 40
        assert breaker.effective_recovery_timeout == 40.0

        breaker.total_trips = 4  # 10 * 2^3 = 80
        assert breaker.effective_recovery_timeout == 80.0

    def test_after_3_trips_recovery_timeout_is_4x_base(self) -> None:
        """After 3 trips, recovery timeout should be 4x the base."""
        now = 100.0

        def _clock() -> float:
            return now

        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout_seconds=10.0,
            half_open_success_threshold=1,
            max_recovery_timeout_seconds=300.0,
            clock=_clock,
        )

        # Trip 1
        breaker.before_call()
        breaker.record_failure()
        assert breaker.total_trips == 1
        # effective_recovery_timeout after trip 1: 10 * 2^0 = 10
        assert breaker.effective_recovery_timeout == 10.0

        # Recover from trip 1
        now = 111.0
        breaker.before_call()
        breaker.record_failure()  # Re-trip (trip 2)
        assert breaker.total_trips == 2
        # effective_recovery_timeout after trip 2: 10 * 2^1 = 20
        assert breaker.effective_recovery_timeout == 20.0

        # Recover from trip 2
        now = 132.0  # 111 + 21 > 20
        breaker.before_call()
        breaker.record_failure()  # Re-trip (trip 3)
        assert breaker.total_trips == 3
        # effective_recovery_timeout after trip 3: 10 * 2^2 = 40 (4x base)
        assert breaker.effective_recovery_timeout == 40.0

    def test_backoff_capped_at_max(self) -> None:
        breaker = CircuitBreaker(
            recovery_timeout_seconds=10.0,
            max_recovery_timeout_seconds=50.0,
        )
        breaker.total_trips = 10  # 10 * 2^9 = 5120, capped at 50
        assert breaker.effective_recovery_timeout == 50.0

    def test_backoff_applies_to_before_call(self) -> None:
        """The increased timeout is actually enforced in before_call()."""
        now = 100.0

        def _clock() -> float:
            return now

        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout_seconds=10.0,
            half_open_success_threshold=1,
            max_recovery_timeout_seconds=300.0,
            clock=_clock,
        )

        # Trip 1
        breaker.before_call()
        breaker.record_failure()
        assert breaker.total_trips == 1

        # Recover and trip again
        now = 111.0
        breaker.before_call()
        breaker.record_failure()
        assert breaker.total_trips == 2
        # Now effective timeout is 20s

        # Try to recover after only 15s (less than 20) - should still be OPEN
        now = 126.0  # 111 + 15
        with pytest.raises(CircuitOpenError):
            breaker.before_call()

        # Now wait the full 20s
        now = 132.0  # 111 + 21
        breaker.before_call()
        assert breaker.state == CircuitState.HALF_OPEN


# ======================================================================
# 4. Retry exhaustion
# ======================================================================


class TestRetryExhaustion:
    """All retries fail, final exception propagates."""

    @pytest.mark.asyncio
    async def test_all_retries_fail_propagates_last_error(self) -> None:
        call_count = 0

        async def _handler(_req: ConnectorRequest) -> Any:
            nonlocal call_count
            call_count += 1
            raise ValueError(f"failure #{call_count}")

        executor = ConnectorExecutor([RetryMiddleware(max_attempts=3)])
        request = ConnectorRequest(connector="svc:exhaust", operation="op")

        with pytest.raises(ValueError, match="failure #3"):
            await executor.execute(request, _handler)
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_permission_error_not_retried(self) -> None:
        call_count = 0

        async def _handler(_req: ConnectorRequest) -> Any:
            nonlocal call_count
            call_count += 1
            raise PermissionError("denied")

        executor = ConnectorExecutor([RetryMiddleware(max_attempts=3)])
        request = ConnectorRequest(connector="svc:perm", operation="op")

        with pytest.raises(PermissionError, match="denied"):
            await executor.execute(request, _handler)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_circuit_open_error_not_retried(self) -> None:
        call_count = 0

        async def _handler(_req: ConnectorRequest) -> Any:
            nonlocal call_count
            call_count += 1
            raise CircuitOpenError("circuit open")

        executor = ConnectorExecutor([RetryMiddleware(max_attempts=3)])
        request = ConnectorRequest(connector="svc:co", operation="op")

        with pytest.raises(CircuitOpenError, match="circuit open"):
            await executor.execute(request, _handler)
        assert call_count == 1


# ======================================================================
# 5. Shared breaker (CircuitBreakerRegistry)
# ======================================================================


class TestSharedBreaker:
    """Two calls through the same name share circuit state."""

    def test_shared_breaker_registry_returns_same_instance(self) -> None:
        registry = CircuitBreakerRegistry()
        b1 = registry.get_or_create("svc-a", failure_threshold=2)
        b2 = registry.get_or_create("svc-a", failure_threshold=5)
        assert b1 is b2
        # Original config preserved (failure_threshold=2)
        assert b1.failure_threshold == 2

    def test_different_names_get_different_breakers(self) -> None:
        registry = CircuitBreakerRegistry()
        b1 = registry.get_or_create("svc-a", failure_threshold=2)
        b2 = registry.get_or_create("svc-b", failure_threshold=5)
        assert b1 is not b2
        assert b1.failure_threshold == 2
        assert b2.failure_threshold == 5

    def test_get_returns_none_for_unknown(self) -> None:
        registry = CircuitBreakerRegistry()
        assert registry.get("unknown") is None

    def test_get_returns_existing(self) -> None:
        registry = CircuitBreakerRegistry()
        created = registry.get_or_create("svc-x")
        found = registry.get("svc-x")
        assert found is created

    def test_all_returns_copy_of_breakers(self) -> None:
        registry = CircuitBreakerRegistry()
        registry.get_or_create("a")
        registry.get_or_create("b")
        all_breakers = registry.all()
        assert set(all_breakers.keys()) == {"a", "b"}
        # It should be a copy, not the internal dict
        all_breakers["c"] = CircuitBreaker()
        assert registry.get("c") is None

    @pytest.mark.asyncio
    async def test_shared_state_across_executors(self) -> None:
        """Two separate executors sharing a breaker see the same state."""
        registry = CircuitBreakerRegistry()
        breaker = registry.get_or_create(
            "shared-svc",
            failure_threshold=2,
            half_open_success_threshold=1,
        )

        executor_a = ConnectorExecutor([CircuitBreakerMiddleware(breaker)])
        executor_b = ConnectorExecutor([CircuitBreakerMiddleware(breaker)])

        call_count = 0

        async def _failing_handler(_req: ConnectorRequest) -> Any:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("fail")

        req_a = ConnectorRequest(connector="shared-svc", operation="call")
        req_b = ConnectorRequest(connector="shared-svc", operation="call")

        # First failure via executor_a
        with pytest.raises(RuntimeError, match="fail"):
            await executor_a.execute(req_a, _failing_handler)
        assert breaker.consecutive_failures == 1

        # Second failure via executor_b trips the breaker
        with pytest.raises(RuntimeError, match="fail"):
            await executor_b.execute(req_b, _failing_handler)
        assert breaker.state == CircuitState.OPEN
        assert call_count == 2


# ======================================================================
# 6. ConnectorMetricsCollector integration with on_state_change
# ======================================================================


class TestCollectorCircuitIntegration:
    """Wire on_state_change -> metrics_collector.record_circuit_event()."""

    def test_on_state_change_records_circuit_event(self) -> None:
        collector = ConnectorMetricsCollector()

        def _on_change(
            old: CircuitState,
            new: CircuitState,
        ) -> None:
            collector.record_circuit_event("svc-wired", str(old), str(new))

        breaker = CircuitBreaker(
            failure_threshold=1,
            half_open_success_threshold=1,
            on_state_change=_on_change,
        )

        breaker.before_call()
        breaker.record_failure()  # CLOSED -> OPEN

        events = collector.get_circuit_events("svc-wired")
        assert len(events) == 1
        assert events[0]["old_state"] == "closed"
        assert events[0]["new_state"] == "open"
        assert "svc-wired" in collector.list_known_connectors()


# ======================================================================
# 7. Structured logging
# ======================================================================


class TestStructuredLogging:
    """Verify structlog is called on key state transitions."""

    def test_circuit_breaker_logs_transition(self) -> None:
        with patch("agent33.connectors.circuit_breaker.logger") as mock_logger:
            breaker = CircuitBreaker(
                failure_threshold=1,
                half_open_success_threshold=1,
            )
            breaker.before_call()
            breaker.record_failure()

            # Should have logged the CLOSED->OPEN transition
            info_calls = [
                c
                for c in mock_logger.info.call_args_list
                if c[0][0] == "circuit_breaker_state_transition"
            ]
            assert len(info_calls) == 1
            kwargs = info_calls[0][1]
            assert kwargs["old_state"] == "closed"
            assert kwargs["new_state"] == "open"

    def test_circuit_breaker_logs_trip_warning(self) -> None:
        with patch("agent33.connectors.circuit_breaker.logger") as mock_logger:
            breaker = CircuitBreaker(
                failure_threshold=1,
                half_open_success_threshold=1,
            )
            breaker.before_call()
            breaker.record_failure()

            warning_calls = [
                c
                for c in mock_logger.warning.call_args_list
                if c[0][0] == "circuit_breaker_tripped"
            ]
            assert len(warning_calls) == 1
            kwargs = warning_calls[0][1]
            assert kwargs["total_trips"] == 1

    @pytest.mark.asyncio
    async def test_governance_denial_logs_warning(self) -> None:
        with patch("agent33.connectors.middleware.logger") as mock_logger:
            policy = BlocklistConnectorPolicy(blocked_connectors=frozenset({"svc:denied"}))
            mw = GovernanceMiddleware(policy)
            request = ConnectorRequest(connector="svc:denied", operation="op")

            async def _handler(_req: ConnectorRequest) -> Any:
                raise AssertionError("should not be called")

            with pytest.raises(PermissionError):
                await mw(request, _handler)

            warning_calls = [
                c
                for c in mock_logger.warning.call_args_list
                if c[0][0] == "connector_governance_denied"
            ]
            assert len(warning_calls) == 1
            assert warning_calls[0][1]["connector"] == "svc:denied"

    @pytest.mark.asyncio
    async def test_circuit_open_rejection_logs_warning(self) -> None:
        with patch("agent33.connectors.middleware.logger") as mock_logger:
            breaker = CircuitBreaker(
                failure_threshold=1,
                half_open_success_threshold=1,
            )
            # Trip the breaker first
            breaker.before_call()
            breaker.record_failure()
            assert breaker.state == CircuitState.OPEN

            mw = CircuitBreakerMiddleware(breaker)
            request = ConnectorRequest(connector="svc:open", operation="op")

            async def _handler(_req: ConnectorRequest) -> Any:
                return {}

            with pytest.raises(CircuitOpenError):
                await mw(request, _handler)

            warning_calls = [
                c
                for c in mock_logger.warning.call_args_list
                if c[0][0] == "connector_circuit_open_rejected"
            ]
            assert len(warning_calls) == 1
            assert warning_calls[0][1]["connector"] == "svc:open"


# ======================================================================
# 8. CircuitBreakerRegistry get_or_create
# ======================================================================


class TestCircuitBreakerRegistryGetOrCreate:
    """get_or_create returns same instance for same name."""

    def test_returns_same_instance(self) -> None:
        registry = CircuitBreakerRegistry()
        first = registry.get_or_create("my-svc", failure_threshold=5)
        second = registry.get_or_create("my-svc", failure_threshold=99)
        assert first is second
        assert first.failure_threshold == 5

    def test_logs_creation(self) -> None:
        with patch("agent33.connectors.circuit_breaker.logger") as mock_logger:
            registry = CircuitBreakerRegistry()
            registry.get_or_create("new-svc")

            info_calls = [
                c
                for c in mock_logger.info.call_args_list
                if c[0][0] == "circuit_breaker_registry_created"
            ]
            assert len(info_calls) == 1
            assert info_calls[0][1]["breaker_name"] == "new-svc"

    def test_second_get_or_create_does_not_log(self) -> None:
        with patch("agent33.connectors.circuit_breaker.logger") as mock_logger:
            registry = CircuitBreakerRegistry()
            registry.get_or_create("svc")
            mock_logger.info.reset_mock()
            registry.get_or_create("svc")

            create_calls = [
                c
                for c in mock_logger.info.call_args_list
                if c[0][0] == "circuit_breaker_registry_created"
            ]
            assert len(create_calls) == 0


# ======================================================================
# 9. Half-open requires 2 successes (new default)
# ======================================================================


class TestHalfOpenRequiresTwoSuccesses:
    """Default threshold is now 2: one success stays half_open, second closes."""

    def test_one_success_stays_half_open(self) -> None:
        now = 100.0

        def _clock() -> float:
            return now

        # Use default half_open_success_threshold (now 2)
        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout_seconds=5.0,
            clock=_clock,
        )

        # Trip the breaker
        breaker.before_call()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Wait for recovery
        now = 106.0
        breaker.before_call()
        assert breaker.state == CircuitState.HALF_OPEN

        # First success: still HALF_OPEN
        breaker.record_success()
        assert breaker.state == CircuitState.HALF_OPEN
        assert breaker.half_open_successes == 1

        # Second success: transitions to CLOSED
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.half_open_successes == 0

    def test_failure_after_one_success_re_trips(self) -> None:
        now = 100.0

        def _clock() -> float:
            return now

        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout_seconds=5.0,
            clock=_clock,
        )

        # Trip
        breaker.before_call()
        breaker.record_failure()

        # Recover
        now = 106.0
        breaker.before_call()
        assert breaker.state == CircuitState.HALF_OPEN

        # One success then failure
        breaker.record_success()
        assert breaker.state == CircuitState.HALF_OPEN

        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
        assert breaker.total_trips == 2


# ======================================================================
# 10. MetricsMiddleware feeds collector
# ======================================================================


class TestMetricsMiddlewareCollector:
    """MetricsMiddleware.record_call() invoked on collector."""

    @pytest.mark.asyncio
    async def test_success_recorded_in_collector(self) -> None:
        collector = ConnectorMetricsCollector()
        mw = MetricsMiddleware(collector=collector)
        request = ConnectorRequest(connector="svc:metrics-test", operation="read")

        async def _handler(_req: ConnectorRequest) -> dict[str, str]:
            return {"ok": "yes"}

        await mw(request, _handler)

        m = collector.get_connector_metrics("svc:metrics-test")
        assert m["total_calls"] == 1
        assert m["successes"] == 1
        assert m["failures"] == 0
        assert m["avg_latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_failure_recorded_in_collector(self) -> None:
        collector = ConnectorMetricsCollector()
        mw = MetricsMiddleware(collector=collector)
        request = ConnectorRequest(connector="svc:fail-test", operation="write")

        async def _handler(_req: ConnectorRequest) -> Any:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            await mw(request, _handler)

        m = collector.get_connector_metrics("svc:fail-test")
        assert m["total_calls"] == 1
        assert m["successes"] == 0
        assert m["failures"] == 1

    @pytest.mark.asyncio
    async def test_without_collector_still_records_metadata(self) -> None:
        """MetricsMiddleware with no collector still writes to metadata."""
        mw = MetricsMiddleware()  # no collector
        request = ConnectorRequest(connector="svc:no-coll", operation="op")

        async def _handler(_req: ConnectorRequest) -> str:
            return "done"

        await mw(request, _handler)

        metrics = request.metadata["boundary_metrics"]
        assert metrics["calls"] == 1
        assert metrics["success"] == 1

    @pytest.mark.asyncio
    async def test_collector_record_call_invocation_count(self) -> None:
        """Verify record_call is invoked exactly once per call."""
        mock_collector = MagicMock(spec=ConnectorMetricsCollector)
        mw = MetricsMiddleware(collector=mock_collector)
        request = ConnectorRequest(connector="svc:mock", operation="ping")

        async def _handler(_req: ConnectorRequest) -> str:
            return "pong"

        await mw(request, _handler)

        mock_collector.record_call.assert_called_once()
        call_kwargs = mock_collector.record_call.call_args
        assert call_kwargs[0][0] == "svc:mock"
        assert call_kwargs[1]["success"] is True
        assert call_kwargs[1]["latency_ms"] >= 0
