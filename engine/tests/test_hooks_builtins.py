"""Tests for built-in hooks: MetricsHook, AuditLogHook."""

from __future__ import annotations

import pytest

from agent33.hooks.builtins import AuditLogHook, MetricsHook, get_builtin_hooks
from agent33.hooks.models import AgentHookContext, HookContext, HookEventType, RequestHookContext

# ---------------------------------------------------------------------------
# MetricsHook
# ---------------------------------------------------------------------------


class TestMetricsHook:
    @pytest.fixture()
    def hook(self) -> MetricsHook:
        h = MetricsHook()
        h._event_type = "agent.invoke.pre"  # noqa: SLF001
        return h

    async def test_records_call_count(self, hook: MetricsHook) -> None:
        ctx = HookContext(event_type="agent.invoke.pre", tenant_id="t1", metadata={})

        async def noop(c: HookContext) -> HookContext:
            return c

        await hook.execute(ctx, noop)
        assert hook.call_counts.get("agent.invoke.pre") == 1

        await hook.execute(ctx, noop)
        assert hook.call_counts.get("agent.invoke.pre") == 2

    async def test_records_duration(self, hook: MetricsHook) -> None:
        ctx = HookContext(event_type="agent.invoke.pre", tenant_id="t1", metadata={})

        async def noop(c: HookContext) -> HookContext:
            return c

        result = await hook.execute(ctx, noop)
        metrics = result.metadata.get("hook_metrics", {})
        assert "agent.invoke.pre" in metrics
        assert metrics["agent.invoke.pre"]["call_count"] == 1
        assert metrics["agent.invoke.pre"]["last_duration_ms"] >= 0.0

    async def test_delegates_to_next(self, hook: MetricsHook) -> None:
        ctx = HookContext(event_type="agent.invoke.pre", tenant_id="t1", metadata={})

        async def marker(c: HookContext) -> HookContext:
            c.metadata["downstream_ran"] = True
            return c

        result = await hook.execute(ctx, marker)
        assert result.metadata["downstream_ran"] is True

    async def test_cumulative_duration(self, hook: MetricsHook) -> None:
        ctx = HookContext(event_type="agent.invoke.pre", tenant_id="t1", metadata={})

        async def noop(c: HookContext) -> HookContext:
            return c

        await hook.execute(ctx, noop)
        await hook.execute(ctx, noop)
        durations = hook.total_duration_ms
        # Duration may round to 0.0 on fast machines; verify the key exists
        assert "agent.invoke.pre" in durations
        assert durations["agent.invoke.pre"] >= 0.0


# ---------------------------------------------------------------------------
# AuditLogHook
# ---------------------------------------------------------------------------


class TestAuditLogHook:
    @pytest.fixture()
    def hook(self) -> AuditLogHook:
        h = AuditLogHook()
        h._event_type = "agent.invoke.pre"  # noqa: SLF001
        return h

    async def test_logs_entry(self, hook: AuditLogHook) -> None:
        ctx = HookContext(event_type="agent.invoke.pre", tenant_id="acme", metadata={})

        async def noop(c: HookContext) -> HookContext:
            return c

        await hook.execute(ctx, noop)
        entries = hook.log_entries
        assert len(entries) == 1
        assert entries[0]["event_type"] == "agent.invoke.pre"
        assert entries[0]["tenant_id"] == "acme"
        assert "timestamp" in entries[0]

    async def test_logs_agent_name(self, hook: AuditLogHook) -> None:
        ctx = AgentHookContext(
            event_type="agent.invoke.pre",
            tenant_id="t1",
            metadata={},
            agent_name="code-worker",
        )

        async def noop(c: HookContext) -> HookContext:
            return c

        await hook.execute(ctx, noop)
        entry = hook.log_entries[0]
        assert entry["agent_name"] == "code-worker"

    async def test_logs_request_fields(self, hook: AuditLogHook) -> None:
        hook._event_type = "request.pre"  # noqa: SLF001
        ctx = RequestHookContext(
            event_type="request.pre",
            tenant_id="",
            metadata={},
            method="POST",
            path="/v1/test",
        )

        async def noop(c: HookContext) -> HookContext:
            return c

        await hook.execute(ctx, noop)
        entry = hook.log_entries[0]
        assert entry["method"] == "POST"
        assert entry["path"] == "/v1/test"

    async def test_delegates_to_next(self, hook: AuditLogHook) -> None:
        ctx = HookContext(event_type="agent.invoke.pre", tenant_id="", metadata={})

        async def marker(c: HookContext) -> HookContext:
            c.metadata["marked"] = True
            return c

        result = await hook.execute(ctx, marker)
        assert result.metadata["marked"] is True


# ---------------------------------------------------------------------------
# get_builtin_hooks factory
# ---------------------------------------------------------------------------


class TestGetBuiltinHooks:
    def test_returns_correct_count(self) -> None:
        builtins = get_builtin_hooks()
        assert len(builtins) == len(HookEventType) * 2

    def test_all_have_definitions(self) -> None:
        builtins = get_builtin_hooks()
        for _hook, defn in builtins:
            assert defn.name.startswith("builtin.")
            assert defn.handler_ref.startswith("agent33.hooks.builtins.")
            assert defn.tenant_id == ""
            assert defn.fail_mode == "open"
            assert "builtin" in defn.tags

    def test_hooks_have_correct_event_types(self) -> None:
        builtins = get_builtin_hooks()
        for hook, defn in builtins:
            assert hook.event_type == defn.event_type.value
