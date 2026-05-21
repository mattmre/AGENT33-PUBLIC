"""Validate Alembic migration chain integrity.

These tests verify that:
1. The Alembic configuration is valid
2. All migration files are well-formed
3. The migration chain has no gaps or branches
4. The head revision is deterministic (no multi-head state)

Tests parse migration files directly without importing Alembic or
requiring a database connection, making them safe for CI.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_ENGINE_DIR = Path(__file__).resolve().parent.parent
_ALEMBIC_DIR = _ENGINE_DIR / "alembic"
_VERSIONS_DIR = _ALEMBIC_DIR / "versions"
_ALEMBIC_INI = _ENGINE_DIR / "alembic.ini"

# Matches both plain assignment and type-annotated assignment:
#   revision = "001"
#   revision: str = "001"
#   revision: str | None = None
_REV_PATTERN = re.compile(
    r"^revision(?:\s*:\s*\w[\w\s|]*?)?\s*=\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
_DOWN_REV_PATTERN = re.compile(
    r"^down_revision(?:\s*:\s*\w[\w\s|]*?)?\s*=\s*['\"]([^'\"]*)['\"]",
    re.MULTILINE,
)
_DOWN_REV_NONE_PATTERN = re.compile(
    r"^down_revision(?:\s*:\s*\w[\w\s|]*?)?\s*=\s*None",
    re.MULTILINE,
)


def _migration_files() -> list[Path]:
    """Return all .py migration files, excluding __pycache__ artifacts."""
    if not _VERSIONS_DIR.is_dir():
        return []
    return [f for f in sorted(_VERSIONS_DIR.glob("*.py")) if f.stem != "__init__"]


class TestAlembicConfigExists:
    """Verify the Alembic configuration files are present and well-formed."""

    def test_alembic_ini_exists(self) -> None:
        assert _ALEMBIC_INI.exists(), f"alembic.ini not found at {_ALEMBIC_INI}"

    def test_alembic_directory_exists(self) -> None:
        assert _ALEMBIC_DIR.is_dir(), f"alembic/ directory not found at {_ALEMBIC_DIR}"

    def test_env_py_exists(self) -> None:
        env_py = _ALEMBIC_DIR / "env.py"
        assert env_py.exists(), f"alembic/env.py not found at {env_py}"

    def test_versions_directory_exists(self) -> None:
        assert _VERSIONS_DIR.is_dir(), f"alembic/versions/ directory not found at {_VERSIONS_DIR}"

    def test_alembic_ini_has_script_location(self) -> None:
        content = _ALEMBIC_INI.read_text(encoding="utf-8")
        assert "script_location" in content, "alembic.ini missing 'script_location' directive"
        # Verify the script_location points to a real directory
        match = re.search(r"^script_location\s*=\s*(.+)$", content, re.MULTILINE)
        assert match is not None, "Could not parse script_location value"
        location = match.group(1).strip()
        resolved = _ENGINE_DIR / location
        assert resolved.is_dir(), (
            f"script_location '{location}' resolves to {resolved} which does not exist"
        )


class TestMigrationFilesValid:
    """Verify all migration files are syntactically valid Python."""

    def test_at_least_one_migration_exists(self) -> None:
        files = _migration_files()
        assert len(files) > 0, "No migration files found in alembic/versions/"

    def test_migration_files_parse_as_valid_python(self) -> None:
        for mf in _migration_files():
            source = mf.read_text(encoding="utf-8")
            try:
                ast.parse(source, filename=str(mf))
            except SyntaxError as exc:
                pytest.fail(f"Migration {mf.name} has a syntax error: {exc}")

    def test_migration_files_have_revision_id(self) -> None:
        """Every migration must declare a revision identifier."""
        for mf in _migration_files():
            content = mf.read_text(encoding="utf-8")
            match = _REV_PATTERN.search(content)
            assert match is not None, f"Migration {mf.name} is missing a 'revision' assignment"
            assert match.group(1).strip(), f"Migration {mf.name} has an empty revision identifier"

    def test_migration_files_have_down_revision(self) -> None:
        """Every migration must declare down_revision (can be None for root)."""
        for mf in _migration_files():
            content = mf.read_text(encoding="utf-8")
            has_string = _DOWN_REV_PATTERN.search(content) is not None
            has_none = _DOWN_REV_NONE_PATTERN.search(content) is not None
            assert has_string or has_none, (
                f"Migration {mf.name} is missing a 'down_revision' assignment"
            )

    def test_migration_files_have_upgrade_function(self) -> None:
        """Every migration must define an upgrade() function."""
        for mf in _migration_files():
            content = mf.read_text(encoding="utf-8")
            assert re.search(r"^def upgrade\(", content, re.MULTILINE), (
                f"Migration {mf.name} is missing an 'upgrade()' function"
            )

    def test_migration_files_have_downgrade_function(self) -> None:
        """Every migration must define a downgrade() function."""
        for mf in _migration_files():
            content = mf.read_text(encoding="utf-8")
            assert re.search(r"^def downgrade\(", content, re.MULTILINE), (
                f"Migration {mf.name} is missing a 'downgrade()' function"
            )


class TestMigrationChainIntegrity:
    """Verify the migration chain is linear with exactly one head."""

    @staticmethod
    def _parse_revisions() -> dict[str, str | None]:
        """Parse revision -> down_revision mapping from all migration files.

        Returns a dict mapping each revision ID to its down_revision
        (None for the root migration).
        """
        revisions: dict[str, str | None] = {}
        for mf in _migration_files():
            content = mf.read_text(encoding="utf-8")
            rev_match = _REV_PATTERN.search(content)
            if rev_match is None:
                continue

            rev = rev_match.group(1)
            down_match = _DOWN_REV_PATTERN.search(content)
            none_match = _DOWN_REV_NONE_PATTERN.search(content)

            if none_match:
                down = None
            elif down_match:
                down = down_match.group(1) or None
            else:
                down = None

            revisions[rev] = down
        return revisions

    def test_no_duplicate_revision_ids(self) -> None:
        """Each migration file must have a unique revision ID."""
        seen: dict[str, Path] = {}
        for mf in _migration_files():
            content = mf.read_text(encoding="utf-8")
            match = _REV_PATTERN.search(content)
            if match is None:
                continue
            rev = match.group(1)
            if rev in seen:
                pytest.fail(f"Duplicate revision '{rev}' found in {mf.name} and {seen[rev].name}")
            seen[rev] = mf

    def test_single_root_migration(self) -> None:
        """Exactly one migration should have down_revision = None."""
        revisions = self._parse_revisions()
        if not revisions:
            pytest.skip("No parseable migration revisions found")

        roots = [rev for rev, down in revisions.items() if down is None]
        assert len(roots) == 1, (
            f"Expected exactly 1 root migration (down_revision=None), found {len(roots)}: {roots}"
        )

    def test_single_head_revision(self) -> None:
        """The migration chain must have exactly one head (no branching).

        A 'head' is a revision that no other revision lists as its
        down_revision -- i.e., nothing comes after it.
        """
        revisions = self._parse_revisions()
        if not revisions:
            pytest.skip("No parseable migration revisions found")

        referenced_as_parent = {v for v in revisions.values() if v is not None}
        heads = [r for r in revisions if r not in referenced_as_parent]

        assert len(heads) == 1, (
            f"Migration chain has {len(heads)} heads (expected 1): {heads}. "
            "This indicates a branching migration that needs to be merged."
        )

    def test_chain_is_contiguous(self) -> None:
        """Every down_revision must point to an existing revision or None.

        This catches dangling references where a migration claims to
        depend on a revision that doesn't exist in the versions/ directory.
        """
        revisions = self._parse_revisions()
        if not revisions:
            pytest.skip("No parseable migration revisions found")

        all_rev_ids = set(revisions.keys())
        for rev, down in revisions.items():
            if down is not None and down not in all_rev_ids:
                pytest.fail(
                    f"Migration '{rev}' references down_revision '{down}' "
                    f"which does not exist. Known revisions: {sorted(all_rev_ids)}"
                )

    def test_chain_forms_linear_sequence(self) -> None:
        """Walk from root to head and verify the chain visits every revision.

        This confirms there are no orphaned migrations or disconnected
        sub-chains.
        """
        revisions = self._parse_revisions()
        if not revisions:
            pytest.skip("No parseable migration revisions found")

        # Build child map: down_revision -> revision
        children: dict[str | None, list[str]] = {}
        for rev, down in revisions.items():
            children.setdefault(down, []).append(rev)

        # Walk from root (down_revision=None)
        visited: list[str] = []
        current: str | None = None  # Start from the root's parent (None)
        while current in children or (current is None and None in children):
            next_revs = children.get(current, [])
            if not next_revs:
                break
            if len(next_revs) > 1:
                pytest.fail(
                    f"Branching detected at revision '{current}': multiple children {next_revs}"
                )
            visited.append(next_revs[0])
            current = next_revs[0]

        assert set(visited) == set(revisions.keys()), (
            f"Chain walk visited {len(visited)} revisions but {len(revisions)} "
            f"exist. Visited: {visited}, All: {sorted(revisions.keys())}. "
            "This indicates orphaned or disconnected migrations."
        )
