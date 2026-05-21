"""Tests for hook chain runners (sequential and concurrent)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent33.hooks.chain import ConcurrentHookChainRunner, HookChainRunner
from agent33.hooks.models import HookContext
from agent33.hooks.protocol import BaseHook

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class PassthroughHook(BaseHook):
    """Hook that delegates to call_next without modification."""

    async def execute(self, context, call_next):
        return await call_next(context)


class MetadataHook(BaseHook):
    """Hook that adds a key to context.metadata before calling next."""

    def __init__(self, *, name: str, key: str, value: str, **kwargs: Any) -> None:
        super().__init__(name=name, **kwargs)
        self._key = key
        self._value = value

    async def execute(self, context, call_next):
        context.metadata[self._key] = self._value
        return await call_next(context)


class AbortHook(BaseHook):
    """Hook that aborts the chain."""

    def __init__(self, *, name: str, reason: str = "aborted", **kwargs: Any) -> None:
        super().__init__(name=name, **kwargs)
        self._reason = reason

    async def execute(self, context, call_next):
        context.abort = True
        context.abort_reason = self._reason
        return context


class FailingHook(BaseHook):
    """Hook that always raises an exception."""

    async def execute(self, context, call_next):
        raise RuntimeError("hook_failure")


class SlowHook(BaseHook):
    """Hook that sleeps longer than the timeout."""

    async def execute(self, context, call_next):
        await asyncio.sleep(10)
        return await call_next(context)


# ---------------------------------------------------------------------------
# HookChainRunner tests
# ---------------------------------------------------------------------------


class TestHookChainRunner:
    @pytest.fixture()
    def ctx(self) -> HookContext:
        return HookContext(event_type="test", tenant_id="t1", metadata={})

    async def test_empty_chain_returns_context(self, ctx: HookContext) -> None:
        runner = HookChainRunner(hooks=[], timeout_ms=500)
        result = await runner.run(ctx)
        assert result is ctx
        assert result.abort is False

    async def test_single_hook_passthrough(self, ctx: HookContext) -> None:
        hook = PassthroughHook(name="pt", event_type="test", priority=100)
        runner = HookChainRunner(hooks=[hook], timeout_ms=500)
        result = await runner.run(ctx)
        assert result.abort is False
        assert len(result.results) == 1
        assert result.results[0].hook_name == "pt"
        assert result.results[0].success is True

    async def test_priority_ordering(self, ctx: HookContext) -> None:
        """Hooks must execute in ascending priority order."""
        h1 = MetadataHook(name="first", key="order", value="1", event_type="test", priority=10)
        h2 = MetadataHook(name="second", key="order", value="2", event_type="test", priority=20)
        h3 = MetadataHook(name="third", key="order", value="3", event_type="test", priority=30)

        # Register in wrong order
        runner = HookChainRunner(hooks=[h3, h1, h2], timeout_ms=500)
        result = await runner.run(ctx)

        # The last writer wins on the same key, but priority order
        # should be 10 -> 20 -> 30, so "third" writes last
        assert result.metadata["order"] == "3"
        assert len(result.results) == 3
        # In a middleware chain, results are appended from innermost out.
        # The innermost (highest priority) hook's result is appended first
        # as it finishes first after terminal returns.
        result_names = {r.hook_name for r in result.results}
        assert result_names == {"first", "second", "third"}

    async def test_metadata_passing_between_hooks(self, ctx: HookContext) -> None:
        """A hook can read metadata set by a prior hook."""
        h1 = MetadataHook(name="setter", key="x", value="42", event_type="test", priority=10)

        class ReaderHook(BaseHook):
            read_value: str | None = None

            async def execute(self, context, call_next):
                self.read_value = context.metadata.get("x")
                return await call_next(context)

        h2 = ReaderHook(name="reader", event_type="test", priority=20)
        runner = HookChainRunner(hooks=[h1, h2], timeout_ms=500)
        await runner.run(ctx)
        assert h2.read_value == "42"

    async def test_abort_stops_chain(self, ctx: HookContext) -> None:
        h1 = AbortHook(name="blocker", reason="denied", event_type="test", priority=10)
        h2 = PassthroughHook(name="unreached", event_type="test", priority=20)

        runner = HookChainRunner(hooks=[h1, h2], timeout_ms=500)
        result = await runner.run(ctx)
        assert result.abort is True
        assert result.abort_reason == "denied"
        # Only the abort hook should have run (plus its result)
        assert len(result.results) == 1
        assert result.results[0].hook_name == "blocker"

    async def test_fail_open_continues_chain(self, ctx: HookContext) -> None:
        """In fail-open mode, a failing hook is skipped and the chain continues."""
        h1 = FailingHook(name="bad", event_type="test", priority=10)
        h2 = MetadataHook(name="good", key="ran", value="yes", event_type="test", priority=20)

        runner = HookChainRunner(hooks=[h1, h2], timeout_ms=500, fail_open=True)
        result = await runner.run(ctx)
        assert result.abort is False
        assert result.metadata["ran"] == "yes"
        # Both hooks should have results
        assert len(result.results) == 2
        assert result.results[0].hook_name == "bad"
        assert result.results[0].success is False
        assert "hook_failure" in result.results[0].error
        assert result.results[1].hook_name == "good"
        assert result.results[1].success is True

    async def test_fail_closed_aborts_chain(self, ctx: HookContext) -> None:
        """In fail-closed mode, a failing hook aborts the chain."""
        h1 = FailingHook(name="bad", event_type="test", priority=10)
        h2 = PassthroughHook(name="unreached", event_type="test", priority=20)

        runner = HookChainRunner(hooks=[h1, h2], timeout_ms=500, fail_open=False)
        result = await runner.run(ctx)
        assert result.abort is True
        assert "bad" in result.abort_reason
        # Only the failing hook should have a result
        assert len(result.results) == 1
        assert result.results[0].success is False

    async def test_timeout_triggers_failure(self, ctx: HookContext) -> None:
        """A hook exceeding the timeout is treated as a failure."""
        h1 = SlowHook(name="slow", event_type="test", priority=10)
        h2 = PassthroughHook(name="after", event_type="test", priority=20)

        runner = HookChainRunner(hooks=[h1, h2], timeout_ms=50, fail_open=True)
        result = await runner.run(ctx)
        # Slow hook should fail, fast hook should still run
        assert len(result.results) == 2
        assert result.results[0].hook_name == "slow"
        assert result.results[0].success is False
        assert result.results[1].hook_name == "after"
        assert result.results[1].success is True

    async def test_disabled_hooks_skipped(self, ctx: HookContext) -> None:
        h1 = PassthroughHook(name="enabled", event_type="test", priority=10, enabled=True)
        h2 = PassthroughHook(name="disabled", event_type="test", priority=20, enabled=False)
        h3 = PassthroughHook(name="also_enabled", event_type="test", priority=30, enabled=True)

        runner = HookChainRunner(hooks=[h1, h2, h3], timeout_ms=500)
        result = await runner.run(ctx)
        # Only 2 hooks should have run
        assert len(result.results) == 2
        names = [r.hook_name for r in result.results]
        assert "disabled" not in names
        assert "enabled" in names
        assert "also_enabled" in names

    async def test_to_chain_result(self, ctx: HookContext) -> None:
        h1 = PassthroughHook(name="h1", event_type="test", priority=10)
        runner = HookChainRunner(hooks=[h1], timeout_ms=500)
        result_ctx = await runner.run(ctx)
        chain_result = runner.to_chain_result(result_ctx)
        assert chain_result.event_type == "test"
        assert chain_result.hook_count == 1
        assert chain_result.all_succeeded is True
        assert chain_result.aborted is False

    async def test_many_hooks_in_sequence(self, ctx: HookContext) -> None:
        """Verify correct behavior with many hooks in sequence."""
        hooks = [
            MetadataHook(
                name=f"h{i}",
                key=f"k{i}",
                value=str(i),
                event_type="test",
                priority=i * 10,
            )
            for i in range(10)
        ]
        runner = HookChainRunner(hooks=hooks, timeout_ms=5000)
        result = await runner.run(ctx)
        assert len(result.results) == 10
        for i in range(10):
            assert result.metadata[f"k{i}"] == str(i)

    async def test_hook_duration_recorded(self, ctx: HookContext) -> None:
        h1 = PassthroughHook(name="timed", event_type="test", priority=10)
        runner = HookChainRunner(hooks=[h1], timeout_ms=500)
        result = await runner.run(ctx)
        assert result.results[0].duration_ms >= 0.0


# ---------------------------------------------------------------------------
# ConcurrentHookChainRunner tests
# ---------------------------------------------------------------------------


class TestConcurrentHookChainRunner:
    @pytest.fixture()
    def ctx(self) -> HookContext:
        return HookContext(event_type="test", tenant_id="t1", metadata={})

    async def test_empty_chain(self, ctx: HookContext) -> None:
        runner = ConcurrentHookChainRunner(hooks=[], timeout_ms=500)
        result = await runner.run(ctx)
        assert result is ctx

    async def test_concurrent_execution(self, ctx: HookContext) -> None:
        h1 = PassthroughHook(name="c1", event_type="test", priority=10)
        h2 = PassthroughHook(name="c2", event_type="test", priority=20)

        runner = ConcurrentHookChainRunner(hooks=[h1, h2], timeout_ms=500)
        result = await runner.run(ctx)
        assert len(result.results) == 2
        names = {r.hook_name for r in result.results}
        assert names == {"c1", "c2"}

    async def test_concurrent_failure_isolated(self, ctx: HookContext) -> None:
        """A failing hook in concurrent mode does not prevent others."""
        h1 = FailingHook(name="bad", event_type="test", priority=10)
        h2 = PassthroughHook(name="good", event_type="test", priority=20)

        runner = ConcurrentHookChainRunner(hooks=[h1, h2], timeout_ms=500)
        result = await runner.run(ctx)
        assert len(result.results) == 2
        bad_result = next(r for r in result.results if r.hook_name == "bad")
        good_result = next(r for r in result.results if r.hook_name == "good")
        assert bad_result.success is False
        assert good_result.success is True

    async def test_concurrent_timeout(self, ctx: HookContext) -> None:
        h1 = SlowHook(name="slow", event_type="test", priority=10)
        h2 = PassthroughHook(name="fast", event_type="test", priority=20)

        runner = ConcurrentHookChainRunner(hooks=[h1, h2], timeout_ms=50)
        result = await runner.run(ctx)
        assert len(result.results) == 2
        slow_result = next(r for r in result.results if r.hook_name == "slow")
        fast_result = next(r for r in result.results if r.hook_name == "fast")
        assert slow_result.success is False
        assert fast_result.success is True

    async def test_disabled_hooks_excluded(self, ctx: HookContext) -> None:
        h1 = PassthroughHook(name="on", event_type="test", priority=10, enabled=True)
        h2 = PassthroughHook(name="off", event_type="test", priority=20, enabled=False)

        runner = ConcurrentHookChainRunner(hooks=[h1, h2], timeout_ms=500)
        result = await runner.run(ctx)
        assert len(result.results) == 1
        assert result.results[0].hook_name == "on"
