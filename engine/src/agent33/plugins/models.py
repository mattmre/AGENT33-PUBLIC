"""Plugin internal models: state machine, scope, and tracking types."""

from __future__ import annotations

from enum import StrEnum


class PluginState(StrEnum):
    """Lifecycle state of a loaded plugin.

    State machine:
        DISCOVERED -> LOADING -> LOADED -> ENABLING -> ACTIVE
                                                   |-> DISABLED -> ENABLING (re-enable)
                                                                |-> UNLOADING -> UNLOADED
        Any state may transition to ERROR on failure.
    """

    DISCOVERED = "discovered"
    LOADING = "loading"
    LOADED = "loaded"
    ENABLING = "enabling"
    ACTIVE = "active"
    DISABLED = "disabled"
    UNLOADING = "unloading"
    UNLOADED = "unloaded"
    ERROR = "error"


class PluginScope(StrEnum):
    """Three-tier scoping for multi-tenancy.

    - SYSTEM: Available to all tenants, loaded once.
    - SHARED: Available to multiple tenants, single instance.
    - TENANT: Private to one tenant, isolated instance.
    """

    SYSTEM = "system"
    SHARED = "shared"
    TENANT = "tenant"
