"""Capability grant evaluator for plugin permission sandboxing."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class CapabilityGrant:
    """Evaluates and enforces plugin capability grants.

    A plugin receives the intersection of:
    - What it declares in its manifest (permissions)
    - What the admin has approved (admin_grants)
    - What the tenant has approved (tenant_grants)

    Anything not in all three sets is denied.
    """

    def __init__(
        self,
        manifest_permissions: list[str],
        admin_grants: set[str] | None = None,
        tenant_grants: set[str] | None = None,
    ) -> None:
        self._requested = set(manifest_permissions)

        # Admin grants default to all-requested (trust manifest in dev mode)
        self._admin_grants = (
            admin_grants if admin_grants is not None else set(manifest_permissions)
        )

        # Tenant grants default to admin grants
        self._tenant_grants = tenant_grants if tenant_grants is not None else self._admin_grants

        # Effective = requested AND admin AND tenant
        self._effective = self._requested & self._admin_grants & self._tenant_grants

    @property
    def effective_permissions(self) -> frozenset[str]:
        """The set of permissions actually granted to the plugin."""
        return frozenset(self._effective)

    @property
    def requested_permissions(self) -> frozenset[str]:
        """The set of permissions requested by the plugin manifest."""
        return frozenset(self._requested)

    def check(self, permission: str) -> bool:
        """Return True if the permission is granted."""
        return permission in self._effective

    def require(self, permission: str) -> None:
        """Raise PermissionError if the permission is not granted."""
        if permission not in self._effective:
            raise PermissionError(
                f"Permission '{permission}' not granted. "
                f"Requested: {sorted(self._requested)}, "
                f"Effective: {sorted(self._effective)}"
            )

    def denied_permissions(self) -> frozenset[str]:
        """Return permissions that were requested but not granted."""
        return frozenset(self._requested - self._effective)
