"""Tests for semver constraint parsing, version comparison, and dependency resolution.

Tests cover: Version parsing, constraint syntax (^, ~, >=, <, exact, *),
range checking, DependencyResolver happy paths and conflict detection,
lock file generation and parsing.
"""

from __future__ import annotations

import pytest

from agent33.packs.version import (
    DependencyResolver,
    Version,
    VersionConstraint,
    generate_lock_content,
    parse_lock_content,
)


class TestVersion:
    """Test the Version dataclass."""

    def test_parse_valid(self) -> None:
        v = Version.parse("1.2.3")
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 3

    def test_parse_zero_version(self) -> None:
        v = Version.parse("0.0.0")
        assert v == Version(0, 0, 0)

    def test_parse_leading_whitespace(self) -> None:
        v = Version.parse("  1.2.3  ")
        assert v == Version(1, 2, 3)

    def test_parse_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="Invalid semver"):
            Version.parse("1.2")

    def test_parse_invalid_prefix(self) -> None:
        with pytest.raises(ValueError, match="Invalid semver"):
            Version.parse("v1.2.3")

    def test_ordering(self) -> None:
        assert Version(1, 0, 0) < Version(2, 0, 0)
        assert Version(1, 0, 0) < Version(1, 1, 0)
        assert Version(1, 1, 0) < Version(1, 1, 1)
        assert Version(1, 2, 3) == Version(1, 2, 3)
        assert Version(2, 0, 0) > Version(1, 99, 99)

    def test_str(self) -> None:
        assert str(Version(1, 2, 3)) == "1.2.3"


class TestVersionConstraint:
    """Test constraint parsing and satisfaction."""

    def test_caret_constraint(self) -> None:
        """^1.2.3 means >=1.2.3, <2.0.0"""
        c = VersionConstraint.parse("^1.2.3")
        assert c.satisfies(Version(1, 2, 3))
        assert c.satisfies(Version(1, 9, 9))
        assert not c.satisfies(Version(2, 0, 0))
        assert not c.satisfies(Version(1, 2, 2))

    def test_caret_zero_major(self) -> None:
        """^0.1.0 means >=0.1.0, <1.0.0"""
        c = VersionConstraint.parse("^0.1.0")
        assert c.satisfies(Version(0, 1, 0))
        assert c.satisfies(Version(0, 99, 99))
        assert not c.satisfies(Version(1, 0, 0))

    def test_tilde_constraint(self) -> None:
        """~1.2.3 means >=1.2.3, <1.3.0"""
        c = VersionConstraint.parse("~1.2.3")
        assert c.satisfies(Version(1, 2, 3))
        assert c.satisfies(Version(1, 2, 9))
        assert not c.satisfies(Version(1, 3, 0))
        assert not c.satisfies(Version(1, 2, 2))

    def test_gte_constraint(self) -> None:
        c = VersionConstraint.parse(">=1.0.0")
        assert c.satisfies(Version(1, 0, 0))
        assert c.satisfies(Version(2, 0, 0))
        assert not c.satisfies(Version(0, 9, 9))

    def test_lt_constraint(self) -> None:
        c = VersionConstraint.parse("<2.0.0")
        assert c.satisfies(Version(1, 9, 9))
        assert not c.satisfies(Version(2, 0, 0))
        assert not c.satisfies(Version(3, 0, 0))

    def test_gt_constraint(self) -> None:
        c = VersionConstraint.parse(">1.0.0")
        assert not c.satisfies(Version(1, 0, 0))
        assert c.satisfies(Version(1, 0, 1))

    def test_lte_constraint(self) -> None:
        c = VersionConstraint.parse("<=2.0.0")
        assert c.satisfies(Version(2, 0, 0))
        assert c.satisfies(Version(1, 0, 0))
        assert not c.satisfies(Version(2, 0, 1))

    def test_exact_with_equals(self) -> None:
        c = VersionConstraint.parse("=1.2.3")
        assert c.satisfies(Version(1, 2, 3))
        assert not c.satisfies(Version(1, 2, 4))

    def test_exact_without_operator(self) -> None:
        c = VersionConstraint.parse("1.2.3")
        assert c.satisfies(Version(1, 2, 3))
        assert not c.satisfies(Version(1, 2, 4))

    def test_wildcard(self) -> None:
        c = VersionConstraint.parse("*")
        assert c.satisfies(Version(0, 0, 0))
        assert c.satisfies(Version(99, 99, 99))

    def test_range_with_comma(self) -> None:
        """>=1.0.0, <2.0.0 (AND combination)"""
        c = VersionConstraint.parse(">=1.0.0, <2.0.0")
        assert c.satisfies(Version(1, 0, 0))
        assert c.satisfies(Version(1, 9, 9))
        assert not c.satisfies(Version(0, 9, 9))
        assert not c.satisfies(Version(2, 0, 0))

    def test_raw_preserved(self) -> None:
        c = VersionConstraint.parse("^1.0.0")
        assert c.raw == "^1.0.0"


class TestDependencyResolver:
    """Test the greedy backtracking dependency resolver."""

    def test_no_dependencies(self) -> None:
        resolver = DependencyResolver()
        result = resolver.resolve([])
        assert result.success
        assert result.resolved == {}

    def test_single_dependency_resolved(self) -> None:
        resolver = DependencyResolver({"utils": ["1.0.0", "1.1.0", "2.0.0"]})
        result = resolver.resolve([("utils", "^1.0.0")])
        assert result.success
        assert result.resolved is not None
        assert result.resolved["utils"] == "1.1.0"  # highest matching

    def test_exact_version_match(self) -> None:
        resolver = DependencyResolver({"utils": ["1.0.0", "1.1.0"]})
        result = resolver.resolve([("utils", "1.0.0")])
        assert result.success
        assert result.resolved is not None
        assert result.resolved["utils"] == "1.0.0"

    def test_multiple_dependencies(self) -> None:
        resolver = DependencyResolver(
            {
                "utils": ["1.0.0", "1.1.0"],
                "helpers": ["2.0.0", "2.1.0"],
            }
        )
        result = resolver.resolve(
            [
                ("utils", "^1.0.0"),
                ("helpers", "^2.0.0"),
            ]
        )
        assert result.success
        assert result.resolved is not None
        assert result.resolved["utils"] == "1.1.0"
        assert result.resolved["helpers"] == "2.1.0"

    def test_missing_pack_conflict(self) -> None:
        resolver = DependencyResolver({"utils": ["1.0.0"]})
        result = resolver.resolve([("nonexistent", "^1.0.0")])
        assert not result.success
        assert len(result.conflicts) == 1
        assert result.conflicts[0].package == "nonexistent"
        assert "not found" in result.conflicts[0].reason

    def test_no_version_satisfies_conflict(self) -> None:
        resolver = DependencyResolver({"utils": ["1.0.0", "1.1.0"]})
        result = resolver.resolve([("utils", "^2.0.0")])
        assert not result.success
        assert len(result.conflicts) == 1
        assert "No version" in result.conflicts[0].reason

    def test_version_incompatibility_conflict(self) -> None:
        """Two requirements for the same pack with incompatible constraints."""
        resolver = DependencyResolver({"utils": ["1.0.0", "2.0.0"]})
        result = resolver.resolve(
            [
                ("utils", "^1.0.0"),
                ("utils", "^2.0.0"),
            ]
        )
        # First resolves to 1.0.0, second wants ^2.0.0 -> conflict
        assert not result.success
        assert any(
            "conflict" in c.reason.lower() or "Version conflict" in c.reason
            for c in result.conflicts
        )

    def test_add_available_after_init(self) -> None:
        resolver = DependencyResolver()
        resolver.add_available("utils", "1.0.0")
        resolver.add_available("utils", "1.1.0")
        result = resolver.resolve([("utils", "^1.0.0")])
        assert result.success
        assert result.resolved is not None
        assert result.resolved["utils"] == "1.1.0"

    def test_graph_populated(self) -> None:
        resolver = DependencyResolver({"utils": ["1.0.0"]})
        result = resolver.resolve([("utils", "^1.0.0")])
        assert result.success
        assert "root" in result.graph
        assert "utils" in result.graph["root"]


class TestLockFile:
    """Test lock file generation and parsing."""

    def test_generate_lock_content(self) -> None:
        content = generate_lock_content(
            resolved={"utils": "1.0.0", "helpers": "2.1.0"},
            engine_version="0.1.0",
            sources={"utils": "local", "helpers": "marketplace"},
            constraints={"utils": "^1.0.0", "helpers": "^2.0.0"},
        )
        assert content["lock_version"] == "1"
        assert content["engine_version"] == "0.1.0"
        assert "resolved_at" in content
        assert "packages" in content
        assert content["packages"]["utils"]["version"] == "1.0.0"
        assert content["packages"]["utils"]["source"] == "local"
        assert content["packages"]["helpers"]["source"] == "marketplace"
        assert content["packages"]["utils"]["resolved_from"] == "^1.0.0"

    def test_generate_lock_with_checksums(self) -> None:
        content = generate_lock_content(
            resolved={"utils": "1.0.0"},
            checksums={"utils": "sha256:abc123"},
        )
        assert content["packages"]["utils"]["checksum"] == "sha256:abc123"

    def test_parse_lock_content(self) -> None:
        data = {
            "lock_version": "1",
            "packages": {
                "utils": {"version": "1.0.0", "source": "local"},
                "helpers": {"version": "2.1.0", "source": "marketplace"},
            },
        }
        result = parse_lock_content(data)
        assert result["utils"] == "1.0.0"
        assert result["helpers"] == "2.1.0"

    def test_parse_lock_empty_packages(self) -> None:
        result = parse_lock_content({"lock_version": "1", "packages": {}})
        assert result == {}
