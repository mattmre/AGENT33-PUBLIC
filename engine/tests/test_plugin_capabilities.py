"""Tests for capability grant evaluator."""

from __future__ import annotations

import pytest

from agent33.plugins.capabilities import CapabilityGrant


class TestCapabilityGrantBasics:
    """Tests for CapabilityGrant initialization and permission checking."""

    def test_default_dev_mode_grants_all_requested(self) -> None:
        """In dev mode (no admin/tenant grants), all requested permissions are granted."""
        grant = CapabilityGrant(
            manifest_permissions=["file:read", "network", "config:read"],
        )
        assert grant.check("file:read") is True
        assert grant.check("network") is True
        assert grant.check("config:read") is True
        assert grant.effective_permissions == frozenset({"file:read", "network", "config:read"})

    def test_admin_restricts_permissions(self) -> None:
        """Admin grants only a subset of requested permissions."""
        grant = CapabilityGrant(
            manifest_permissions=["file:read", "network", "subprocess"],
            admin_grants={"file:read", "network"},
        )
        assert grant.check("file:read") is True
        assert grant.check("network") is True
        assert grant.check("subprocess") is False
        assert grant.effective_permissions == frozenset({"file:read", "network"})

    def test_tenant_restricts_permissions(self) -> None:
        """Tenant grants can further restrict beyond admin grants."""
        grant = CapabilityGrant(
            manifest_permissions=["file:read", "network"],
            admin_grants={"file:read", "network"},
            tenant_grants={"file:read"},
        )
        assert grant.check("file:read") is True
        assert grant.check("network") is False

    def test_effective_is_intersection_of_all_three(self) -> None:
        """Effective = requested AND admin AND tenant."""
        grant = CapabilityGrant(
            manifest_permissions=["file:read", "network", "subprocess"],
            admin_grants={"file:read", "network", "config:read"},  # config:read not requested
            tenant_grants={"file:read", "subprocess"},
        )
        # file:read is in all three
        # network is in requested+admin but not tenant
        # subprocess is in requested+tenant but not admin
        assert grant.effective_permissions == frozenset({"file:read"})

    def test_unrequested_permissions_never_granted(self) -> None:
        """Even if admin grants extra, only requested permissions can be effective."""
        grant = CapabilityGrant(
            manifest_permissions=["file:read"],
            admin_grants={"file:read", "network", "subprocess"},
        )
        assert grant.check("file:read") is True
        assert grant.check("network") is False
        assert grant.check("subprocess") is False

    def test_empty_manifest_permissions(self) -> None:
        """Plugin with no permissions gets nothing."""
        grant = CapabilityGrant(manifest_permissions=[])
        assert grant.effective_permissions == frozenset()
        assert grant.check("file:read") is False


class TestCapabilityGrantRequire:
    """Tests for CapabilityGrant.require() method."""

    def test_require_granted_permission_succeeds(self) -> None:
        grant = CapabilityGrant(manifest_permissions=["file:read"])
        # Should not raise
        grant.require("file:read")

    def test_require_denied_permission_raises(self) -> None:
        grant = CapabilityGrant(
            manifest_permissions=["file:read"],
            admin_grants=set(),
        )
        with pytest.raises(PermissionError, match="file:read"):
            grant.require("file:read")

    def test_require_unrequested_permission_raises(self) -> None:
        grant = CapabilityGrant(manifest_permissions=["file:read"])
        with pytest.raises(PermissionError, match="network"):
            grant.require("network")


class TestCapabilityGrantDenied:
    """Tests for denied_permissions() method."""

    def test_denied_when_admin_restricts(self) -> None:
        grant = CapabilityGrant(
            manifest_permissions=["file:read", "network", "subprocess"],
            admin_grants={"file:read"},
        )
        denied = grant.denied_permissions()
        assert denied == frozenset({"network", "subprocess"})

    def test_no_denied_when_all_granted(self) -> None:
        grant = CapabilityGrant(
            manifest_permissions=["file:read", "network"],
        )
        assert grant.denied_permissions() == frozenset()

    def test_requested_permissions_property(self) -> None:
        grant = CapabilityGrant(
            manifest_permissions=["file:read", "network"],
        )
        assert grant.requested_permissions == frozenset({"file:read", "network"})
