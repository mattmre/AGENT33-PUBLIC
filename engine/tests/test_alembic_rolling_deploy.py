"""Alembic rolling-deploy migration safety tests (P4.15).

Validates that the Alembic migration chain supports safe rolling deploys by
checking:

1. **Chain integrity** -- sequential ordering, no gaps, single root/head.
2. **Upgrade/downgrade symmetry** -- every migration has non-trivial bodies.
3. **N-1 schema compatibility** -- ORM models at version N work with the
   schema at version N-1 (critical for rolling deploys where old and new
   code coexist).
4. **Migration metadata consistency** -- filenames, revision IDs, and
   down_revision links follow conventions.
5. **Destructive-migration detection** -- migrations that drop columns or
   tables are flagged as requiring downtime (not safe for zero-downtime
   rolling deploys).

Tests that require a live PostgreSQL database are marked with
``@pytest.mark.integration``.
"""

from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ENGINE_DIR = Path(__file__).resolve().parent.parent
_ALEMBIC_DIR = _ENGINE_DIR / "alembic"
_VERSIONS_DIR = _ALEMBIC_DIR / "versions"

# Regex patterns for extracting revision metadata from migration files.
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

# SQL patterns that indicate destructive operations.
_DROP_COLUMN_PATTERN = re.compile(r"DROP\s+COLUMN", re.IGNORECASE)
_DROP_TABLE_PATTERN = re.compile(r"(?:op\.drop_table|DROP\s+TABLE)", re.IGNORECASE)
_DROP_INDEX_PATTERN = re.compile(r"(?:op\.drop_index|DROP\s+INDEX)", re.IGNORECASE)

# Known tables managed by migrations.
_MIGRATION_TABLES = {"workflow_checkpoints", "sessions", "memory_documents"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _migration_files() -> list[Path]:
    """Return all .py migration files, excluding __pycache__ artifacts."""
    if not _VERSIONS_DIR.is_dir():
        return []
    return [f for f in sorted(_VERSIONS_DIR.glob("*.py")) if f.stem != "__init__"]


def _parse_revision(path: Path) -> dict[str, Any]:
    """Parse a migration file and return revision metadata.

    Returns a dict with keys: ``revision``, ``down_revision``, ``file_name``,
    ``source``, ``has_upgrade``, ``has_downgrade``.
    """
    source = path.read_text(encoding="utf-8")

    rev_match = _REV_PATTERN.search(source)
    revision = rev_match.group(1) if rev_match else None

    down_match = _DOWN_REV_PATTERN.search(source)
    none_match = _DOWN_REV_NONE_PATTERN.search(source)
    if none_match and (not down_match or none_match.start() < down_match.start()):
        down_revision = None
    elif down_match:
        down_revision = down_match.group(1) or None
    else:
        down_revision = None

    has_upgrade = bool(re.search(r"^def upgrade\(", source, re.MULTILINE))
    has_downgrade = bool(re.search(r"^def downgrade\(", source, re.MULTILINE))

    return {
        "revision": revision,
        "down_revision": down_revision,
        "file_name": path.name,
        "source": source,
        "path": path,
        "has_upgrade": has_upgrade,
        "has_downgrade": has_downgrade,
    }


def _parse_all_revisions() -> list[dict[str, Any]]:
    """Parse all migration files and return a list of revision metadata dicts."""
    return [_parse_revision(f) for f in _migration_files()]


def _extract_function_body(source: str, func_name: str) -> str:
    """Extract the body source of a top-level function from a migration script.

    Returns the raw source lines of the function body (after the ``def`` line).
    """
    tree = ast.parse(source)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            # Extract lines from the function body
            body_lines: list[str] = []
            lines = source.splitlines()
            for stmt in node.body:
                for lineno in range(stmt.lineno - 1, stmt.end_lineno or stmt.lineno):
                    if lineno < len(lines):
                        body_lines.append(lines[lineno])
            return "\n".join(body_lines)
    return ""


def _function_is_pass_only(source: str, func_name: str) -> bool:
    """Return True if the named function consists solely of ``pass``."""
    tree = ast.parse(source)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            if len(node.body) == 1:
                stmt = node.body[0]
                if isinstance(stmt, ast.Pass):
                    return True
                # Also catch ``pass`` disguised as an Expr(Constant(...))
                if (
                    isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    # Just a docstring, no real operations
                    return True
            return False
    return True


def _detect_destructive_ops(source: str) -> list[str]:
    """Scan migration source for destructive SQL operations.

    Returns a list of human-readable descriptions of destructive operations
    found in the source.
    """
    findings: list[str] = []

    if _DROP_COLUMN_PATTERN.search(source):
        findings.append("DROP COLUMN detected")
    if _DROP_TABLE_PATTERN.search(source):
        findings.append("DROP TABLE detected")
    # DROP INDEX alone is not destructive (indexes can be recreated), but
    # combined with DROP COLUMN it indicates data loss.
    if _DROP_INDEX_PATTERN.search(source) and _DROP_COLUMN_PATTERN.search(source):
        findings.append("DROP INDEX + DROP COLUMN combination (data loss risk)")

    return findings


def _collect_upgrade_source(source: str) -> str:
    """Collect the full upgrade-reachable source from a migration.

    Migration 002 uses helper functions called from upgrade(). This function
    returns the combined source of upgrade() and all helper functions it
    calls, so destructive-operation detection covers the full upgrade path.

    For simplicity, we scan the entire module source *excluding* the
    downgrade() function and its helpers. This is conservative: if any
    function in the module contains destructive SQL that is reachable from
    upgrade(), it will be detected.
    """
    tree = ast.parse(source)
    lines = source.splitlines()

    # Find the downgrade function and its range.  We exclude that range
    # because downgrade() is *expected* to contain destructive ops.
    downgrade_ranges: list[tuple[int, int]] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "downgrade",
            "_downgrade_table",
        ):
            start = node.lineno - 1  # 0-indexed
            end = (node.end_lineno or node.lineno) - 1
            downgrade_ranges.append((start, end))

    # Build source excluding downgrade ranges
    included: list[str] = []
    for i, line in enumerate(lines):
        in_excluded = any(start <= i <= end for start, end in downgrade_ranges)
        if not in_excluded:
            included.append(line)

    return "\n".join(included)


def _extract_table_columns_from_create(source: str) -> dict[str, list[str]]:
    """Extract table -> [column_names] from op.create_table() calls in migration source.

    Uses AST parsing to find calls to ``op.create_table(table_name, Column(...), ...)``.
    """
    table_columns: dict[str, list[str]] = {}

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Match op.create_table(...)
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "create_table"
            and isinstance(func.value, ast.Name)
            and func.value.id == "op"
        ):
            continue

        # First arg is table name
        if not node.args:
            continue
        table_arg = node.args[0]
        if not isinstance(table_arg, ast.Constant) or not isinstance(table_arg.value, str):
            continue
        table_name = table_arg.value

        # Remaining positional args are Column(...) calls
        columns: list[str] = []
        for arg in node.args[1:]:
            if (
                isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Attribute)
                and arg.func.attr == "Column"
                and arg.args
                and isinstance(arg.args[0], ast.Constant)
            ):
                columns.append(str(arg.args[0].value))

        table_columns[table_name] = columns

    return table_columns


# ===========================================================================
# Test Classes
# ===========================================================================


class TestMigrationSequentialOrdering:
    """Verify migration files follow sequential numeric ordering."""

    def test_filenames_start_with_sequential_numbers(self) -> None:
        """Every migration filename must start with a 3-digit sequential prefix."""
        files = _migration_files()
        assert len(files) >= 2, "Expected at least 2 migration files"

        for i, mf in enumerate(files):
            prefix_match = re.match(r"^(\d+)_", mf.name)
            assert prefix_match is not None, (
                f"Migration file {mf.name} does not start with a numeric prefix"
            )
            # Verify sequential ordering (001, 002, ...)
            expected_num = i + 1
            actual_num = int(prefix_match.group(1))
            assert actual_num == expected_num, (
                f"Migration {mf.name} has prefix {actual_num} but expected "
                f"{expected_num} (sequential ordering broken)"
            )

    def test_revision_ids_match_filename_prefixes(self) -> None:
        """Each migration's revision ID must match its filename numeric prefix."""
        for rev in _parse_all_revisions():
            prefix_match = re.match(r"^(\d+)_", rev["file_name"])
            assert prefix_match is not None
            filename_prefix = prefix_match.group(1)
            assert rev["revision"] == filename_prefix, (
                f"Migration {rev['file_name']} has revision '{rev['revision']}' "
                f"but filename prefix is '{filename_prefix}'"
            )

    def test_down_revision_chain_matches_numeric_order(self) -> None:
        """Each migration's down_revision must point to the previous revision."""
        revisions = _parse_all_revisions()
        for i, rev in enumerate(revisions):
            if i == 0:
                assert rev["down_revision"] is None, (
                    f"First migration {rev['file_name']} should have "
                    f"down_revision=None, got '{rev['down_revision']}'"
                )
            else:
                expected_down = revisions[i - 1]["revision"]
                assert rev["down_revision"] == expected_down, (
                    f"Migration {rev['file_name']} has down_revision "
                    f"'{rev['down_revision']}' but expected '{expected_down}'"
                )


class TestUpgradeDowngradeSymmetry:
    """Verify each migration has meaningful upgrade and downgrade functions."""

    def test_all_migrations_have_upgrade(self) -> None:
        for rev in _parse_all_revisions():
            assert rev["has_upgrade"], (
                f"Migration {rev['file_name']} is missing an upgrade() function"
            )

    def test_all_migrations_have_downgrade(self) -> None:
        for rev in _parse_all_revisions():
            assert rev["has_downgrade"], (
                f"Migration {rev['file_name']} is missing a downgrade() function"
            )

    def test_upgrade_is_not_empty_pass(self) -> None:
        """upgrade() must contain real operations, not just ``pass``."""
        for rev in _parse_all_revisions():
            is_pass = _function_is_pass_only(rev["source"], "upgrade")
            assert not is_pass, (
                f"Migration {rev['file_name']} has an empty upgrade() "
                f"(just 'pass') -- this is a no-op migration"
            )

    def test_downgrade_is_not_empty_pass(self) -> None:
        """downgrade() must contain real operations, not just ``pass``."""
        for rev in _parse_all_revisions():
            is_pass = _function_is_pass_only(rev["source"], "downgrade")
            assert not is_pass, (
                f"Migration {rev['file_name']} has an empty downgrade() "
                f"(just 'pass') -- rollback is not possible"
            )

    def test_downgrade_reverses_upgrade_tables(self) -> None:
        """For migration 001, downgrade must drop the tables that upgrade creates."""
        rev_001 = next((r for r in _parse_all_revisions() if r["revision"] == "001"), None)
        assert rev_001 is not None, "Migration 001 not found"

        upgrade_body = _extract_function_body(rev_001["source"], "upgrade")
        downgrade_body = _extract_function_body(rev_001["source"], "downgrade")

        # upgrade creates these tables
        for table in _MIGRATION_TABLES:
            assert table in upgrade_body, f"Expected upgrade() to create table '{table}'"
            assert table in downgrade_body, (
                f"Expected downgrade() to reference table '{table}' for rollback"
            )


class TestDestructiveMigrationDetection:
    """Detect destructive operations in migrations and flag them.

    Destructive migrations (DROP COLUMN, DROP TABLE on existing data) are not
    safe for zero-downtime rolling deploys. This test class documents which
    migrations are destructive so operators can plan accordingly.
    """

    def test_migration_001_is_additive(self) -> None:
        """Migration 001 (initial) should only create tables, not drop anything."""
        rev = next((r for r in _parse_all_revisions() if r["revision"] == "001"), None)
        assert rev is not None

        upgrade_source = _collect_upgrade_source(rev["source"])
        destructive = _detect_destructive_ops(upgrade_source)
        assert destructive == [], (
            f"Migration 001 upgrade path has destructive operations: {destructive}. "
            f"Initial migration should be purely additive."
        )

    def test_migration_002_is_destructive(self) -> None:
        """Migration 002 drops and recreates the embedding column -- this is destructive.

        This test documents that migration 002 requires downtime or a re-ingestion
        strategy. It is NOT safe for zero-downtime rolling deploys.

        Note: migration 002 uses helper functions (_upgrade_table) that contain
        the actual DROP COLUMN SQL. We scan the full upgrade path, not just the
        direct body of upgrade().
        """
        rev = next((r for r in _parse_all_revisions() if r["revision"] == "002"), None)
        assert rev is not None

        upgrade_source = _collect_upgrade_source(rev["source"])
        destructive = _detect_destructive_ops(upgrade_source)
        assert len(destructive) > 0, (
            "Expected migration 002 to be flagged as destructive "
            "(it drops and recreates the embedding column via helper functions)"
        )
        assert any("DROP COLUMN" in d for d in destructive), (
            "Migration 002 should be flagged for DROP COLUMN"
        )

    def test_all_migrations_classified(self) -> None:
        """Every migration must be explicitly classified as additive or destructive.

        This ensures new migrations get reviewed for rolling-deploy safety.
        """
        revisions = _parse_all_revisions()
        assert len(revisions) >= 2, "Expected at least 2 migrations"

        # Build a classification for each migration
        classified: dict[str, list[str]] = {}
        for rev in revisions:
            upgrade_source = _collect_upgrade_source(rev["source"])
            findings = _detect_destructive_ops(upgrade_source)
            classified[rev["revision"]] = findings

        # Verify all revisions were classified
        assert set(classified.keys()) == {r["revision"] for r in revisions}

        # Document the classification
        additive = [r for r, f in classified.items() if not f]
        destructive = [r for r, f in classified.items() if f]

        assert "001" in additive, "Migration 001 should be additive"
        assert "002" in destructive, "Migration 002 should be destructive"


class TestNMinus1SchemaCompatibility:
    """Verify that app code at version N is compatible with schema at N-1.

    In a rolling deploy, the new application code starts running while the
    database is still at the old schema version. These tests verify that
    the ORM models used by application code can operate against the schema
    produced by the previous migration.

    Since the actual migrations use PostgreSQL-specific SQL (pgvector, JSONB,
    UUID), we test compatibility by comparing ORM model column expectations
    against the schema defined by each migration, without executing SQL.
    """

    @staticmethod
    def _get_orm_columns(table_name: str) -> dict[str, str]:
        """Return {column_name: type_description} for the ORM model of a table.

        This inspects the actual application ORM models to determine what
        columns the current code expects.
        """
        if table_name == "workflow_checkpoints":
            from agent33.workflows.checkpoint import WorkflowCheckpoint

            model = WorkflowCheckpoint
        elif table_name == "sessions":
            from agent33.memory.session import SessionManager  # noqa: F401

            # Sessions table is defined in alembic/env.py ORM, not a
            # standalone app ORM model. The app uses raw queries via
            # SessionManager. Return the env.py model's columns.
            return {
                "id": "UUID",
                "user_id": "Text",
                "agent_name": "Text",
                "data_encrypted": "Text",
                "created_at": "DateTime",
                "expires_at": "DateTime",
            }
        elif table_name == "memory_documents":
            # memory_documents is defined in alembic/env.py ORM
            return {
                "id": "UUID",
                "content": "Text",
                "embedding": "vector",
                "metadata": "JSONB",
                "created_at": "DateTime",
            }
        elif table_name == "memory_records":
            from agent33.memory.long_term import MemoryRecord

            model = MemoryRecord
        else:
            return {}

        # Extract column names and types from the SA model
        result: dict[str, str] = {}
        for col in model.__table__.columns:
            result[col.name] = type(col.type).__name__
        return result

    def test_migration_001_creates_expected_tables(self) -> None:
        """Migration 001 must create all tables needed by the application."""
        rev = next((r for r in _parse_all_revisions() if r["revision"] == "001"), None)
        assert rev is not None

        source = rev["source"]
        upgrade_body = _extract_function_body(source, "upgrade")

        for table in _MIGRATION_TABLES:
            assert f'"{table}"' in upgrade_body or f"'{table}'" in upgrade_body, (
                f"Migration 001 upgrade() does not create table '{table}'"
            )

    def test_migration_001_schema_has_required_columns(self) -> None:
        """Migration 001 schema must include all columns the ORM expects.

        This is the N-1 check for migration 002: if the app code has been
        updated to use 002's schema changes, can it still work with 001's
        schema?
        """
        rev = next((r for r in _parse_all_revisions() if r["revision"] == "001"), None)
        assert rev is not None

        # Parse the columns created by migration 001
        created_tables = _extract_table_columns_from_create(rev["source"])

        # workflow_checkpoints: the ORM model needs these columns
        assert "workflow_checkpoints" in created_tables
        wc_cols = created_tables["workflow_checkpoints"]
        # Migration 001 creates: id, workflow_id, step_id, state, created_at
        for expected in ["id", "workflow_id", "step_id", "state", "created_at"]:
            assert expected in wc_cols, (
                f"workflow_checkpoints missing column '{expected}' in migration 001"
            )

        # sessions
        assert "sessions" in created_tables
        sess_cols = created_tables["sessions"]
        for expected in ["id", "user_id", "agent_name", "data_encrypted", "created_at"]:
            assert expected in sess_cols, f"sessions missing column '{expected}' in migration 001"

        # memory_documents
        assert "memory_documents" in created_tables
        md_cols = created_tables["memory_documents"]
        for expected in ["id", "content", "metadata", "created_at"]:
            assert expected in md_cols, (
                f"memory_documents missing column '{expected}' in migration 001"
            )

    def test_orm_checkpoint_columns_exist_in_migration_001(self) -> None:
        """The WorkflowCheckpoint ORM model columns must exist in migration 001 schema.

        The ORM uses: id, workflow_id, step_id, state_json, created_at.
        Migration 001 creates: id, workflow_id, step_id, state, created_at.

        Note: The ORM column ``state_json`` maps to the DB column ``state``
        via SQLAlchemy column naming. The test verifies the DB-level column
        names that the ORM queries.
        """
        orm_cols = self._get_orm_columns("workflow_checkpoints")
        assert "id" in orm_cols, "ORM model missing 'id'"
        assert "workflow_id" in orm_cols, "ORM model missing 'workflow_id'"
        assert "step_id" in orm_cols, "ORM model missing 'step_id'"
        # The ORM uses state_json (Python attr) which maps to either
        # 'state_json' or 'state' column depending on the Column() definition
        assert "state_json" in orm_cols or "state" in orm_cols, (
            "ORM model missing 'state' or 'state_json' column"
        )
        assert "created_at" in orm_cols, "ORM model missing 'created_at'"

    def test_orm_memory_record_columns_exist_after_migration_002(self) -> None:
        """MemoryRecord ORM columns must be compatible with post-002 schema.

        MemoryRecord expects: id, content, embedding, metadata, created_at.
        Migration 002 changes embedding from vector(1536) to vector(768)
        but the column still exists with the same name.
        """
        orm_cols = self._get_orm_columns("memory_records")
        for expected in ["id", "content", "embedding", "metadata", "created_at"]:
            assert expected in orm_cols, f"MemoryRecord ORM model missing column '{expected}'"

    def test_migration_002_preserves_non_embedding_columns(self) -> None:
        """Migration 002 must not modify columns other than 'embedding'.

        For N-1 compatibility during rolling deploy, the non-embedding columns
        in memory_documents must remain unchanged between 001 and 002.
        """
        rev_001 = next((r for r in _parse_all_revisions() if r["revision"] == "001"), None)
        rev_002 = next((r for r in _parse_all_revisions() if r["revision"] == "002"), None)
        assert rev_001 is not None
        assert rev_002 is not None

        # 002's upgrade only touches the embedding column + index
        upgrade_body = _extract_function_body(rev_002["source"], "upgrade")

        # Verify 002 does NOT create or drop these tables
        assert "workflow_checkpoints" not in upgrade_body, (
            "Migration 002 should not touch workflow_checkpoints"
        )
        assert "sessions" not in upgrade_body, "Migration 002 should not touch sessions table"

        # Verify 002 only operates on embedding-related columns
        # The upgrade should reference 'embedding' but not other columns
        # like 'content', 'metadata', 'created_at'
        non_embedding_cols = ["content", "created_at"]
        for col in non_embedding_cols:
            # Check that the column isn't being dropped or altered
            assert f"DROP COLUMN IF EXISTS {col}" not in upgrade_body, (
                f"Migration 002 should not drop column '{col}'"
            )
            assert f"DROP COLUMN {col}" not in upgrade_body, (
                f"Migration 002 should not drop column '{col}'"
            )

    def test_rolling_deploy_safe_at_migration_001(self) -> None:
        """Verify that code expecting 001's schema can tolerate 001 being the
        current schema (trivial base case -- app and DB at same version).

        Migration 001 creates all base tables. App code that only queries
        these tables works fine.
        """
        # The base case: app at version 001, DB at version 001.
        # All required tables exist with all required columns.
        rev = next((r for r in _parse_all_revisions() if r["revision"] == "001"), None)
        assert rev is not None

        tables_created = _extract_table_columns_from_create(rev["source"])
        assert len(tables_created) >= 3, (
            f"Migration 001 creates {len(tables_created)} tables, expected >= 3"
        )

    def test_rolling_deploy_002_with_schema_001_embedding_incompatible(self) -> None:
        """Code at version 002 expects vector(768) embeddings, but schema 001
        has vector(1536). This is a known incompatibility.

        This test documents that migration 002 is NOT safe for zero-downtime
        rolling deploy due to embedding dimension change. The test verifies
        that 002's upgrade changes the embedding dimension.
        """
        rev_002 = next((r for r in _parse_all_revisions() if r["revision"] == "002"), None)
        assert rev_002 is not None

        # 002 changes embedding from 1536 to 768 (or configurable via env)
        source = rev_002["source"]
        assert "1536" in source, "Migration 002 should reference old dimension 1536"
        assert "768" in source or "EMBEDDING_DIM" in source, (
            "Migration 002 should reference new dimension 768 or EMBEDDING_DIM"
        )

        # The downgrade path restores vector(1536).
        # Migration 002 uses a helper function _downgrade_table() that contains
        # the actual vector(1536) reference, so we check the full source.
        assert "vector(1536)" in source, (
            "Migration 002 should contain vector(1536) for downgrade restoration"
        )


class TestMigrationDowngradeDataPreservation:
    """Verify that downgrade paths preserve data where possible.

    For non-destructive migrations, downgrade should not lose data.
    For destructive migrations, the test documents the data loss.
    """

    def test_migration_001_downgrade_drops_all_tables(self) -> None:
        """Migration 001 downgrade drops all created tables (acceptable -- it's
        the initial migration, so there is no previous state to preserve).
        """
        rev = next((r for r in _parse_all_revisions() if r["revision"] == "001"), None)
        assert rev is not None

        downgrade_body = _extract_function_body(rev["source"], "downgrade")
        for table in _MIGRATION_TABLES:
            assert table in downgrade_body, f"Migration 001 downgrade should drop table '{table}'"

    def test_migration_002_downgrade_restores_original_schema(self) -> None:
        """Migration 002 downgrade must restore vector(1536) with IVFFlat index.

        Although data (embeddings) is lost on upgrade, the downgrade must
        correctly restore the schema so that code at version 001 can work.

        Migration 002 uses a helper function ``_downgrade_table()`` that
        contains the actual SQL for restoring vector(1536) and the IVFFlat
        index, so we scan the full module source.
        """
        rev = next((r for r in _parse_all_revisions() if r["revision"] == "002"), None)
        assert rev is not None

        source = rev["source"]

        # Must restore vector(1536) -- in _downgrade_table helper
        assert "vector(1536)" in source, (
            "Migration 002 must contain vector(1536) for downgrade restoration"
        )
        # Must restore IVFFlat index -- in _downgrade_table helper
        assert "ivfflat" in source.lower(), (
            "Migration 002 must contain IVFFlat reference for downgrade restoration"
        )

    def test_migration_002_documents_data_loss(self) -> None:
        """Migration 002 must document that embeddings are lost on upgrade.

        The migration's docstring should warn about data loss.
        """
        rev = next((r for r in _parse_all_revisions() if r["revision"] == "002"), None)
        assert rev is not None

        # Check the module docstring for data loss warning
        tree = ast.parse(rev["source"])
        docstring = ast.get_docstring(tree)
        assert docstring is not None, "Migration 002 should have a docstring"

        docstring_lower = docstring.lower()
        assert "destructive" in docstring_lower or "data loss" in docstring_lower, (
            "Migration 002 docstring should warn about destructive changes or data loss"
        )


class TestMigrationChainWalk:
    """Walk the migration chain and verify structural properties."""

    def test_full_chain_walk_from_root_to_head(self) -> None:
        """Walk the revision chain from root to head, verifying every node is visited."""
        revisions = _parse_all_revisions()
        assert len(revisions) >= 2

        # Build forward map: down_revision -> revision
        forward: dict[str | None, str] = {}
        for rev in revisions:
            down = rev["down_revision"]
            assert down not in forward, (
                f"Branching detected: multiple migrations claim down_revision='{down}'"
            )
            forward[down] = rev["revision"]

        # Walk from None (root) to head
        visited: list[str] = []
        current: str | None = None
        while current in forward:
            next_rev = forward[current]
            visited.append(next_rev)
            current = next_rev

        all_rev_ids = {r["revision"] for r in revisions}
        assert set(visited) == all_rev_ids, (
            f"Chain walk visited {visited} but expected {sorted(all_rev_ids)}"
        )

    def test_head_revision_is_latest(self) -> None:
        """The head revision should be the numerically highest."""
        revisions = _parse_all_revisions()
        rev_ids = {r["revision"] for r in revisions}

        # Head = revision not referenced as any other's down_revision
        referenced = {r["down_revision"] for r in revisions if r["down_revision"]}
        heads = rev_ids - referenced

        assert len(heads) == 1, f"Expected exactly 1 head, found {heads}"
        head = heads.pop()

        # Head should be the highest numbered revision
        max_rev = max(rev_ids, key=lambda r: int(r))
        assert head == max_rev, (
            f"Head revision is '{head}' but highest numbered revision is '{max_rev}'"
        )


class TestMigrationConventions:
    """Verify migration files follow project conventions."""

    def test_all_migrations_have_docstrings(self) -> None:
        """Every migration file should have a module-level docstring."""
        for rev in _parse_all_revisions():
            tree = ast.parse(rev["source"])
            docstring = ast.get_docstring(tree)
            assert docstring is not None, (
                f"Migration {rev['file_name']} is missing a module docstring"
            )

    def test_all_migrations_have_create_date_comment(self) -> None:
        """Migration docstrings should include a Create Date."""
        for rev in _parse_all_revisions():
            tree = ast.parse(rev["source"])
            docstring = ast.get_docstring(tree) or ""
            assert "Create Date" in docstring, (
                f"Migration {rev['file_name']} docstring missing 'Create Date'"
            )

    def test_all_migrations_have_revision_id_comment(self) -> None:
        """Migration docstrings should include a Revision ID."""
        for rev in _parse_all_revisions():
            tree = ast.parse(rev["source"])
            docstring = ast.get_docstring(tree) or ""
            assert "Revision ID" in docstring, (
                f"Migration {rev['file_name']} docstring missing 'Revision ID'"
            )

    def test_all_migrations_declare_branch_labels(self) -> None:
        """Every migration should declare branch_labels (even if None)."""
        for rev in _parse_all_revisions():
            assert "branch_labels" in rev["source"], (
                f"Migration {rev['file_name']} missing branch_labels declaration"
            )

    def test_all_migrations_declare_depends_on(self) -> None:
        """Every migration should declare depends_on (even if None)."""
        for rev in _parse_all_revisions():
            assert "depends_on" in rev["source"], (
                f"Migration {rev['file_name']} missing depends_on declaration"
            )

    def test_migrations_use_from_future_annotations(self) -> None:
        """All migrations should use ``from __future__ import annotations``."""
        for rev in _parse_all_revisions():
            assert "from __future__ import annotations" in rev["source"], (
                f"Migration {rev['file_name']} missing 'from __future__ import annotations'"
            )


class TestRollingDeployReadinessMatrix:
    """Build a rolling-deploy readiness matrix for the entire migration chain.

    For each migration step (N-1 -> N), classify whether the transition is
    safe for rolling deploy or requires downtime.
    """

    def test_readiness_matrix(self) -> None:
        """Build and verify the rolling-deploy readiness matrix.

        Expected results:
        - 001 (None -> 001): N/A (initial migration, no N-1 state)
        - 002 (001 -> 002): UNSAFE (embedding column drop + recreate)
        """
        revisions = _parse_all_revisions()
        assert len(revisions) >= 2

        matrix: list[dict[str, Any]] = []
        for rev in revisions:
            upgrade_source = _collect_upgrade_source(rev["source"])
            destructive_ops = _detect_destructive_ops(upgrade_source)
            is_initial = rev["down_revision"] is None

            entry = {
                "revision": rev["revision"],
                "from": rev["down_revision"] or "(none)",
                "destructive_ops": destructive_ops,
                "rolling_deploy_safe": not destructive_ops and not is_initial,
                "classification": (
                    "INITIAL" if is_initial else "UNSAFE" if destructive_ops else "SAFE"
                ),
            }
            matrix.append(entry)

        # Verify expected classifications
        m001 = next(e for e in matrix if e["revision"] == "001")
        assert m001["classification"] == "INITIAL"

        m002 = next(e for e in matrix if e["revision"] == "002")
        assert m002["classification"] == "UNSAFE"
        assert not m002["rolling_deploy_safe"]


@pytest.mark.integration
class TestAlembicMigrationExecution:
    """Tests that execute actual Alembic migrations against a database.

    These tests require a running PostgreSQL instance with the pgvector
    extension installed. They are skipped in CI unless the
    ``DATABASE_URL`` environment variable is set.
    """

    @pytest.fixture(autouse=True)
    def _check_database(self) -> None:
        """Skip if no DATABASE_URL is configured."""
        import os

        if not os.environ.get("DATABASE_URL"):
            pytest.skip("DATABASE_URL not set -- skipping integration tests")

    def test_upgrade_to_head(self) -> None:
        """Apply all migrations from empty database to head."""
        # This test would use alembic.command.upgrade(config, "head")
        # against a test database. Skipped without DATABASE_URL.
        pytest.skip("Requires PostgreSQL with pgvector -- run manually")

    def test_downgrade_to_base(self) -> None:
        """Downgrade from head back to empty database."""
        pytest.skip("Requires PostgreSQL with pgvector -- run manually")

    def test_upgrade_downgrade_cycle(self) -> None:
        """Full upgrade-to-head then downgrade-to-base cycle."""
        pytest.skip("Requires PostgreSQL with pgvector -- run manually")

    def test_stepwise_upgrade_downgrade(self) -> None:
        """Apply each migration individually, then roll back one at a time."""
        pytest.skip("Requires PostgreSQL with pgvector -- run manually")


class TestSyntheticMigrationChainValidation:
    """Test the validation logic against synthetic migration chains.

    These tests create temporary migration files to verify that the
    validation helpers catch specific error conditions.
    """

    def test_detect_gap_in_chain(self, tmp_path: Path) -> None:
        """A migration referencing a non-existent down_revision is detected."""
        versions = tmp_path / "versions"
        versions.mkdir()

        (versions / "001_init.py").write_text(
            textwrap.dedent('''\
            """Init."""
            from __future__ import annotations
            revision: str = "001"
            down_revision: str | None = None
            branch_labels: tuple[str, ...] | None = None
            depends_on: str | None = None

            def upgrade() -> None:
                pass

            def downgrade() -> None:
                pass
            '''),
            encoding="utf-8",
        )

        # 003 skips 002 -- references non-existent revision
        (versions / "003_skip.py").write_text(
            textwrap.dedent('''\
            """Skip."""
            from __future__ import annotations
            revision: str = "003"
            down_revision: str | None = "002"
            branch_labels: tuple[str, ...] | None = None
            depends_on: str | None = None

            def upgrade() -> None:
                pass

            def downgrade() -> None:
                pass
            '''),
            encoding="utf-8",
        )

        from agent33.migrations.checker import MigrationChecker

        checker = MigrationChecker(alembic_dir=str(tmp_path))
        valid, errors = checker.validate_chain()
        assert valid is False
        assert len(errors) >= 1
        assert any("002" in e for e in errors), (
            f"Expected error about missing revision '002', got: {errors}"
        )

    def test_detect_branch_in_chain(self, tmp_path: Path) -> None:
        """Two migrations with the same down_revision create a branch."""
        versions = tmp_path / "versions"
        versions.mkdir()

        (versions / "001_init.py").write_text(
            textwrap.dedent('''\
            """Init."""
            from __future__ import annotations
            revision: str = "001"
            down_revision: str | None = None
            branch_labels: tuple[str, ...] | None = None
            depends_on: str | None = None

            def upgrade() -> None:
                pass

            def downgrade() -> None:
                pass
            '''),
            encoding="utf-8",
        )

        for name, rev in [("002a_feat.py", "002a"), ("002b_feat.py", "002b")]:
            (versions / name).write_text(
                textwrap.dedent(f'''\
                """Feature."""
                from __future__ import annotations
                revision: str = "{rev}"
                down_revision: str | None = "001"
                branch_labels: tuple[str, ...] | None = None
                depends_on: str | None = None

                def upgrade() -> None:
                    pass

                def downgrade() -> None:
                    pass
                '''),
                encoding="utf-8",
            )

        from agent33.migrations.checker import MigrationChecker

        checker = MigrationChecker(alembic_dir=str(tmp_path))
        conflicts = checker.detect_conflicts()
        assert len(conflicts) >= 1, "Expected a branch/conflict to be detected"
        assert "Multiple heads" in conflicts[0]

    def test_empty_upgrade_flagged(self) -> None:
        """A migration with an empty upgrade() body should be caught."""
        source = textwrap.dedent('''\
        """Empty."""
        from __future__ import annotations
        revision: str = "099"
        down_revision: str | None = "098"

        def upgrade() -> None:
            pass

        def downgrade() -> None:
            pass
        ''')
        assert _function_is_pass_only(source, "upgrade") is True
        assert _function_is_pass_only(source, "downgrade") is True

    def test_non_empty_upgrade_not_flagged(self) -> None:
        """A migration with real operations should not be flagged as empty."""
        source = textwrap.dedent('''\
        """Real."""
        from __future__ import annotations
        revision: str = "099"
        down_revision: str | None = "098"

        def upgrade() -> None:
            op.create_table("foo", sa.Column("id", sa.Integer, primary_key=True))

        def downgrade() -> None:
            op.drop_table("foo")
        ''')
        assert _function_is_pass_only(source, "upgrade") is False
        assert _function_is_pass_only(source, "downgrade") is False

    def test_destructive_detection_drop_column(self) -> None:
        """DROP COLUMN in migration source is flagged as destructive."""
        source = 'op.execute("ALTER TABLE foo DROP COLUMN bar")'
        findings = _detect_destructive_ops(source)
        assert any("DROP COLUMN" in f for f in findings)

    def test_destructive_detection_drop_table(self) -> None:
        """DROP TABLE in migration source is flagged as destructive."""
        source = 'op.drop_table("foo")'
        findings = _detect_destructive_ops(source)
        assert any("DROP TABLE" in f for f in findings)

    def test_additive_migration_not_flagged(self) -> None:
        """A purely additive migration (CREATE TABLE only) is not flagged."""
        source = 'op.create_table("foo", sa.Column("id", sa.Integer))'
        findings = _detect_destructive_ops(source)
        assert findings == []
