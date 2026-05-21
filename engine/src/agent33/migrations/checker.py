"""Alembic migration chain inspection and validation.

Provides offline chain validation (no database required) and optional online
pending-migration detection when a database URL is available.

The checker parses Alembic migration script files directly, extracting revision
metadata (``revision``, ``down_revision``, ``branch_labels``, ``depends_on``)
from module-level assignments.  This avoids requiring Alembic's internal
``ScriptDirectory`` machinery (which needs a valid ``alembic.ini`` with a
reachable ``sqlalchemy.url``) for pure chain-integrity checks.
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

_REVISION_VARS = frozenset({"revision", "down_revision", "branch_labels", "depends_on"})
"""Module-level variable names extracted from Alembic migration scripts."""


class MigrationStatus(BaseModel):
    """Snapshot of the Alembic migration chain state."""

    current_head: str | None = None
    pending_count: int = 0
    pending_revisions: list[str] = Field(default_factory=list)
    chain_valid: bool = True
    has_multiple_heads: bool = False
    heads: list[str] = Field(default_factory=list)
    branch_labels: list[str] = Field(default_factory=list)


class RevisionInfo(BaseModel):
    """Metadata for a single Alembic revision script."""

    revision: str
    down_revision: str | None = None
    branch_labels: list[str] = Field(default_factory=list)
    depends_on: str | None = None
    message: str = ""
    file_name: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_string_or_none(node: ast.expr) -> str | None:
    """Return a string literal value from an AST node, or ``None``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Constant) and node.value is None:
        return None
    return None


def _extract_string_list(node: ast.expr) -> list[str]:
    """Return a list of string literals from an AST Tuple/List/Set."""
    if isinstance(node, ast.Constant) and node.value is None:
        return []
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        result: list[str] = []
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                result.append(elt.value)
        return result
    # Single string also accepted
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    return []


def _parse_migration_script(path: Path) -> RevisionInfo | None:
    """Parse a single migration script and extract revision metadata.

    Returns ``None`` if the file cannot be parsed or does not contain a
    ``revision`` assignment.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("migration_file_read_failed: %s", path)
        return None

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        logger.warning("migration_file_parse_failed: %s", path)
        return None

    revision: str | None = None
    down_revision: str | None = None
    branch_labels: list[str] = []
    depends_on: str | None = None

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue

        # Handle both plain assign and annotated assign
        if isinstance(node, ast.AnnAssign):
            if node.value is None:
                continue
            ann_target = node.target
            if not isinstance(ann_target, ast.Name):
                continue
            name = ann_target.id
            value = node.value
        else:
            if len(node.targets) != 1:
                continue
            plain_target = node.targets[0]
            if not isinstance(plain_target, ast.Name):
                continue
            name = plain_target.id
            value = node.value

        if name not in _REVISION_VARS:
            continue

        if name == "revision":
            revision = _extract_string_or_none(value)
        elif name == "down_revision":
            down_revision = _extract_string_or_none(value)
        elif name == "branch_labels":
            branch_labels = _extract_string_list(value)
        elif name == "depends_on":
            depends_on = _extract_string_or_none(value)

    if revision is None:
        return None

    # Extract docstring message (first line of module docstring)
    message = ""
    docstring = ast.get_docstring(tree)
    if docstring:
        first_line = docstring.strip().split("\n")[0]
        # Strip trailing Alembic metadata lines (Revision ID, Revises, Create Date)
        if not re.match(r"^(Revision ID|Revises|Create Date):", first_line):
            message = first_line

    return RevisionInfo(
        revision=revision,
        down_revision=down_revision,
        branch_labels=branch_labels,
        depends_on=depends_on,
        message=message,
        file_name=path.name,
    )


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------


class MigrationChecker:
    """Inspect and validate an Alembic migration chain.

    Works in two modes:

    * **Offline** (default): Parses migration script files to validate chain
      integrity, detect multiple heads, and list revisions.  No database or
      running Alembic environment required.

    * **Online** (when ``db_url`` is provided to :meth:`check_pending`):
      Compares the current database revision against the chain head to
      determine pending migrations.

    Parameters
    ----------
    alembic_dir:
        Path to the Alembic scripts directory (containing ``versions/``).
        Can be relative (resolved against cwd) or absolute.
    config_file:
        Path to the ``alembic.ini`` configuration file.  Currently used
        only for metadata; offline operations do not require it.
    """

    def __init__(
        self,
        alembic_dir: str = "alembic",
        config_file: str = "alembic.ini",
    ) -> None:
        self._alembic_dir = Path(alembic_dir)
        self._config_file = Path(config_file)
        self._revisions: list[RevisionInfo] | None = None

    # -- Internal helpers ---------------------------------------------------

    @property
    def versions_dir(self) -> Path:
        """Return the path to the ``versions/`` subdirectory."""
        return self._alembic_dir / "versions"

    def _load_revisions(self) -> list[RevisionInfo]:
        """Discover and parse all migration scripts in ``versions/``."""
        if self._revisions is not None:
            return self._revisions

        vdir = self.versions_dir
        if not vdir.is_dir():
            logger.info("alembic_versions_dir_not_found: %s", vdir)
            self._revisions = []
            return self._revisions

        revisions: list[RevisionInfo] = []
        for path in sorted(vdir.glob("*.py")):
            if path.name == "__init__.py":
                continue
            info = _parse_migration_script(path)
            if info is not None:
                revisions.append(info)

        self._revisions = revisions
        return self._revisions

    def _build_down_map(self) -> dict[str, str | None]:
        """Return ``{revision: down_revision}`` for every script."""
        return {r.revision: r.down_revision for r in self._load_revisions()}

    def _build_up_map(self) -> dict[str | None, list[str]]:
        """Return ``{down_revision: [revisions that depend on it]}``."""
        up: dict[str | None, list[str]] = {}
        for rev in self._load_revisions():
            up.setdefault(rev.down_revision, []).append(rev.revision)
        return up

    # -- Public API ---------------------------------------------------------

    def list_revisions(self) -> list[dict[str, Any]]:
        """Return metadata for every discovered revision script.

        Each dict contains: ``revision``, ``down_revision``,
        ``branch_labels``, ``depends_on``, ``message``, ``file_name``.
        """
        return [r.model_dump() for r in self._load_revisions()]

    def validate_chain(self) -> tuple[bool, list[str]]:
        """Validate the revision chain integrity.

        Returns a ``(valid, errors)`` tuple.  An empty error list means the
        chain is valid.

        Checks performed:

        * No orphaned ``down_revision`` references (every referenced parent
          must exist, or be ``None`` for the root migration).
        * No duplicate revision identifiers.
        * Exactly one root (``down_revision is None``) unless branch labels
          are used.
        """
        revisions = self._load_revisions()
        errors: list[str] = []

        if not revisions:
            # An empty chain is valid (nothing to break).
            return True, errors

        rev_ids = {r.revision for r in revisions}

        # Duplicate check
        seen: set[str] = set()
        for r in revisions:
            if r.revision in seen:
                errors.append(f"Duplicate revision id: {r.revision}")
            seen.add(r.revision)

        # Orphan check: every non-None down_revision must exist in rev_ids
        for r in revisions:
            if r.down_revision is not None and r.down_revision not in rev_ids:
                errors.append(
                    f"Revision {r.revision} references non-existent "
                    f"down_revision {r.down_revision}"
                )

        # Root count check
        roots = [r for r in revisions if r.down_revision is None]
        if len(roots) > 1:
            root_ids = [r.revision for r in roots]
            errors.append(f"Multiple root revisions (down_revision=None): {root_ids}")

        valid = len(errors) == 0
        return valid, errors

    def detect_conflicts(self) -> list[str]:
        """Detect multiple heads in the revision chain.

        Returns a list of conflict descriptions (empty if no conflicts).
        Multiple heads indicate that a merge migration is needed.
        """
        revisions = self._load_revisions()
        if not revisions:
            return []

        rev_ids = {r.revision for r in revisions}
        # A revision is a "child" of some other revision.
        # Heads are revisions that are NOT the down_revision of any other.
        children: set[str | None] = {r.down_revision for r in revisions}
        heads = [rid for rid in rev_ids if rid not in children]

        if len(heads) <= 1:
            return []

        return [f"Multiple heads detected: {heads}. A merge migration is required."]

    def _find_heads(self) -> list[str]:
        """Return all head revisions (not referenced as down_revision by any other)."""
        revisions = self._load_revisions()
        if not revisions:
            return []

        rev_ids = {r.revision for r in revisions}
        children: set[str | None] = {r.down_revision for r in revisions}
        return sorted(rid for rid in rev_ids if rid not in children)

    def _collect_branch_labels(self) -> list[str]:
        """Return all branch labels across the chain."""
        labels: list[str] = []
        for r in self._load_revisions():
            labels.extend(r.branch_labels)
        return sorted(set(labels))

    def get_status(self) -> MigrationStatus:
        """Return a composite :class:`MigrationStatus` snapshot (offline).

        This does not require a database connection.  The ``pending_count``
        and ``pending_revisions`` fields are only populated by
        :meth:`check_pending`.
        """
        valid, _errors = self.validate_chain()
        heads = self._find_heads()

        return MigrationStatus(
            current_head=heads[0] if len(heads) == 1 else None,
            pending_count=0,
            pending_revisions=[],
            chain_valid=valid,
            has_multiple_heads=len(heads) > 1,
            heads=heads,
            branch_labels=self._collect_branch_labels(),
        )

    def check_pending(self, db_url: str | None = None) -> list[str]:
        """Compare the database revision against the chain head.

        Parameters
        ----------
        db_url:
            SQLAlchemy-style database URL.  If ``None``, returns an empty
            list (no online check is performed).

        Returns
        -------
        list[str]
            Revision IDs that are ahead of the database.

        Notes
        -----
        This method uses Alembic's ``MigrationContext`` to read the current
        database revision.  It requires a live database connection and a
        synchronous SQLAlchemy engine.

        If the ``alembic`` package is not importable or the connection
        fails, an empty list is returned with a warning logged.
        """
        if db_url is None:
            return []

        try:
            from alembic.runtime.migration import MigrationContext
            from sqlalchemy import create_engine
        except ImportError:
            logger.warning("alembic_or_sqlalchemy_not_available")
            return []

        # Build synchronous URL (strip +asyncpg if present)
        sync_url = db_url.replace("+asyncpg", "")

        try:
            engine = create_engine(sync_url)
            with engine.connect() as conn:
                context = MigrationContext.configure(conn)
                current_rev = context.get_current_revision()
        except Exception as exc:
            logger.warning("migration_pending_check_failed: %s", exc)
            return []

        # Walk chain from head(s) back to current_rev to find pending
        heads = self._find_heads()
        down_map = self._build_down_map()

        pending: list[str] = []
        for head in heads:
            rev: str | None = head
            while rev is not None and rev != current_rev:
                pending.append(rev)
                rev = down_map.get(rev)

        return pending
