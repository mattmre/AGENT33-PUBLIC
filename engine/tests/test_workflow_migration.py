"""Tests for CA-030 Workflow Migration Tooling.

Covers: multi-hop BFS path finding, unreachable versions, downgrade with
missing downgrade_fn, bidirectional upgrade/downgrade round-trip,
same-version no-op, and validate_migration().
"""

from __future__ import annotations

from typing import Any

import pytest

from agent33.workflows.migration import WorkflowMigration


def _add_field(d: dict[str, Any]) -> dict[str, Any]:
    """v1->v2: add a 'description' field."""
    return {**d, "description": d.get("description", "default-desc")}


def _remove_field(d: dict[str, Any]) -> dict[str, Any]:
    """v2->v1 downgrade: remove 'description'."""
    out = dict(d)
    out.pop("description", None)
    return out


def _rename_key(d: dict[str, Any]) -> dict[str, Any]:
    """v2->v3: rename 'steps' to 'stages'."""
    out = dict(d)
    if "steps" in out:
        out["stages"] = out.pop("steps")
    return out


def _unrename_key(d: dict[str, Any]) -> dict[str, Any]:
    """v3->v2 downgrade: rename 'stages' back to 'steps'."""
    out = dict(d)
    if "stages" in out:
        out["steps"] = out.pop("stages")
    return out


def _add_metadata(d: dict[str, Any]) -> dict[str, Any]:
    """v3->v4: add metadata block."""
    return {**d, "metadata": {"migrated": True}}


def _remove_metadata(d: dict[str, Any]) -> dict[str, Any]:
    """v4->v3 downgrade: remove metadata."""
    out = dict(d)
    out.pop("metadata", None)
    return out


@pytest.fixture()
def migration() -> WorkflowMigration:
    """A migration registry with a 4-version chain: v1 -> v2 -> v3 -> v4."""
    m = WorkflowMigration()
    m.register("1.0", "2.0", upgrade_fn=_add_field, downgrade_fn=_remove_field)
    m.register("2.0", "3.0", upgrade_fn=_rename_key, downgrade_fn=_unrename_key)
    m.register("3.0", "4.0", upgrade_fn=_add_metadata, downgrade_fn=_remove_metadata)
    return m


class TestMultiHopUpgrade:
    """BFS migration path with 3+ version hops."""

    def test_upgrade_v1_to_v4_applies_all_transforms(self, migration: WorkflowMigration) -> None:
        """Upgrade from v1 to v4 should apply all three migration steps
        in order: add description, rename steps->stages, add metadata."""
        definition: dict[str, Any] = {
            "version": "1.0",
            "name": "workflow-a",
            "steps": ["s1", "s2"],
        }

        result = migration.upgrade(definition, "1.0", "4.0")

        # v2 transform: description added
        assert result["description"] == "default-desc"
        # v3 transform: 'steps' renamed to 'stages'
        assert "stages" in result
        assert "steps" not in result
        assert result["stages"] == ["s1", "s2"]
        # v4 transform: metadata added
        assert result["metadata"] == {"migrated": True}
        # final version stamp
        assert result["version"] == "4.0"
        # original field preserved
        assert result["name"] == "workflow-a"

    def test_upgrade_v1_to_v3_skips_v4_transform(self, migration: WorkflowMigration) -> None:
        """Upgrading only to v3 must NOT apply the v4 metadata transform."""
        definition: dict[str, Any] = {
            "version": "1.0",
            "name": "wf",
            "steps": ["a"],
        }

        result = migration.upgrade(definition, "1.0", "3.0")

        assert result["version"] == "3.0"
        assert "stages" in result
        assert "metadata" not in result


class TestFindPathNoRoute:
    """_find_path raises ValueError when no migration path exists."""

    def test_find_path_raises_for_unreachable_version(self, migration: WorkflowMigration) -> None:
        """Requesting migration to an unregistered version must raise."""
        with pytest.raises(ValueError, match="No migration path from 1.0 to 9.9"):
            migration._find_path("1.0", "9.9")

    def test_upgrade_raises_for_unreachable_version(self, migration: WorkflowMigration) -> None:
        """upgrade() surfaces the ValueError from _find_path."""
        with pytest.raises(ValueError, match="No migration path"):
            migration.upgrade({"version": "1.0"}, "1.0", "9.9")


class TestDowngradeMissingFn:
    """Downgrade fails when a step lacks a downgrade_fn."""

    def test_downgrade_raises_when_downgrade_fn_is_none(self) -> None:
        """If any step in the downgrade path has downgrade_fn=None,
        a ValueError must be raised naming the offending step."""
        m = WorkflowMigration()
        m.register("1.0", "2.0", upgrade_fn=_add_field, downgrade_fn=_remove_field)
        # Register v2->v3 WITHOUT a downgrade function
        m.register("2.0", "3.0", upgrade_fn=_rename_key, downgrade_fn=None)

        with pytest.raises(ValueError, match="No downgrade function for 2.0 -> 3.0"):
            m.downgrade({"version": "3.0"}, "3.0", "1.0")


class TestBidirectionalRoundTrip:
    """Upgrade then downgrade returns the original definition."""

    def test_upgrade_then_downgrade_is_identity(self, migration: WorkflowMigration) -> None:
        """Upgrading v1->v4 then downgrading v4->v1 must recover the
        original definition (except the version field, which tracks
        current version)."""
        original: dict[str, Any] = {
            "version": "1.0",
            "name": "roundtrip-wf",
            "steps": ["x", "y", "z"],
        }

        upgraded = migration.upgrade(dict(original), "1.0", "4.0")
        assert upgraded["version"] == "4.0"

        downgraded = migration.downgrade(upgraded, "4.0", "1.0")
        assert downgraded["version"] == "1.0"
        assert downgraded["name"] == "roundtrip-wf"
        assert downgraded["steps"] == ["x", "y", "z"]
        # Fields added by upgrade should be removed by downgrade
        assert "stages" not in downgraded
        assert "metadata" not in downgraded
        assert "description" not in downgraded


class TestSameVersionNoop:
    """Migrating to the same version is a no-op."""

    def test_upgrade_same_version_returns_copy(self, migration: WorkflowMigration) -> None:
        """upgrade(v, v) must return a copy without applying any transforms."""
        definition: dict[str, Any] = {
            "version": "2.0",
            "name": "static",
            "steps": [1],
        }

        result = migration.upgrade(definition, "2.0", "2.0")

        assert result == definition
        # Must be a copy, not the same object
        assert result is not definition

    def test_downgrade_same_version_returns_copy(self, migration: WorkflowMigration) -> None:
        """downgrade(v, v) must also be a no-op copy."""
        definition: dict[str, Any] = {"version": "3.0", "data": "abc"}

        result = migration.downgrade(definition, "3.0", "3.0")

        assert result == definition
        assert result is not definition


class TestValidateMigration:
    """validate_migration returns correct reachability answers."""

    def test_validate_returns_true_for_reachable_path(self, migration: WorkflowMigration) -> None:
        assert migration.validate_migration("1.0", "4.0") is True

    def test_validate_returns_false_for_unreachable_path(
        self, migration: WorkflowMigration
    ) -> None:
        assert migration.validate_migration("1.0", "9.9") is False

    def test_validate_returns_true_for_same_version(self, migration: WorkflowMigration) -> None:
        assert migration.validate_migration("2.0", "2.0") is True

    def test_validate_returns_false_for_reverse_without_reverse_edges(self) -> None:
        """validate_migration uses _find_path which builds its graph from
        registered (from, to) pairs. Without explicit reverse edges,
        v3->v1 should be unreachable even though downgrade() would work
        (downgrade finds the *forward* path and reverses it)."""
        m = WorkflowMigration()
        m.register("1.0", "2.0", upgrade_fn=_add_field)
        m.register("2.0", "3.0", upgrade_fn=_rename_key)
        # No reverse edges registered -- validate checks forward graph only
        assert m.validate_migration("3.0", "1.0") is False
