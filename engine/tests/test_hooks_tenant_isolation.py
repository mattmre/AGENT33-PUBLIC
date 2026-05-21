"""Tests for tenant isolation hardening in HookRegistry (Phase 32)."""

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
    tenant_id: str = "",
) -> HookDefinition:
    kwargs: dict = {
        "name": name,
        "event_type": event_type,
        "handler_ref": "test.Handler",
        "priority": priority,
        "tenant_id": tenant_id,
    }
    if hook_id:
        kwargs["hook_id"] = hook_id
    return HookDefinition(**kwargs)


# ---------------------------------------------------------------------------
# Registration tenant isolation
# ---------------------------------------------------------------------------


class TestRegisterTenantIsolation:
    """Validate tenant ownership enforcement during hook registration."""

    def test_register_allows_matching_tenant(self) -> None:
        reg = HookRegistry()
        hook = _make_hook(name="h1", tenant_id="acme")
        reg.register(hook, tenant_id="acme")
        assert reg.count() == 1

    def test_register_allows_system_hook_from_admin(self) -> None:
        reg = HookRegistry()
        hook = _make_hook(name="sys", tenant_id="")
        reg.register(hook, tenant_id="")
        assert reg.count() == 1

    def test_register_allows_system_hook_from_any_tenant(self) -> None:
        """A hook with tenant_id='' (system) can be registered by anyone."""
        reg = HookRegistry()
        hook = _make_hook(name="sys", tenant_id="")
        reg.register(hook, tenant_id="acme")
        assert reg.count() == 1

    def test_register_rejects_mismatched_tenant(self) -> None:
        reg = HookRegistry()
        hook = _make_hook(name="h1", tenant_id="acme")
        with pytest.raises(PermissionError, match="does not match"):
            reg.register(hook, tenant_id="other")

    def test_register_without_tenant_always_succeeds(self) -> None:
        """Admin mode (tenant_id='') bypasses validation."""
        reg = HookRegistry()
        hook = _make_hook(name="h1", tenant_id="acme")
        reg.register(hook, tenant_id="")
        assert reg.count() == 1


# ---------------------------------------------------------------------------
# Deregistration tenant isolation
# ---------------------------------------------------------------------------


class TestDeregisterTenantIsolation:
    """Validate tenant-scoped deregistration."""

    def test_deregister_scoped_to_tenant(self) -> None:
        reg = HookRegistry()
        acme = _make_hook(name="shared-name", tenant_id="acme")
        other = _make_hook(name="shared-name", tenant_id="other")
        reg.register(acme)
        reg.register(other)
        assert reg.count() == 2

        # Only remove acme's hook
        removed = reg.deregister("shared-name", tenant_id="acme")
        assert removed is True
        # other's hook remains
        hooks = reg.get_hooks("agent.invoke.pre", "other")
        assert len(hooks) == 1
        assert hooks[0].tenant_id == "other"

    def test_deregister_admin_removes_all(self) -> None:
        reg = HookRegistry()
        reg.register(_make_hook(name="h1", tenant_id="acme"))
        reg.register(_make_hook(name="h1", tenant_id="other"))
        assert reg.count() == 2

        removed = reg.deregister("h1")  # no tenant_id = admin
        assert removed is True
        assert reg.count() == 0

    def test_deregister_tenant_cannot_remove_others_hook(self) -> None:
        reg = HookRegistry()
        reg.register(_make_hook(name="h1", tenant_id="other"))

        removed = reg.deregister("h1", tenant_id="acme")
        assert removed is False
        assert reg.count() == 1  # still there

    def test_deregister_tenant_removes_own_definition(self) -> None:
        reg = HookRegistry()
        hook = _make_hook(name="h1", tenant_id="acme")
        defn = _make_definition(name="h1", hook_id="def1", tenant_id="acme")
        reg.register(hook, defn)

        reg.deregister("h1", tenant_id="acme")
        assert reg.get_definition("def1") is None

    def test_deregister_tenant_leaves_other_definition(self) -> None:
        reg = HookRegistry()
        hook = _make_hook(name="h1", tenant_id="other")
        defn = _make_definition(name="h1", hook_id="def1", tenant_id="other")
        reg.register(hook, defn)

        reg.deregister("h1", tenant_id="acme")
        assert reg.get_definition("def1") is not None


# ---------------------------------------------------------------------------
# get_definition tenant isolation
# ---------------------------------------------------------------------------


class TestGetDefinitionTenantIsolation:
    """Validate tenant-scoped definition retrieval."""

    def test_admin_sees_all_definitions(self) -> None:
        reg = HookRegistry()
        reg.register(
            _make_hook(name="h1", tenant_id="acme"),
            _make_definition(name="h1", hook_id="d1", tenant_id="acme"),
        )
        assert reg.get_definition("d1") is not None

    def test_owning_tenant_sees_own_definition(self) -> None:
        reg = HookRegistry()
        reg.register(
            _make_hook(name="h1", tenant_id="acme"),
            _make_definition(name="h1", hook_id="d1", tenant_id="acme"),
        )
        assert reg.get_definition("d1", tenant_id="acme") is not None

    def test_other_tenant_cannot_see_definition(self) -> None:
        reg = HookRegistry()
        reg.register(
            _make_hook(name="h1", tenant_id="acme"),
            _make_definition(name="h1", hook_id="d1", tenant_id="acme"),
        )
        assert reg.get_definition("d1", tenant_id="other") is None

    def test_system_definition_visible_to_all(self) -> None:
        reg = HookRegistry()
        reg.register(
            _make_hook(name="sys", tenant_id=""),
            _make_definition(name="sys", hook_id="sys1", tenant_id=""),
        )
        assert reg.get_definition("sys1", tenant_id="acme") is not None
        assert reg.get_definition("sys1", tenant_id="other") is not None
        assert reg.get_definition("sys1") is not None


# ---------------------------------------------------------------------------
# update_definition tenant isolation
# ---------------------------------------------------------------------------


class TestUpdateDefinitionTenantIsolation:
    def test_update_allowed_for_matching_tenant(self) -> None:
        reg = HookRegistry()
        reg.register(
            _make_hook(name="h1", tenant_id="acme"),
            _make_definition(name="h1", hook_id="d1", tenant_id="acme"),
        )
        updated = reg.update_definition("d1", {"priority": 50}, tenant_id="acme")
        assert updated is not None
        assert updated.priority == 50

    def test_update_allowed_for_admin(self) -> None:
        reg = HookRegistry()
        reg.register(
            _make_hook(name="h1", tenant_id="acme"),
            _make_definition(name="h1", hook_id="d1", tenant_id="acme"),
        )
        updated = reg.update_definition("d1", {"priority": 50})
        assert updated is not None

    def test_update_blocked_for_wrong_tenant(self) -> None:
        reg = HookRegistry()
        reg.register(
            _make_hook(name="h1", tenant_id="acme"),
            _make_definition(name="h1", hook_id="d1", tenant_id="acme"),
        )
        with pytest.raises(PermissionError, match="cannot update"):
            reg.update_definition("d1", {"priority": 50}, tenant_id="other")

    def test_update_system_hook_blocked_for_tenant(self) -> None:
        reg = HookRegistry()
        reg.register(
            _make_hook(name="sys", tenant_id=""),
            _make_definition(name="sys", hook_id="s1", tenant_id=""),
        )
        with pytest.raises(PermissionError):
            reg.update_definition("s1", {"priority": 50}, tenant_id="acme")


# ---------------------------------------------------------------------------
# toggle tenant isolation
# ---------------------------------------------------------------------------


class TestToggleTenantIsolation:
    def test_toggle_allowed_for_matching_tenant(self) -> None:
        reg = HookRegistry()
        reg.register(
            _make_hook(name="h1", tenant_id="acme"),
            _make_definition(name="h1", hook_id="d1", tenant_id="acme"),
        )
        toggled = reg.toggle("d1", False, tenant_id="acme")
        assert toggled is not None
        assert toggled.enabled is False

    def test_toggle_blocked_for_wrong_tenant(self) -> None:
        reg = HookRegistry()
        reg.register(
            _make_hook(name="h1", tenant_id="acme"),
            _make_definition(name="h1", hook_id="d1", tenant_id="acme"),
        )
        with pytest.raises(PermissionError, match="cannot toggle"):
            reg.toggle("d1", False, tenant_id="other")

    def test_toggle_only_updates_matching_tenant_runtime_hook(self) -> None:
        reg = HookRegistry()
        acme_hook = _make_hook(name="shared", tenant_id="acme")
        other_hook = _make_hook(name="shared", tenant_id="other")
        reg.register(
            acme_hook,
            _make_definition(name="shared", hook_id="d1", tenant_id="acme"),
        )
        reg.register(
            other_hook,
            _make_definition(name="shared", hook_id="d2", tenant_id="other"),
        )

        reg.toggle("d1", False, tenant_id="acme")

        assert acme_hook.enabled is False
        assert other_hook.enabled is True


# ---------------------------------------------------------------------------
# delete_definition tenant isolation
# ---------------------------------------------------------------------------


class TestDeleteDefinitionTenantIsolation:
    def test_delete_allowed_for_matching_tenant(self) -> None:
        reg = HookRegistry()
        reg.register(
            _make_hook(name="h1", tenant_id="acme"),
            _make_definition(name="h1", hook_id="d1", tenant_id="acme"),
        )
        assert reg.delete_definition("d1", tenant_id="acme") is True
        assert reg.get_definition("d1") is None

    def test_delete_allowed_for_admin(self) -> None:
        reg = HookRegistry()
        reg.register(
            _make_hook(name="h1", tenant_id="acme"),
            _make_definition(name="h1", hook_id="d1", tenant_id="acme"),
        )
        assert reg.delete_definition("d1") is True

    def test_delete_blocked_for_wrong_tenant(self) -> None:
        reg = HookRegistry()
        reg.register(
            _make_hook(name="h1", tenant_id="acme"),
            _make_definition(name="h1", hook_id="d1", tenant_id="acme"),
        )
        with pytest.raises(PermissionError, match="cannot delete"):
            reg.delete_definition("d1", tenant_id="other")
        # Definition should still exist
        assert reg.get_definition("d1") is not None

    def test_delete_only_removes_matching_tenant_runtime_hook(self) -> None:
        reg = HookRegistry()
        acme_hook = _make_hook(name="shared", tenant_id="acme")
        other_hook = _make_hook(name="shared", tenant_id="other")
        reg.register(
            acme_hook,
            _make_definition(name="shared", hook_id="d1", tenant_id="acme"),
        )
        reg.register(
            other_hook,
            _make_definition(name="shared", hook_id="d2", tenant_id="other"),
        )

        assert reg.delete_definition("d1", tenant_id="acme") is True

        other_hooks = reg.get_hooks("agent.invoke.pre", "other")
        assert len(other_hooks) == 1
        assert other_hooks[0].tenant_id == "other"
        assert reg.get_definition("d2", tenant_id="other") is not None
