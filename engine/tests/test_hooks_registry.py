"""Tests for HookRegistry: registration, tenant filtering, event indexing."""

from __future__ import annotations

import pytest

from agent33.hooks.models import HookDefinition, HookEventType
from agent33.hooks.protocol import BaseHook
from agent33.hooks.registry import HookRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hook(
    name: str = "test",
    event_type: str = "agent.invoke.pre",
    priority: int = 100,
    tenant_id: str = "",
    enabled: bool = True,
) -> BaseHook:
    return BaseHook(
        name=name,
        event_type=event_type,
        priority=priority,
        enabled=enabled,
        tenant_id=tenant_id,
    )


def _make_definition(
    name: str = "test",
    event_type: HookEventType = HookEventType.AGENT_INVOKE_PRE,
    priority: int = 100,
    hook_id: str | None = None,
) -> HookDefinition:
    kwargs = {
        "name": name,
        "event_type": event_type,
        "handler_ref": "test.Handler",
        "priority": priority,
    }
    if hook_id:
        kwargs["hook_id"] = hook_id
    return HookDefinition(**kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_hook(self) -> None:
        reg = HookRegistry()
        hook = _make_hook(name="h1")
        reg.register(hook)
        assert reg.count() == 1

    def test_register_with_definition(self) -> None:
        reg = HookRegistry()
        hook = _make_hook(name="h1")
        defn = _make_definition(name="h1", hook_id="hook_123")
        reg.register(hook, defn)
        assert reg.count() == 1
        assert reg.get_definition("hook_123") is not None
        assert reg.get_definition("hook_123").name == "h1"

    def test_max_per_event_enforced(self) -> None:
        reg = HookRegistry(max_per_event=2)
        h1 = _make_hook(name="h1")
        h2 = _make_hook(name="h2")
        h3 = _make_hook(name="h3")
        reg.register(h1)
        reg.register(h2)
        with pytest.raises(ValueError, match="Max hooks"):
            reg.register(h3)

    def test_deregister_by_name(self) -> None:
        reg = HookRegistry()
        hook = _make_hook(name="removeme")
        defn = _make_definition(name="removeme", hook_id="hook_rm")
        reg.register(hook, defn)
        assert reg.count() == 1

        removed = reg.deregister("removeme")
        assert removed is True
        assert reg.count() == 0
        assert reg.get_definition("hook_rm") is None

    def test_deregister_nonexistent(self) -> None:
        reg = HookRegistry()
        assert reg.deregister("ghost") is False

    def test_deregister_by_event_type(self) -> None:
        reg = HookRegistry()
        h1 = _make_hook(name="h1", event_type="agent.invoke.pre")
        h2 = _make_hook(name="h1", event_type="tool.execute.pre")
        reg.register(h1)
        reg.register(h2)
        assert reg.count() == 2

        reg.deregister("h1", event_type="agent.invoke.pre")
        assert reg.count() == 1
        # Only the tool event type hook remains
        assert len(reg.get_hooks("tool.execute.pre")) == 1
        assert len(reg.get_hooks("agent.invoke.pre")) == 0


class TestRetrieval:
    def test_get_hooks_empty(self) -> None:
        reg = HookRegistry()
        assert reg.get_hooks("agent.invoke.pre") == []

    def test_get_hooks_by_event_type(self) -> None:
        reg = HookRegistry()
        h1 = _make_hook(name="h1", event_type="agent.invoke.pre")
        h2 = _make_hook(name="h2", event_type="tool.execute.pre")
        reg.register(h1)
        reg.register(h2)
        result = reg.get_hooks("agent.invoke.pre")
        assert len(result) == 1
        assert result[0].name == "h1"

    def test_tenant_filtering_system_hook(self) -> None:
        """System hooks (tenant_id='') are returned for all tenants."""
        reg = HookRegistry()
        sys_hook = _make_hook(name="sys", tenant_id="")
        reg.register(sys_hook)
        # System hook should be visible to any tenant
        assert len(reg.get_hooks("agent.invoke.pre", "acme")) == 1
        assert len(reg.get_hooks("agent.invoke.pre", "other")) == 1
        assert len(reg.get_hooks("agent.invoke.pre", "")) == 1

    def test_tenant_filtering_tenant_hook(self) -> None:
        """Tenant hooks are only returned for their own tenant."""
        reg = HookRegistry()
        t_hook = _make_hook(name="acme-only", tenant_id="acme")
        reg.register(t_hook)
        assert len(reg.get_hooks("agent.invoke.pre", "acme")) == 1
        assert len(reg.get_hooks("agent.invoke.pre", "other")) == 0
        assert len(reg.get_hooks("agent.invoke.pre", "")) == 0

    def test_mixed_system_and_tenant_hooks(self) -> None:
        """Both system and matching tenant hooks are returned together."""
        reg = HookRegistry()
        sys_hook = _make_hook(name="sys", tenant_id="", priority=10)
        acme_hook = _make_hook(name="acme-hook", tenant_id="acme", priority=20)
        other_hook = _make_hook(name="other-hook", tenant_id="other", priority=30)
        reg.register(sys_hook)
        reg.register(acme_hook)
        reg.register(other_hook)

        acme_hooks = reg.get_hooks("agent.invoke.pre", "acme")
        assert len(acme_hooks) == 2
        names = {h.name for h in acme_hooks}
        assert names == {"sys", "acme-hook"}


class TestChainRunner:
    def test_get_chain_runner(self) -> None:
        reg = HookRegistry()
        h1 = _make_hook(name="h1")
        reg.register(h1)
        runner = reg.get_chain_runner("agent.invoke.pre", "")
        assert runner is not None


class TestDefinitionCRUD:
    def test_list_definitions_empty(self) -> None:
        reg = HookRegistry()
        assert reg.list_definitions() == []

    def test_list_definitions_with_filter(self) -> None:
        reg = HookRegistry()
        h1 = _make_hook(name="h1", event_type="agent.invoke.pre")
        d1 = _make_definition(name="h1", event_type=HookEventType.AGENT_INVOKE_PRE, hook_id="id1")
        h2 = _make_hook(name="h2", event_type="tool.execute.pre")
        d2 = _make_definition(name="h2", event_type=HookEventType.TOOL_EXECUTE_PRE, hook_id="id2")
        reg.register(h1, d1)
        reg.register(h2, d2)

        all_defs = reg.list_definitions()
        assert len(all_defs) == 2

        agent_defs = reg.list_definitions(event_type="agent.invoke.pre")
        assert len(agent_defs) == 1
        assert agent_defs[0].name == "h1"

    def test_update_definition(self) -> None:
        reg = HookRegistry()
        h1 = _make_hook(name="h1")
        d1 = _make_definition(name="h1", hook_id="upd1")
        reg.register(h1, d1)

        updated = reg.update_definition("upd1", {"description": "new desc", "priority": 50})
        assert updated is not None
        assert updated.description == "new desc"
        assert updated.priority == 50

    def test_update_nonexistent(self) -> None:
        reg = HookRegistry()
        assert reg.update_definition("ghost", {"priority": 10}) is None

    def test_toggle_hook(self) -> None:
        reg = HookRegistry()
        h1 = _make_hook(name="h1")
        d1 = _make_definition(name="h1", hook_id="tog1")
        reg.register(h1, d1)

        toggled = reg.toggle("tog1", False)
        assert toggled is not None
        assert toggled.enabled is False

    def test_delete_definition(self) -> None:
        reg = HookRegistry()
        h1 = _make_hook(name="h1")
        d1 = _make_definition(name="h1", hook_id="del1")
        reg.register(h1, d1)
        assert reg.count() == 1

        deleted = reg.delete_definition("del1")
        assert deleted is True
        assert reg.count() == 0
        assert reg.get_definition("del1") is None

    def test_delete_nonexistent(self) -> None:
        reg = HookRegistry()
        assert reg.delete_definition("ghost") is False


class TestDiscovery:
    def test_discover_builtins(self) -> None:
        reg = HookRegistry()
        count = reg.discover_builtins()
        expected = len(HookEventType) * 2
        assert count == expected
        assert reg.count() == expected

    def test_resolve_handler_valid(self) -> None:
        reg = HookRegistry()
        cls = reg.resolve_handler("agent33.hooks.builtins.MetricsHook")
        assert cls is not None
        from agent33.hooks.builtins import MetricsHook

        assert cls is MetricsHook

    def test_resolve_handler_invalid(self) -> None:
        reg = HookRegistry()
        assert reg.resolve_handler("nonexistent.module.Class") is None

    def test_resolve_handler_no_module(self) -> None:
        reg = HookRegistry()
        assert reg.resolve_handler("NoModule") is None


class TestIntrospection:
    def test_count_empty(self) -> None:
        reg = HookRegistry()
        assert reg.count() == 0

    def test_event_types_empty(self) -> None:
        reg = HookRegistry()
        assert reg.event_types() == []

    def test_event_types_with_hooks(self) -> None:
        reg = HookRegistry()
        reg.register(_make_hook(name="h1", event_type="agent.invoke.pre"))
        reg.register(_make_hook(name="h2", event_type="tool.execute.pre"))
        types = reg.event_types()
        assert set(types) == {"agent.invoke.pre", "tool.execute.pre"}

    def test_stats(self) -> None:
        reg = HookRegistry()
        reg.register(_make_hook(name="h1", event_type="agent.invoke.pre"))
        reg.register(_make_hook(name="h2", event_type="agent.invoke.pre"))
        stats = reg.stats()
        assert stats["total_hooks"] == 2
        assert stats["by_event_type"]["agent.invoke.pre"] == 2
        assert stats["event_types_active"] == 1
