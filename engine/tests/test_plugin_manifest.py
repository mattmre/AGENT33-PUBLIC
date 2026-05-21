"""Tests for plugin manifest model validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent33.plugins.manifest import (
    PluginCapabilityType,
    PluginContributions,
    PluginDependency,
    PluginManifest,
    PluginPermission,
    PluginStatus,
)


class TestPluginManifestValidation:
    """Tests for PluginManifest field validation rules."""

    def test_valid_minimal_manifest(self) -> None:
        """Minimal valid manifest: name + version only."""
        m = PluginManifest(name="hello-world", version="1.0.0")
        assert m.name == "hello-world"
        assert m.version == "1.0.0"
        assert m.description == ""
        assert m.entry_point == "plugin:Plugin"
        assert m.status == PluginStatus.ACTIVE
        assert m.tags == []
        assert m.permissions == []
        assert m.dependencies == []

    def test_valid_full_manifest(self) -> None:
        """Full manifest with all fields populated."""
        m = PluginManifest(
            name="kubernetes-deploy",
            version="1.2.0",
            description="K8s deployment skills and tools",
            author="platform-team",
            license="Apache-2.0",
            homepage="https://example.com",
            repository="https://github.com/example/plugin",
            entry_point="k8s_plugin:KubernetesPlugin",
            contributions=PluginContributions(
                skills=["k8s-deploy", "k8s-troubleshoot"],
                tools=["KubectlTool"],
                hooks=["AuditHook"],
            ),
            permissions=[
                PluginPermission.SUBPROCESS,
                PluginPermission.NETWORK,
                PluginPermission.HOOK_REGISTER,
            ],
            dependencies=[
                PluginDependency(name="core-shell", version_constraint=">=1.0.0"),
            ],
            tags=["kubernetes", "infrastructure"],
            status=PluginStatus.ACTIVE,
        )
        assert m.name == "kubernetes-deploy"
        assert len(m.contributions.skills) == 2
        assert len(m.permissions) == 3
        assert m.dependencies[0].name == "core-shell"
        assert m.dependencies[0].version_constraint == ">=1.0.0"

    def test_name_must_be_slug_format(self) -> None:
        """Name must match ^[a-z][a-z0-9-]*$ pattern."""
        with pytest.raises(ValidationError) as exc_info:
            PluginManifest(name="Invalid_Name", version="1.0.0")
        assert "name" in str(exc_info.value)

    def test_name_cannot_start_with_number(self) -> None:
        """Name must start with a lowercase letter."""
        with pytest.raises(ValidationError):
            PluginManifest(name="1plugin", version="1.0.0")

    def test_name_cannot_be_empty(self) -> None:
        """Name must have at least 1 character."""
        with pytest.raises(ValidationError):
            PluginManifest(name="", version="1.0.0")

    def test_name_max_length(self) -> None:
        """Name cannot exceed 64 characters."""
        long_name = "a" * 65
        with pytest.raises(ValidationError):
            PluginManifest(name=long_name, version="1.0.0")

    def test_version_must_be_semver(self) -> None:
        """Version must match X.Y.Z format."""
        with pytest.raises(ValidationError) as exc_info:
            PluginManifest(name="test", version="1.0")
        assert "version" in str(exc_info.value)

    def test_version_invalid_alpha(self) -> None:
        """Version must not contain alpha characters."""
        with pytest.raises(ValidationError):
            PluginManifest(name="test", version="1.0.0-beta")

    def test_description_max_length(self) -> None:
        """Description cannot exceed 500 characters."""
        long_desc = "x" * 501
        with pytest.raises(ValidationError):
            PluginManifest(name="test", version="1.0.0", description=long_desc)

    def test_default_contributions_are_empty(self) -> None:
        """Contributions default to empty lists."""
        m = PluginManifest(name="test", version="1.0.0")
        assert m.contributions.skills == []
        assert m.contributions.tools == []
        assert m.contributions.agents == []
        assert m.contributions.hooks == []

    def test_dependency_default_constraint_is_wildcard(self) -> None:
        """Dependency version_constraint defaults to '*'."""
        dep = PluginDependency(name="other-plugin")
        assert dep.version_constraint == "*"
        assert dep.optional is False

    def test_optional_dependency(self) -> None:
        """Optional dependencies are allowed."""
        dep = PluginDependency(name="optional-plugin", optional=True)
        assert dep.optional is True

    def test_schema_version_default(self) -> None:
        """Schema version defaults to '1'."""
        m = PluginManifest(name="test", version="1.0.0")
        assert m.schema_version == "1"


class TestPluginPermissionEnum:
    """Tests for PluginPermission enum values."""

    def test_all_permission_values(self) -> None:
        """All expected permission values exist."""
        expected = {
            "file:read",
            "file:write",
            "network",
            "database:read",
            "database:write",
            "subprocess",
            "secrets:read",
            "tool:execute",
            "agent:invoke",
            "hook:register",
            "config:read",
            "config:write",
        }
        actual = {p.value for p in PluginPermission}
        assert actual == expected

    def test_permission_string_value(self) -> None:
        """PluginPermission is a StrEnum with colon-separated values."""
        assert PluginPermission.FILE_READ == "file:read"
        assert PluginPermission.HOOK_REGISTER == "hook:register"


class TestPluginStatusEnum:
    """Tests for PluginStatus enum values."""

    def test_all_status_values(self) -> None:
        """All lifecycle statuses exist."""
        expected = {"active", "deprecated", "experimental"}
        actual = {s.value for s in PluginStatus}
        assert actual == expected


class TestPluginCapabilityType:
    """Tests for PluginCapabilityType enum."""

    def test_all_capability_types(self) -> None:
        expected = {"skills", "tools", "agents", "hooks", "config"}
        actual = {c.value for c in PluginCapabilityType}
        assert actual == expected
