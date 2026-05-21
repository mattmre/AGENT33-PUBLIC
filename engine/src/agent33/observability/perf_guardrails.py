"""Performance regression guardrails (P1.7).

Provides configurable per-operation latency budgets with violation tracking.
Each :class:`PerfGuardrail` wraps a :class:`PerfBudget` that defines a hard
p99 threshold and a softer warning threshold.  The :meth:`measure` helper
runs an awaitable, records wall-clock duration, and counts violations.

The module ships a :data:`default_registry` pre-populated with the budgets
identified in the P1.6 bottleneck report.

This module is intentionally **standalone** -- it does not depend on Prometheus,
FastAPI, or any external service.  Integration with those layers (P1.4
histograms, route middleware) is a separate concern.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class PerfBudget:
    """Latency budget for a single named operation.

    Attributes
    ----------
    operation:
        Short identifier, e.g. ``"health_check"``.
    p99_threshold_ms:
        Maximum acceptable p99 latency in milliseconds.
    warn_threshold_ms:
        Warning threshold (must be lower than ``p99_threshold_ms``).
    """

    operation: str
    p99_threshold_ms: float
    warn_threshold_ms: float


@dataclass
class PerfGuardrail:
    """Tracks timing observations against a single :class:`PerfBudget`."""

    budget: PerfBudget
    _violations: int = field(default=0, init=False, repr=False)
    _warnings: int = field(default=0, init=False, repr=False)
    _total_calls: int = field(default=0, init=False, repr=False)

    # -- public API ----------------------------------------------------------

    async def measure(self, coro: Awaitable[T]) -> T:
        """Await *coro*, record wall-clock duration, and return its result.

        Emits a ``WARNING`` log if the warn threshold is exceeded.
        Increments the violation counter if the p99 threshold is exceeded.
        Re-raises any exception from *coro* after recording the duration.
        """
        start = perf_counter()
        try:
            result: T = await coro
            return result
        except BaseException:
            raise
        finally:
            elapsed_ms = (perf_counter() - start) * 1000.0
            self._total_calls += 1

            if elapsed_ms > self.budget.p99_threshold_ms:
                self._violations += 1
                logger.warning(
                    "perf_violation operation=%s duration_ms=%.1f p99_threshold_ms=%.1f",
                    self.budget.operation,
                    elapsed_ms,
                    self.budget.p99_threshold_ms,
                )
            elif elapsed_ms > self.budget.warn_threshold_ms:
                self._warnings += 1
                logger.warning(
                    "perf_warning operation=%s duration_ms=%.1f warn_threshold_ms=%.1f",
                    self.budget.operation,
                    elapsed_ms,
                    self.budget.warn_threshold_ms,
                )

    def check_violation(self, duration_ms: float) -> bool:
        """Return ``True`` if *duration_ms* exceeds the p99 threshold."""
        return duration_ms > self.budget.p99_threshold_ms

    def report(self) -> dict[str, object]:
        """Return a summary dict for this guardrail."""
        return {
            "operation": self.budget.operation,
            "p99_threshold_ms": self.budget.p99_threshold_ms,
            "warn_threshold_ms": self.budget.warn_threshold_ms,
            "violations": self._violations,
            "warnings": self._warnings,
            "total_calls": self._total_calls,
        }

    def reset(self) -> None:
        """Reset all counters to zero."""
        self._violations = 0
        self._warnings = 0
        self._total_calls = 0


class PerfGuardrailRegistry:
    """Collection of named :class:`PerfGuardrail` instances."""

    def __init__(self) -> None:
        self._guardrails: dict[str, PerfGuardrail] = {}

    def register(self, budget: PerfBudget) -> PerfGuardrail:
        """Create and register a guardrail for *budget*.  Returns it."""
        guardrail = PerfGuardrail(budget=budget)
        self._guardrails[budget.operation] = guardrail
        return guardrail

    def get(self, operation: str) -> PerfGuardrail | None:
        """Look up a guardrail by operation name.  Returns ``None`` if absent."""
        return self._guardrails.get(operation)

    def check_all(self) -> list[dict[str, object]]:
        """Return :meth:`PerfGuardrail.report` for every guardrail that has
        at least one violation."""
        return [
            g.report()
            for g in self._guardrails.values()
            if g._violations > 0  # noqa: SLF001
        ]

    def reset(self) -> None:
        """Reset violation counters on every registered guardrail."""
        for g in self._guardrails.values():
            g.reset()

    @property
    def operations(self) -> list[str]:
        """List of registered operation names (insertion order)."""
        return list(self._guardrails.keys())


# ---------------------------------------------------------------------------
# Module-level default registry with P1.6 bottleneck-report thresholds.
# ---------------------------------------------------------------------------

DEFAULT_BUDGETS: list[PerfBudget] = [
    PerfBudget("health_check", p99_threshold_ms=50.0, warn_threshold_ms=30.0),
    PerfBudget("db_query", p99_threshold_ms=100.0, warn_threshold_ms=75.0),
    PerfBudget("agent_invoke", p99_threshold_ms=5000.0, warn_threshold_ms=3000.0),
    PerfBudget("metrics_scrape", p99_threshold_ms=200.0, warn_threshold_ms=150.0),
    PerfBudget("session_operation", p99_threshold_ms=500.0, warn_threshold_ms=400.0),
]

default_registry = PerfGuardrailRegistry()
for _budget in DEFAULT_BUDGETS:
    default_registry.register(_budget)
