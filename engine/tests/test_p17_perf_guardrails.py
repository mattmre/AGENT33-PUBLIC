"""P1.7 Performance regression guardrails — unit tests.

Tests cover:
- PerfBudget field storage
- PerfGuardrail.check_violation threshold logic
- PerfGuardrail.measure() timing, violation recording, warning logging, and
  exception re-raising
- PerfGuardrail.report() structure and accuracy
- PerfGuardrailRegistry CRUD, check_all filtering, and reset
- default_registry contents and threshold values
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

from agent33.observability.perf_guardrails import (
    DEFAULT_BUDGETS,
    PerfBudget,
    PerfGuardrail,
    PerfGuardrailRegistry,
    default_registry,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def budget() -> PerfBudget:
    """A simple budget for testing."""
    return PerfBudget("test_op", p99_threshold_ms=100.0, warn_threshold_ms=60.0)


@pytest.fixture()
def guardrail(budget: PerfBudget) -> PerfGuardrail:
    """A fresh guardrail wrapping the test budget."""
    return PerfGuardrail(budget=budget)


@pytest.fixture()
def registry() -> PerfGuardrailRegistry:
    """A fresh empty registry for each test."""
    return PerfGuardrailRegistry()


# ---------------------------------------------------------------------------
# 1. PerfBudget stores fields correctly
# ---------------------------------------------------------------------------


class TestPerfBudgetStorage:
    """PerfBudget is a simple dataclass -- verify field assignment."""

    def test_operation_stored(self) -> None:
        b = PerfBudget("health_check", p99_threshold_ms=50.0, warn_threshold_ms=30.0)
        assert b.operation == "health_check"

    def test_p99_threshold_stored(self) -> None:
        b = PerfBudget("health_check", p99_threshold_ms=50.0, warn_threshold_ms=30.0)
        assert b.p99_threshold_ms == 50.0

    def test_warn_threshold_stored(self) -> None:
        b = PerfBudget("health_check", p99_threshold_ms=50.0, warn_threshold_ms=30.0)
        assert b.warn_threshold_ms == 30.0


# ---------------------------------------------------------------------------
# 2. PerfGuardrail.check_violation() threshold logic
# ---------------------------------------------------------------------------


class TestCheckViolation:
    """check_violation returns bool based on p99 threshold comparison."""

    def test_under_threshold_returns_false(self, guardrail: PerfGuardrail) -> None:
        assert guardrail.check_violation(50.0) is False

    def test_at_threshold_returns_false(self, guardrail: PerfGuardrail) -> None:
        """Exactly at threshold is NOT a violation (> not >=)."""
        assert guardrail.check_violation(100.0) is False

    def test_over_threshold_returns_true(self, guardrail: PerfGuardrail) -> None:
        assert guardrail.check_violation(100.1) is True

    def test_way_over_threshold_returns_true(self, guardrail: PerfGuardrail) -> None:
        assert guardrail.check_violation(999.0) is True

    def test_zero_duration_returns_false(self, guardrail: PerfGuardrail) -> None:
        assert guardrail.check_violation(0.0) is False


# ---------------------------------------------------------------------------
# 3. PerfGuardrail.measure() runs coroutine and returns result
# ---------------------------------------------------------------------------


class TestMeasureRunsCoroutine:
    """measure() must await the coroutine and return its value."""

    async def test_returns_coroutine_result(self, guardrail: PerfGuardrail) -> None:
        async def work() -> str:
            return "done"

        result = await guardrail.measure(work())
        assert result == "done"

    async def test_returns_int_result(self, guardrail: PerfGuardrail) -> None:
        async def compute() -> int:
            return 42

        result = await guardrail.measure(compute())
        assert result == 42

    async def test_calls_async_mock(self, guardrail: PerfGuardrail) -> None:
        mock_coro = AsyncMock(return_value="mocked")
        result = await guardrail.measure(mock_coro())
        assert result == "mocked"


# ---------------------------------------------------------------------------
# 4. measure() records violation when p99 exceeded (mock timing)
# ---------------------------------------------------------------------------


class TestMeasureRecordsViolation:
    """Verify violation counter increments only when duration > p99."""

    async def test_violation_recorded_when_over_p99(self) -> None:
        """Use a tight threshold (1ms) with a sleep to guarantee exceeding it."""
        tight_budget = PerfBudget("tight_op", p99_threshold_ms=1.0, warn_threshold_ms=0.5)
        g = PerfGuardrail(budget=tight_budget)

        async def slow_work() -> str:
            await asyncio.sleep(0.02)  # 20ms >> 1ms threshold
            return "slow"

        result = await g.measure(slow_work())
        assert result == "slow"
        assert g._violations == 1
        assert g._total_calls == 1

    async def test_no_violation_when_under_p99(self, guardrail: PerfGuardrail) -> None:
        """100ms threshold; near-instant coroutine should not violate."""

        async def fast_work() -> str:
            return "fast"

        await guardrail.measure(fast_work())
        assert guardrail._violations == 0
        assert guardrail._total_calls == 1


# ---------------------------------------------------------------------------
# 5. measure() logs warning when warn threshold exceeded
# ---------------------------------------------------------------------------


class TestMeasureLogsWarning:
    """Verify warning logs at both thresholds."""

    async def test_warn_log_on_warn_threshold_exceeded(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Duration between warn and p99 should emit perf_warning."""
        # warn=1ms, p99=50ms; a 5ms sleep sits between them
        budget = PerfBudget("warn_test", p99_threshold_ms=50.0, warn_threshold_ms=1.0)
        g = PerfGuardrail(budget=budget)

        with caplog.at_level(logging.WARNING, logger="agent33.observability.perf_guardrails"):

            async def medium_work() -> None:
                await asyncio.sleep(0.005)

            await g.measure(medium_work())

        warnings = [r for r in caplog.records if "perf_warning" in r.message]
        assert len(warnings) == 1
        assert "warn_test" in warnings[0].message
        assert "warn_threshold_ms" in warnings[0].message

    async def test_violation_log_on_p99_exceeded(self, caplog: pytest.LogCaptureFixture) -> None:
        """Duration above p99 should emit perf_violation, not perf_warning."""
        budget = PerfBudget("viol_test", p99_threshold_ms=1.0, warn_threshold_ms=0.5)
        g = PerfGuardrail(budget=budget)

        with caplog.at_level(logging.WARNING, logger="agent33.observability.perf_guardrails"):

            async def slow_work() -> None:
                await asyncio.sleep(0.02)

            await g.measure(slow_work())

        violations = [r for r in caplog.records if "perf_violation" in r.message]
        assert len(violations) == 1
        assert "viol_test" in violations[0].message
        assert "p99_threshold_ms" in violations[0].message

    async def test_no_log_when_under_warn_threshold(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Fast coroutine should produce no warning logs."""
        budget = PerfBudget("fast_test", p99_threshold_ms=5000.0, warn_threshold_ms=3000.0)
        g = PerfGuardrail(budget=budget)

        with caplog.at_level(logging.WARNING, logger="agent33.observability.perf_guardrails"):

            async def instant() -> None:
                pass

            await g.measure(instant())

        perf_logs = [
            r
            for r in caplog.records
            if "perf_violation" in r.message or "perf_warning" in r.message
        ]
        assert len(perf_logs) == 0


# ---------------------------------------------------------------------------
# 6. measure() does NOT record a violation when under threshold
# ---------------------------------------------------------------------------


class TestMeasureNoViolationWhenFast:
    """Explicit test that fast operations leave violation count at zero."""

    async def test_zero_violations_after_fast_call(self, guardrail: PerfGuardrail) -> None:
        async def noop() -> None:
            pass

        await guardrail.measure(noop())
        assert guardrail._violations == 0

    async def test_zero_violations_after_multiple_fast_calls(
        self, guardrail: PerfGuardrail
    ) -> None:
        async def noop() -> None:
            pass

        for _ in range(5):
            await guardrail.measure(noop())
        assert guardrail._violations == 0
        assert guardrail._total_calls == 5


# ---------------------------------------------------------------------------
# 7. PerfGuardrail.report() returns correct structure
# ---------------------------------------------------------------------------


class TestGuardrailReport:
    """Verify report dict shape and accuracy."""

    def test_report_structure_fresh_guardrail(self, guardrail: PerfGuardrail) -> None:
        r = guardrail.report()
        assert r["operation"] == "test_op"
        assert r["p99_threshold_ms"] == 100.0
        assert r["warn_threshold_ms"] == 60.0
        assert r["violations"] == 0
        assert r["warnings"] == 0
        assert r["total_calls"] == 0

    async def test_report_reflects_violation_count(self) -> None:
        budget = PerfBudget("rpt_op", p99_threshold_ms=1.0, warn_threshold_ms=0.5)
        g = PerfGuardrail(budget=budget)

        async def slow() -> None:
            await asyncio.sleep(0.02)

        await g.measure(slow())
        await g.measure(slow())

        r = g.report()
        assert r["violations"] == 2
        assert r["total_calls"] == 2


# ---------------------------------------------------------------------------
# 8. PerfGuardrailRegistry.register() and get()
# ---------------------------------------------------------------------------


class TestRegistryRegisterAndGet:
    """Basic CRUD operations on the registry."""

    def test_register_returns_guardrail(self, registry: PerfGuardrailRegistry) -> None:
        budget = PerfBudget("op_a", p99_threshold_ms=50.0, warn_threshold_ms=30.0)
        g = registry.register(budget)
        assert isinstance(g, PerfGuardrail)
        assert g.budget.operation == "op_a"

    def test_get_returns_registered_guardrail(self, registry: PerfGuardrailRegistry) -> None:
        budget = PerfBudget("op_b", p99_threshold_ms=50.0, warn_threshold_ms=30.0)
        registered = registry.register(budget)
        fetched = registry.get("op_b")
        assert fetched is registered

    def test_get_returns_none_for_unknown(self, registry: PerfGuardrailRegistry) -> None:
        assert registry.get("nonexistent") is None

    def test_register_multiple_operations(self, registry: PerfGuardrailRegistry) -> None:
        registry.register(PerfBudget("x", p99_threshold_ms=10.0, warn_threshold_ms=5.0))
        registry.register(PerfBudget("y", p99_threshold_ms=20.0, warn_threshold_ms=10.0))
        assert registry.get("x") is not None
        assert registry.get("y") is not None
        assert registry.operations == ["x", "y"]


# ---------------------------------------------------------------------------
# 9. PerfGuardrailRegistry.check_all() filtering
# ---------------------------------------------------------------------------


class TestRegistryCheckAll:
    """check_all returns only guardrails with violations."""

    async def test_returns_empty_when_no_violations(self, registry: PerfGuardrailRegistry) -> None:
        budget = PerfBudget("clean_op", p99_threshold_ms=5000.0, warn_threshold_ms=3000.0)
        registry.register(budget)
        g = registry.get("clean_op")
        assert g is not None

        async def fast() -> None:
            pass

        await g.measure(fast())
        assert registry.check_all() == []

    async def test_returns_violated_guardrails_only(self, registry: PerfGuardrailRegistry) -> None:
        registry.register(PerfBudget("fast_op", p99_threshold_ms=5000.0, warn_threshold_ms=3000.0))
        registry.register(PerfBudget("slow_op", p99_threshold_ms=1.0, warn_threshold_ms=0.5))

        fast_g = registry.get("fast_op")
        slow_g = registry.get("slow_op")
        assert fast_g is not None
        assert slow_g is not None

        async def instant() -> None:
            pass

        async def slow() -> None:
            await asyncio.sleep(0.02)

        await fast_g.measure(instant())
        await slow_g.measure(slow())

        violated = registry.check_all()
        assert len(violated) == 1
        assert violated[0]["operation"] == "slow_op"
        assert violated[0]["violations"] == 1

    async def test_returns_multiple_violated_guardrails(
        self, registry: PerfGuardrailRegistry
    ) -> None:
        registry.register(PerfBudget("a", p99_threshold_ms=1.0, warn_threshold_ms=0.5))
        registry.register(PerfBudget("b", p99_threshold_ms=1.0, warn_threshold_ms=0.5))

        async def slow() -> None:
            await asyncio.sleep(0.02)

        g_a = registry.get("a")
        g_b = registry.get("b")
        assert g_a is not None and g_b is not None

        await g_a.measure(slow())
        await g_b.measure(slow())

        violated = registry.check_all()
        assert len(violated) == 2
        ops = {v["operation"] for v in violated}
        assert ops == {"a", "b"}


# ---------------------------------------------------------------------------
# 10. PerfGuardrailRegistry.reset() clears all counters
# ---------------------------------------------------------------------------


class TestRegistryReset:
    """reset() zeros violation/warning/call counters on all guardrails."""

    async def test_reset_clears_violations(self, registry: PerfGuardrailRegistry) -> None:
        registry.register(PerfBudget("reset_op", p99_threshold_ms=1.0, warn_threshold_ms=0.5))
        g = registry.get("reset_op")
        assert g is not None

        async def slow() -> None:
            await asyncio.sleep(0.02)

        await g.measure(slow())
        assert g._violations > 0

        registry.reset()
        assert g._violations == 0
        assert g._warnings == 0
        assert g._total_calls == 0
        assert registry.check_all() == []


# ---------------------------------------------------------------------------
# 11. default_registry has all 5 budgets
# ---------------------------------------------------------------------------


class TestDefaultRegistry:
    """Verify the module-level default_registry is pre-populated."""

    def test_has_five_operations(self) -> None:
        assert len(default_registry.operations) == 5

    def test_all_expected_operations_present(self) -> None:
        expected = {
            "health_check",
            "db_query",
            "agent_invoke",
            "metrics_scrape",
            "session_operation",
        }
        assert set(default_registry.operations) == expected

    def test_health_check_p99_threshold(self) -> None:
        g = default_registry.get("health_check")
        assert g is not None
        assert g.budget.p99_threshold_ms == 50.0

    def test_health_check_warn_threshold(self) -> None:
        g = default_registry.get("health_check")
        assert g is not None
        assert g.budget.warn_threshold_ms == 30.0

    def test_db_query_p99_threshold(self) -> None:
        g = default_registry.get("db_query")
        assert g is not None
        assert g.budget.p99_threshold_ms == 100.0

    def test_db_query_warn_threshold(self) -> None:
        g = default_registry.get("db_query")
        assert g is not None
        assert g.budget.warn_threshold_ms == 75.0

    def test_agent_invoke_p99_threshold(self) -> None:
        g = default_registry.get("agent_invoke")
        assert g is not None
        assert g.budget.p99_threshold_ms == 5000.0

    def test_metrics_scrape_p99_threshold(self) -> None:
        g = default_registry.get("metrics_scrape")
        assert g is not None
        assert g.budget.p99_threshold_ms == 200.0

    def test_session_operation_p99_threshold(self) -> None:
        g = default_registry.get("session_operation")
        assert g is not None
        assert g.budget.p99_threshold_ms == 500.0


# ---------------------------------------------------------------------------
# 12. DEFAULT_BUDGETS list accessible for custom registries
# ---------------------------------------------------------------------------


class TestDefaultBudgetsList:
    """DEFAULT_BUDGETS is a public list for consumers that want to build
    custom registries from the same baseline."""

    def test_is_list_of_perf_budget(self) -> None:
        assert isinstance(DEFAULT_BUDGETS, list)
        for b in DEFAULT_BUDGETS:
            assert isinstance(b, PerfBudget)

    def test_length_matches_default_registry(self) -> None:
        assert len(DEFAULT_BUDGETS) == len(default_registry.operations)


# ---------------------------------------------------------------------------
# 13. Violation count increments on multiple calls
# ---------------------------------------------------------------------------


class TestViolationCountIncrement:
    """Multiple over-threshold calls must each increment the counter."""

    async def test_three_violations_counted(self) -> None:
        budget = PerfBudget("incr_op", p99_threshold_ms=1.0, warn_threshold_ms=0.5)
        g = PerfGuardrail(budget=budget)

        async def slow() -> None:
            await asyncio.sleep(0.02)

        await g.measure(slow())
        await g.measure(slow())
        await g.measure(slow())

        assert g._violations == 3
        assert g._total_calls == 3
        r = g.report()
        assert r["violations"] == 3
        assert r["total_calls"] == 3


# ---------------------------------------------------------------------------
# 14. measure() re-raises exceptions from the coroutine
# ---------------------------------------------------------------------------


class TestMeasureReRaisesExceptions:
    """measure() must propagate exceptions after recording duration."""

    async def test_value_error_reraises(self, guardrail: PerfGuardrail) -> None:
        async def exploding() -> None:
            raise ValueError("kaboom")

        with pytest.raises(ValueError, match="kaboom"):
            await guardrail.measure(exploding())

    async def test_runtime_error_reraises(self, guardrail: PerfGuardrail) -> None:
        async def exploding() -> None:
            raise RuntimeError("connection lost")

        with pytest.raises(RuntimeError, match="connection lost"):
            await guardrail.measure(exploding())

    async def test_total_calls_incremented_on_exception(self, guardrail: PerfGuardrail) -> None:
        """Even when the coroutine raises, total_calls must still increment."""

        async def exploding() -> None:
            raise ValueError("oops")

        with pytest.raises(ValueError):
            await guardrail.measure(exploding())

        assert guardrail._total_calls == 1

    async def test_violation_not_recorded_for_fast_exception(
        self, guardrail: PerfGuardrail
    ) -> None:
        """A fast-failing coroutine should not count as a violation."""

        async def fast_fail() -> None:
            raise ValueError("instant failure")

        with pytest.raises(ValueError):
            await guardrail.measure(fast_fail())

        assert guardrail._violations == 0


# ---------------------------------------------------------------------------
# 15. PerfGuardrail.reset() clears individual counters
# ---------------------------------------------------------------------------


class TestGuardrailReset:
    """Individual guardrail reset zeroes its own counters."""

    async def test_reset_clears_all_counters(self) -> None:
        budget = PerfBudget("rst_op", p99_threshold_ms=1.0, warn_threshold_ms=0.5)
        g = PerfGuardrail(budget=budget)

        async def slow() -> None:
            await asyncio.sleep(0.02)

        await g.measure(slow())
        assert g._violations > 0

        g.reset()
        assert g._violations == 0
        assert g._warnings == 0
        assert g._total_calls == 0
