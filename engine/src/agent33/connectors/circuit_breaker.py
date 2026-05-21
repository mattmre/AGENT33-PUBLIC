"""Circuit-breaker primitives for external connector boundaries."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger()


class CircuitState(StrEnum):
    """Current state of a circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised when a call is blocked by an open circuit breaker."""


@dataclass(slots=True)
class CircuitBreaker:
    """Consecutive-failure circuit breaker with progressive backoff.

    When the breaker trips, the recovery timeout grows exponentially with
    each successive trip:
    ``actual_timeout = min(recovery_timeout * 2^(total_trips-1), max_recovery_timeout)``
    """

    failure_threshold: int = 3
    recovery_timeout_seconds: float = 30.0
    half_open_success_threshold: int = 2
    max_recovery_timeout_seconds: float = 300.0
    clock: Callable[[], float] = time.monotonic
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: float | None = None
    half_open_successes: int = 0
    total_trips: int = 0
    last_trip_at: float | None = None
    on_state_change: Callable[[CircuitState, CircuitState], None] | None = field(
        default=None, repr=False
    )

    @property
    def effective_recovery_timeout(self) -> float:
        """Compute the progressive backoff recovery timeout.

        Returns ``min(base * 2^(trips-1), max)`` for trips >= 1, or the
        base timeout when no trips have occurred yet.
        """
        if self.total_trips <= 0:
            return self.recovery_timeout_seconds
        exponent = self.total_trips - 1
        backoff: float = self.recovery_timeout_seconds * (2**exponent)
        return float(min(backoff, self.max_recovery_timeout_seconds))

    def _transition(self, new_state: CircuitState) -> None:
        """Apply a state transition and fire the callback if set."""
        old_state = self.state
        if old_state == new_state:
            return
        self.state = new_state
        logger.info(
            "circuit_breaker_state_transition",
            old_state=old_state.value,
            new_state=new_state.value,
            total_trips=self.total_trips,
        )
        if self.on_state_change is not None:
            self.on_state_change(old_state, new_state)

    def before_call(self) -> None:
        """Check whether the next call is allowed."""
        if self.state != CircuitState.OPEN:
            return
        if self.opened_at is None:
            raise CircuitOpenError("Circuit is open")
        elapsed = self.clock() - self.opened_at
        timeout = self.effective_recovery_timeout
        if elapsed < timeout:
            raise CircuitOpenError("Circuit is open")
        self._transition(CircuitState.HALF_OPEN)
        self.half_open_successes = 0

    def record_success(self) -> None:
        """Record a successful downstream call."""
        if self.state == CircuitState.HALF_OPEN:
            self.half_open_successes += 1
            if self.half_open_successes >= self.half_open_success_threshold:
                self._transition(CircuitState.CLOSED)
                self.consecutive_failures = 0
                self.opened_at = None
                self.half_open_successes = 0
            return

        self._transition(CircuitState.CLOSED)
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        """Record a failed downstream call."""
        if self.state == CircuitState.HALF_OPEN:
            self._open()
            return

        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            self._open()

    def _open(self) -> None:
        self._transition(CircuitState.OPEN)
        self.opened_at = self.clock()
        self.total_trips += 1
        self.last_trip_at = self.opened_at
        self.consecutive_failures = 0
        self.half_open_successes = 0
        logger.warning(
            "circuit_breaker_tripped",
            total_trips=self.total_trips,
            effective_recovery_timeout=self.effective_recovery_timeout,
        )

    def snapshot(self) -> dict[str, Any]:
        """Return a serializable dict of the breaker's current state."""
        effective_timeout = self.effective_recovery_timeout
        cooldown_remaining = 0.0
        if self.state == CircuitState.OPEN and self.opened_at is not None:
            elapsed = self.clock() - self.opened_at
            cooldown_remaining = max(0.0, effective_timeout - elapsed)
        return {
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "total_trips": self.total_trips,
            "last_trip_at": self.last_trip_at,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_seconds": self.recovery_timeout_seconds,
            "half_open_success_threshold": self.half_open_success_threshold,
            "max_recovery_timeout_seconds": self.max_recovery_timeout_seconds,
            "effective_recovery_timeout_seconds": effective_timeout,
            "cooldown_remaining_seconds": cooldown_remaining,
        }


class CircuitBreakerRegistry:
    """Shared registry for per-connector circuit breaker instances.

    Ensures that callers using the same connector identity share one
    breaker rather than creating independent instances.
    """

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_or_create(self, name: str, **kwargs: Any) -> CircuitBreaker:
        """Return the breaker for *name*, creating one if absent."""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(**kwargs)
            logger.info("circuit_breaker_registry_created", breaker_name=name)
        return self._breakers[name]

    def get(self, name: str) -> CircuitBreaker | None:
        """Return the breaker for *name* or ``None``."""
        return self._breakers.get(name)

    def all(self) -> dict[str, CircuitBreaker]:
        """Return a shallow copy of all registered breakers."""
        return dict(self._breakers)
