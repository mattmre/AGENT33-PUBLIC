"""Tests for scoped registry proxies and settings proxy."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent33.plugins.capabilities import CapabilityGrant
from agent33.plugins.scoped import (
    ReadOnlySettingsProxy,
    ScopedSkillRegistry,
    ScopedToolRegistry,
)


class TestScopedSkillRegistry:
    """Tests for ScopedSkillRegistry proxy."""

    def test_get_delegates_to_underlying(self) -> None:
        mock_registry = MagicMock()
        mock_registry.get.return_value = "skill-result"
        grant = CapabilityGrant(manifest_permissions=[])
        proxy = ScopedSkillRegistry(mock_registry, grant)

        result = proxy.get("my-skill")
        assert result == "skill-result"
        mock_registry.get.assert_called_once_with("my-skill")

    def test_search_delegates_to_underlying(self) -> None:
        mock_registry = MagicMock()
        mock_registry.search.return_value = ["skill-a", "skill-b"]
        grant = CapabilityGrant(manifest_permissions=[])
        proxy = ScopedSkillRegistry(mock_registry, grant)

        result = proxy.search("test")
        assert result == ["skill-a", "skill-b"]

    def test_list_all_delegates(self) -> None:
        mock_registry = MagicMock()
        mock_registry.list_all.return_value = ["s1", "s2"]
        grant = CapabilityGrant(manifest_permissions=[])
        proxy = ScopedSkillRegistry(mock_registry, grant)

        assert proxy.list_all() == ["s1", "s2"]

    def test_register_delegates(self) -> None:
        mock_registry = MagicMock()
        grant = CapabilityGrant(manifest_permissions=[])
        proxy = ScopedSkillRegistry(mock_registry, grant)

        proxy.register("new-skill")
        mock_registry.register.assert_called_once_with("new-skill")

    def test_remove_delegates(self) -> None:
        mock_registry = MagicMock()
        mock_registry.remove.return_value = True
        grant = CapabilityGrant(manifest_permissions=[])
        proxy = ScopedSkillRegistry(mock_registry, grant)

        result = proxy.remove("old-skill")
        assert result is True
        mock_registry.remove.assert_called_once_with("old-skill")

    def test_count_delegates(self) -> None:
        mock_registry = MagicMock()
        mock_registry.count = 5
        grant = CapabilityGrant(manifest_permissions=[])
        proxy = ScopedSkillRegistry(mock_registry, grant)

        assert proxy.count == 5


class TestScopedToolRegistry:
    """Tests for ScopedToolRegistry proxy."""

    def test_get_delegates(self) -> None:
        mock_registry = MagicMock()
        mock_registry.get.return_value = "tool-obj"
        grant = CapabilityGrant(manifest_permissions=[])
        proxy = ScopedToolRegistry(mock_registry, grant)

        assert proxy.get("my-tool") == "tool-obj"

    def test_list_all_delegates(self) -> None:
        mock_registry = MagicMock()
        mock_registry.list_all.return_value = ["t1", "t2"]
        grant = CapabilityGrant(manifest_permissions=[])
        proxy = ScopedToolRegistry(mock_registry, grant)

        assert proxy.list_all() == ["t1", "t2"]

    def test_register_delegates(self) -> None:
        mock_registry = MagicMock()
        grant = CapabilityGrant(manifest_permissions=[])
        proxy = ScopedToolRegistry(mock_registry, grant)

        proxy.register("new-tool")
        mock_registry.register.assert_called_once_with("new-tool")

    async def test_validated_execute_with_permission(self) -> None:
        from unittest.mock import AsyncMock

        mock_registry = MagicMock()
        mock_registry.validated_execute = AsyncMock(return_value="result")
        grant = CapabilityGrant(manifest_permissions=["tool:execute"])
        proxy = ScopedToolRegistry(mock_registry, grant)

        result = await proxy.validated_execute("my-tool", {"key": "val"}, "ctx")
        assert result == "result"

    async def test_validated_execute_without_permission_raises(self) -> None:
        mock_registry = MagicMock()
        grant = CapabilityGrant(
            manifest_permissions=["file:read"],  # No tool:execute
            admin_grants={"file:read"},
        )
        proxy = ScopedToolRegistry(mock_registry, grant)

        with pytest.raises(PermissionError, match="tool:execute"):
            await proxy.validated_execute("my-tool", {}, "ctx")


class TestReadOnlySettingsProxy:
    """Tests for ReadOnlySettingsProxy."""

    def test_read_safe_field(self) -> None:
        mock_settings = MagicMock()
        mock_settings.environment = "development"
        proxy = ReadOnlySettingsProxy(mock_settings)

        assert proxy.get("environment") == "development"

    def test_read_another_safe_field(self) -> None:
        mock_settings = MagicMock()
        mock_settings.api_port = 8000
        proxy = ReadOnlySettingsProxy(mock_settings)

        assert proxy.get("api_port") == 8000

    def test_read_unsafe_field_raises(self) -> None:
        mock_settings = MagicMock()
        proxy = ReadOnlySettingsProxy(mock_settings)

        with pytest.raises(PermissionError, match="jwt_secret"):
            proxy.get("jwt_secret")

    def test_read_database_url_raises(self) -> None:
        mock_settings = MagicMock()
        proxy = ReadOnlySettingsProxy(mock_settings)

        with pytest.raises(PermissionError, match="database_url"):
            proxy.get("database_url")

    def test_safe_fields_property(self) -> None:
        proxy = ReadOnlySettingsProxy(MagicMock())
        assert "environment" in proxy.safe_fields
        assert "api_port" in proxy.safe_fields
        assert "jwt_secret" not in proxy.safe_fields
        assert "database_url" not in proxy.safe_fields
