"""Hook registry: registration, tenant filtering, event type indexing."""

from __future__ import annotations

import importlib
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from agent33.hooks.chain import HookChainRunner

if TYPE_CHECKING:
    from agent33.hooks.models import HookDefinition

logger = logging.getLogger(__name__)


class HookRegistry:
    """Central registry for hook instances.

    Manages registration/deregistration of hooks, provides tenant-filtered
    retrieval by event type, and supports built-in hook discovery.
    """

    def __init__(self, max_per_event: int = 20) -> None:
        self._hooks: dict[str, list[Any]] = defaultdict(list)
        self._definitions: dict[str, HookDefinition] = {}
        self._max_per_event = max_per_event

    # ------------------------------------------------------------------
    # Tenant helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_tenant_write(
        caller_tenant: str, owner_tenant: str, operation: str, name: str
    ) -> None:
        """Raise ``PermissionError`` when a tenant tries to mutate another's hook."""
        if caller_tenant and owner_tenant != caller_tenant:
            raise PermissionError(
                f"Tenant '{caller_tenant}' cannot {operation} '{name}' "
                f"owned by tenant '{owner_tenant or '(system)'}'"
            )

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self, hook: Any, definition: HookDefinition | None = None, *, tenant_id: str = ""
    ) -> None:
        """Register a hook instance.

        Args:
            hook: An object satisfying the Hook protocol.
            definition: Optional persistent definition for API management.
            tenant_id: Caller's tenant ID for ownership validation.  When
                non-empty, the hook's ``tenant_id`` must match or a
                ``PermissionError`` is raised.

        Raises:
            ValueError: If the event type limit is exceeded.
            PermissionError: If *tenant_id* doesn't match the hook's tenant.
        """
        if tenant_id and hook.tenant_id and hook.tenant_id != tenant_id:
            raise PermissionError(
                f"Cannot register hook '{hook.name}': hook tenant "
                f"'{hook.tenant_id}' does not match caller tenant '{tenant_id}'"
            )
        event_type = hook.event_type
        existing = self._hooks[event_type]
        if len(existing) >= self._max_per_event:
            raise ValueError(
                f"Max hooks ({self._max_per_event}) reached for event type '{event_type}'"
            )
        existing.append(hook)
        if definition is not None:
            self._definitions[definition.hook_id] = definition
        logger.info(
            "hook_registered name=%s event=%s priority=%d tenant=%s",
            hook.name,
            event_type,
            hook.priority,
            hook.tenant_id or "(system)",
        )

    def deregister(
        self, hook_name: str, event_type: str | None = None, *, tenant_id: str = ""
    ) -> bool:
        """Remove a hook by name. Returns True if removed.

        If *event_type* is specified, only removes from that event type's list.
        Otherwise, removes from all event types.

        Args:
            hook_name: Name of the hook to remove.
            event_type: If specified, only removes from this event type.
            tenant_id: When non-empty, only removes hooks owned by this
                tenant.  System and other tenants' hooks are left in place.
        """
        removed = False
        event_types = [event_type] if event_type else list(self._hooks.keys())
        for et in event_types:
            before = len(self._hooks[et])
            if tenant_id:
                # Only remove hooks belonging to the specified tenant
                self._hooks[et] = [
                    h
                    for h in self._hooks[et]
                    if not (h.name == hook_name and h.tenant_id == tenant_id)
                ]
            else:
                self._hooks[et] = [h for h in self._hooks[et] if h.name != hook_name]
            if len(self._hooks[et]) < before:
                removed = True
        # Also remove the definition if present
        if tenant_id:
            to_remove = [
                hid
                for hid, d in self._definitions.items()
                if d.name == hook_name and d.tenant_id == tenant_id
            ]
        else:
            to_remove = [hid for hid, d in self._definitions.items() if d.name == hook_name]
        for hid in to_remove:
            del self._definitions[hid]
        if removed:
            logger.info("hook_deregistered name=%s tenant=%s", hook_name, tenant_id or "(any)")
        return removed

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_hooks(self, event_type: str, tenant_id: str = "") -> list[Any]:
        """Return hooks for the given event type, filtered by tenant.

        Returns:
        - System hooks (tenant_id="") -- always included
        - Tenant-specific hooks matching the provided tenant_id
        """
        return [
            h
            for h in self._hooks.get(event_type, [])
            if h.tenant_id == "" or h.tenant_id == tenant_id
        ]

    def get_chain_runner(
        self,
        event_type: str,
        tenant_id: str = "",
        timeout_ms: float = 500.0,
        fail_open: bool = True,
    ) -> HookChainRunner:
        """Build a HookChainRunner for the given event type and tenant."""
        hooks = self.get_hooks(event_type, tenant_id)
        return HookChainRunner(hooks=hooks, timeout_ms=timeout_ms, fail_open=fail_open)

    def get_definition(self, hook_id: str, *, tenant_id: str = "") -> HookDefinition | None:
        """Return a hook definition by ID.

        When *tenant_id* is non-empty, returns the definition only if it is a
        system-level definition (``tenant_id=""``) or belongs to the caller's
        tenant.
        """
        defn = self._definitions.get(hook_id)
        if defn is None:
            return None
        if tenant_id and defn.tenant_id not in ("", tenant_id):
            return None
        return defn

    def list_definitions(
        self,
        event_type: str | None = None,
        tenant_id: str | None = None,
        enabled: bool | None = None,
    ) -> list[HookDefinition]:
        """List hook definitions with optional filtering."""
        result: list[HookDefinition] = []
        for d in self._definitions.values():
            if event_type is not None and d.event_type != event_type:
                continue
            if tenant_id is not None and d.tenant_id != tenant_id:
                continue
            if enabled is not None and d.enabled != enabled:
                continue
            result.append(d)
        return result

    def update_definition(
        self,
        hook_id: str,
        updates: dict[str, Any],
        *,
        tenant_id: str = "",
    ) -> HookDefinition | None:
        """Update a hook definition. Returns the updated definition or None.

        Raises:
            PermissionError: If *tenant_id* is non-empty and the definition
                belongs to a different tenant.
        """
        defn = self._definitions.get(hook_id)
        if defn is None:
            return None
        self._check_tenant_write(tenant_id, defn.tenant_id, "update", hook_id)
        updated = defn.model_copy(update=updates)
        self._definitions[hook_id] = updated
        return updated

    def toggle(self, hook_id: str, enabled: bool, *, tenant_id: str = "") -> HookDefinition | None:
        """Toggle a hook's enabled state.

        Raises:
            PermissionError: If *tenant_id* is non-empty and the definition
                belongs to a different tenant.
        """
        defn = self._definitions.get(hook_id)
        if defn is None:
            return None
        self._check_tenant_write(tenant_id, defn.tenant_id, "toggle", hook_id)
        updated = defn.model_copy(update={"enabled": enabled})
        self._definitions[hook_id] = updated
        # Also update the runtime hook instance if present
        runtime_event_type = defn.event_type.value
        for hook in self._hooks.get(runtime_event_type, []):
            if (
                hook.name == defn.name
                and hook.tenant_id == defn.tenant_id
                and hasattr(hook, "_enabled")
            ):
                hook._enabled = enabled  # noqa: SLF001
        return updated

    def delete_definition(self, hook_id: str, *, tenant_id: str = "") -> bool:
        """Delete a hook definition and deregister the hook. Returns True if found.

        Raises:
            PermissionError: If *tenant_id* is non-empty and the definition
                belongs to a different tenant.
        """
        defn = self._definitions.get(hook_id)
        if defn is None:
            return False
        self._check_tenant_write(tenant_id, defn.tenant_id, "delete", hook_id)
        del self._definitions[hook_id]
        event_type = defn.event_type.value
        self._hooks[event_type] = [
            hook
            for hook in self._hooks.get(event_type, [])
            if not (hook.name == defn.name and hook.tenant_id == defn.tenant_id)
        ]
        return True

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover_builtins(self) -> int:
        """Discover and register built-in hooks from agent33.hooks.builtins.

        Returns the number of hooks registered.
        """
        count = 0
        try:
            from agent33.hooks.builtins import get_builtin_hooks

            for hook, defn in get_builtin_hooks():
                try:
                    self.register(hook, defn)
                    count += 1
                except ValueError:
                    logger.warning(
                        "failed to register builtin hook %s: limit exceeded",
                        hook.name,
                    )
        except ImportError:
            logger.debug("builtins module not available")
        logger.info("builtin_hooks_discovered count=%d", count)
        return count

    def resolve_handler(self, handler_ref: str) -> Any | None:
        """Resolve a dotted Python path to a callable/class.

        Args:
            handler_ref: Dotted path like 'agent33.hooks.builtins.MetricsHook'.

        Returns:
            The resolved object, or None if resolution fails.
        """
        try:
            module_path, _, attr_name = handler_ref.rpartition(".")
            if not module_path:
                return None
            module = importlib.import_module(module_path)
            return getattr(module, attr_name, None)
        except (ImportError, AttributeError) as exc:
            logger.warning("handler_resolution_failed ref=%s error=%s", handler_ref, exc)
            return None

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Total number of registered hook instances across all event types."""
        return sum(len(hooks) for hooks in self._hooks.values())

    def event_types(self) -> list[str]:
        """Return event types that have at least one hook registered."""
        return [et for et, hooks in self._hooks.items() if hooks]

    def stats(self) -> dict[str, Any]:
        """Return aggregate statistics about registered hooks."""
        total = self.count()
        by_event: dict[str, int] = {}
        for et, hooks in self._hooks.items():
            if hooks:
                by_event[et] = len(hooks)
        return {
            "total_hooks": total,
            "total_definitions": len(self._definitions),
            "by_event_type": by_event,
            "event_types_active": len(by_event),
        }
