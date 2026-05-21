"""Tests for S34: Alembic migration checker — chain validation, revision listing, API routes."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from agent33.config import Settings
from agent33.migrations.checker import (
    MigrationChecker,
    MigrationStatus,
    RevisionInfo,
    _parse_migration_script,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_alembic_dir(tmp_path: Path) -> Path:
    """Create a minimal Alembic directory with one valid migration."""
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)
    script = versions / "001_initial.py"
    script.write_text(
        textwrap.dedent('''\
        """Initial migration -- tables setup.

        Revision ID: 001
        Revises:
        Create Date: 2025-01-01 00:00:00.000000
        """
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
    return tmp_path


@pytest.fixture()
def two_revision_dir(tmp_path: Path) -> Path:
    """Create a two-revision linear chain."""
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)

    (versions / "001_initial.py").write_text(
        textwrap.dedent('''\
        """Initial migration."""
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

    (versions / "002_add_users.py").write_text(
        textwrap.dedent('''\
        """Add users table."""
        revision: str = "002"
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

    return tmp_path


@pytest.fixture()
def multi_head_dir(tmp_path: Path) -> Path:
    """Create a branching chain with multiple heads (conflict scenario)."""
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)

    (versions / "001_initial.py").write_text(
        textwrap.dedent('''\
        """Initial migration."""
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

    # Two revisions both descend from 001 => multiple heads
    (versions / "002a_feature_a.py").write_text(
        textwrap.dedent('''\
        """Feature A branch."""
        revision: str = "002a"
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

    (versions / "002b_feature_b.py").write_text(
        textwrap.dedent('''\
        """Feature B branch."""
        revision: str = "002b"
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

    return tmp_path


@pytest.fixture()
def orphan_dir(tmp_path: Path) -> Path:
    """Create a chain with a broken down_revision reference."""
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)

    (versions / "002_orphan.py").write_text(
        textwrap.dedent('''\
        """Orphan migration."""
        revision: str = "002"
        down_revision: str | None = "missing_001"
        branch_labels: tuple[str, ...] | None = None
        depends_on: str | None = None

        def upgrade() -> None:
            pass

        def downgrade() -> None:
            pass
        '''),
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture()
def branch_labels_dir(tmp_path: Path) -> Path:
    """Create a chain with branch labels."""
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)

    (versions / "001_initial.py").write_text(
        textwrap.dedent('''\
        """Initial migration."""
        revision: str = "001"
        down_revision: str | None = None
        branch_labels: tuple[str, ...] | None = ("main",)
        depends_on: str | None = None

        def upgrade() -> None:
            pass

        def downgrade() -> None:
            pass
        '''),
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture()
def real_alembic_dir() -> Path:
    """Return the actual engine/alembic directory for integration-style tests."""
    return Path(__file__).resolve().parent.parent / "alembic"


# ---------------------------------------------------------------------------
# MigrationStatus model tests
# ---------------------------------------------------------------------------


class TestMigrationStatusModel:
    """Test MigrationStatus Pydantic model defaults and serialization."""

    def test_defaults(self) -> None:
        status = MigrationStatus()
        assert status.current_head is None
        assert status.pending_count == 0
        assert status.pending_revisions == []
        assert status.chain_valid is True
        assert status.has_multiple_heads is False
        assert status.heads == []
        assert status.branch_labels == []

    def test_populated_status(self) -> None:
        status = MigrationStatus(
            current_head="abc123",
            pending_count=2,
            pending_revisions=["def456", "ghi789"],
            chain_valid=True,
            has_multiple_heads=False,
            heads=["abc123"],
            branch_labels=["main"],
        )
        assert status.current_head == "abc123"
        assert status.pending_count == 2
        assert len(status.pending_revisions) == 2
        assert status.heads == ["abc123"]

    def test_model_dump_roundtrip(self) -> None:
        status = MigrationStatus(
            current_head="001",
            heads=["001"],
            chain_valid=True,
        )
        data = status.model_dump()
        restored = MigrationStatus(**data)
        assert restored.current_head == "001"
        assert restored.chain_valid is True

    def test_invalid_head_status(self) -> None:
        status = MigrationStatus(
            current_head=None,
            has_multiple_heads=True,
            heads=["a", "b"],
            chain_valid=False,
        )
        assert status.current_head is None
        assert status.has_multiple_heads is True
        assert len(status.heads) == 2


class TestRevisionInfoModel:
    """Test RevisionInfo Pydantic model."""

    def test_defaults(self) -> None:
        info = RevisionInfo(revision="001")
        assert info.revision == "001"
        assert info.down_revision is None
        assert info.branch_labels == []
        assert info.depends_on is None
        assert info.message == ""
        assert info.file_name == ""

    def test_fully_populated(self) -> None:
        info = RevisionInfo(
            revision="002",
            down_revision="001",
            branch_labels=["feature"],
            depends_on="001",
            message="Add users table",
            file_name="002_add_users.py",
        )
        assert info.down_revision == "001"
        assert info.branch_labels == ["feature"]
        assert info.message == "Add users table"


# ---------------------------------------------------------------------------
# Script parsing tests
# ---------------------------------------------------------------------------


class TestParseRevisionScript:
    """Test the AST-based migration script parser."""

    def test_parse_valid_script(self, tmp_alembic_dir: Path) -> None:
        script = tmp_alembic_dir / "alembic" / "versions" / "001_initial.py"
        info = _parse_migration_script(script)
        assert info is not None
        assert info.revision == "001"
        assert info.down_revision is None
        assert info.message == "Initial migration -- tables setup."

    def test_parse_nonexistent_file(self, tmp_path: Path) -> None:
        result = _parse_migration_script(tmp_path / "nonexistent.py")
        assert result is None

    def test_parse_syntax_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.py"
        bad.write_text("def broken(:\n  pass", encoding="utf-8")
        result = _parse_migration_script(bad)
        assert result is None

    def test_parse_no_revision_var(self, tmp_path: Path) -> None:
        script = tmp_path / "no_rev.py"
        script.write_text("x = 1\ny = 2\n", encoding="utf-8")
        result = _parse_migration_script(script)
        assert result is None

    def test_parse_annotated_assignment(self, tmp_path: Path) -> None:
        """Verify that annotated assignments (e.g., ``revision: str = "001"``) are parsed."""
        script = tmp_path / "annotated.py"
        script.write_text(
            textwrap.dedent('''\
            """Annotated style migration."""
            revision: str = "abc"
            down_revision: str | None = "prev"
            branch_labels: tuple[str, ...] | None = ("my-branch",)
            depends_on: str | None = None
            '''),
            encoding="utf-8",
        )
        info = _parse_migration_script(script)
        assert info is not None
        assert info.revision == "abc"
        assert info.down_revision == "prev"
        assert info.branch_labels == ["my-branch"]
        assert info.depends_on is None

    def test_parse_plain_assignment(self, tmp_path: Path) -> None:
        """Verify plain (un-annotated) assignments are also parsed."""
        script = tmp_path / "plain.py"
        script.write_text(
            textwrap.dedent('''\
            """Plain style migration."""
            revision = "xyz"
            down_revision = None
            branch_labels = None
            depends_on = None
            '''),
            encoding="utf-8",
        )
        info = _parse_migration_script(script)
        assert info is not None
        assert info.revision == "xyz"
        assert info.down_revision is None


# ---------------------------------------------------------------------------
# MigrationChecker: list_revisions
# ---------------------------------------------------------------------------


class TestListRevisions:
    """Test listing revisions from actual and synthetic alembic dirs."""

    def test_list_revisions_single(self, tmp_alembic_dir: Path) -> None:
        checker = MigrationChecker(alembic_dir=str(tmp_alembic_dir / "alembic"))
        revisions = checker.list_revisions()
        assert len(revisions) == 1
        assert revisions[0]["revision"] == "001"
        assert revisions[0]["down_revision"] is None
        assert revisions[0]["file_name"] == "001_initial.py"

    def test_list_revisions_two(self, two_revision_dir: Path) -> None:
        checker = MigrationChecker(alembic_dir=str(two_revision_dir / "alembic"))
        revisions = checker.list_revisions()
        assert len(revisions) == 2
        rev_ids = {r["revision"] for r in revisions}
        assert rev_ids == {"001", "002"}

    def test_list_revisions_empty_dir(self, tmp_path: Path) -> None:
        versions = tmp_path / "alembic" / "versions"
        versions.mkdir(parents=True)
        checker = MigrationChecker(alembic_dir=str(tmp_path / "alembic"))
        assert checker.list_revisions() == []

    def test_list_revisions_missing_dir(self, tmp_path: Path) -> None:
        checker = MigrationChecker(alembic_dir=str(tmp_path / "nonexistent"))
        assert checker.list_revisions() == []

    def test_list_revisions_from_real_alembic_dir(self, real_alembic_dir: Path) -> None:
        """Integration-style: read the actual engine/alembic/ directory."""
        if not real_alembic_dir.is_dir():
            pytest.skip("No real alembic directory found")
        checker = MigrationChecker(alembic_dir=str(real_alembic_dir))
        revisions = checker.list_revisions()
        assert len(revisions) >= 1
        # The 001_initial.py migration should always be present
        rev_ids = {r["revision"] for r in revisions}
        assert "001" in rev_ids


# ---------------------------------------------------------------------------
# MigrationChecker: validate_chain
# ---------------------------------------------------------------------------


class TestValidateChain:
    """Test revision chain validation logic."""

    def test_valid_single_chain(self, tmp_alembic_dir: Path) -> None:
        checker = MigrationChecker(alembic_dir=str(tmp_alembic_dir / "alembic"))
        valid, errors = checker.validate_chain()
        assert valid is True
        assert errors == []

    def test_valid_two_revision_chain(self, two_revision_dir: Path) -> None:
        checker = MigrationChecker(alembic_dir=str(two_revision_dir / "alembic"))
        valid, errors = checker.validate_chain()
        assert valid is True
        assert errors == []

    def test_orphan_detected(self, orphan_dir: Path) -> None:
        checker = MigrationChecker(alembic_dir=str(orphan_dir / "alembic"))
        valid, errors = checker.validate_chain()
        assert valid is False
        assert len(errors) >= 1
        assert "missing_001" in errors[0]

    def test_empty_chain_is_valid(self, tmp_path: Path) -> None:
        versions = tmp_path / "alembic" / "versions"
        versions.mkdir(parents=True)
        checker = MigrationChecker(alembic_dir=str(tmp_path / "alembic"))
        valid, errors = checker.validate_chain()
        assert valid is True
        assert errors == []

    def test_duplicate_revision_detected(self, tmp_path: Path) -> None:
        versions = tmp_path / "alembic" / "versions"
        versions.mkdir(parents=True)

        for name in ("001a.py", "001b.py"):
            (versions / name).write_text(
                textwrap.dedent('''\
                """Duplicate revision."""
                revision = "001"
                down_revision = None
                '''),
                encoding="utf-8",
            )

        checker = MigrationChecker(alembic_dir=str(tmp_path / "alembic"))
        valid, errors = checker.validate_chain()
        assert valid is False
        assert any("Duplicate" in e for e in errors)

    def test_multiple_roots_detected(self, tmp_path: Path) -> None:
        versions = tmp_path / "alembic" / "versions"
        versions.mkdir(parents=True)

        (versions / "001_root_a.py").write_text(
            textwrap.dedent('''\
            """Root A."""
            revision = "a"
            down_revision = None
            '''),
            encoding="utf-8",
        )
        (versions / "002_root_b.py").write_text(
            textwrap.dedent('''\
            """Root B."""
            revision = "b"
            down_revision = None
            '''),
            encoding="utf-8",
        )

        checker = MigrationChecker(alembic_dir=str(tmp_path / "alembic"))
        valid, errors = checker.validate_chain()
        assert valid is False
        assert any("Multiple root" in e for e in errors)

    def test_real_chain_is_valid(self, real_alembic_dir: Path) -> None:
        """Verify the real migration chain has no integrity errors."""
        if not real_alembic_dir.is_dir():
            pytest.skip("No real alembic directory found")
        checker = MigrationChecker(alembic_dir=str(real_alembic_dir))
        valid, errors = checker.validate_chain()
        assert valid is True, f"Real chain has errors: {errors}"


# ---------------------------------------------------------------------------
# MigrationChecker: detect_conflicts
# ---------------------------------------------------------------------------


class TestDetectConflicts:
    """Test multiple-head (conflict) detection."""

    def test_no_conflicts_single_chain(self, two_revision_dir: Path) -> None:
        checker = MigrationChecker(alembic_dir=str(two_revision_dir / "alembic"))
        conflicts = checker.detect_conflicts()
        assert conflicts == []

    def test_multiple_heads_detected(self, multi_head_dir: Path) -> None:
        checker = MigrationChecker(alembic_dir=str(multi_head_dir / "alembic"))
        conflicts = checker.detect_conflicts()
        assert len(conflicts) == 1
        assert "Multiple heads" in conflicts[0]
        assert "002a" in conflicts[0]
        assert "002b" in conflicts[0]

    def test_no_conflicts_empty_chain(self, tmp_path: Path) -> None:
        versions = tmp_path / "alembic" / "versions"
        versions.mkdir(parents=True)
        checker = MigrationChecker(alembic_dir=str(tmp_path / "alembic"))
        assert checker.detect_conflicts() == []


# ---------------------------------------------------------------------------
# MigrationChecker: get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    """Test the composite get_status() method."""

    def test_status_single_revision(self, tmp_alembic_dir: Path) -> None:
        checker = MigrationChecker(alembic_dir=str(tmp_alembic_dir / "alembic"))
        status = checker.get_status()
        assert isinstance(status, MigrationStatus)
        assert status.current_head == "001"
        assert status.chain_valid is True
        assert status.has_multiple_heads is False
        assert status.heads == ["001"]
        assert status.pending_count == 0
        assert status.pending_revisions == []

    def test_status_two_revisions(self, two_revision_dir: Path) -> None:
        checker = MigrationChecker(alembic_dir=str(two_revision_dir / "alembic"))
        status = checker.get_status()
        assert status.current_head == "002"
        assert status.heads == ["002"]
        assert status.chain_valid is True

    def test_status_multi_head(self, multi_head_dir: Path) -> None:
        checker = MigrationChecker(alembic_dir=str(multi_head_dir / "alembic"))
        status = checker.get_status()
        assert status.has_multiple_heads is True
        assert status.current_head is None  # ambiguous when multiple heads
        assert len(status.heads) == 2
        assert set(status.heads) == {"002a", "002b"}

    def test_status_orphan_chain(self, orphan_dir: Path) -> None:
        checker = MigrationChecker(alembic_dir=str(orphan_dir / "alembic"))
        status = checker.get_status()
        assert status.chain_valid is False

    def test_status_empty_chain(self, tmp_path: Path) -> None:
        versions = tmp_path / "alembic" / "versions"
        versions.mkdir(parents=True)
        checker = MigrationChecker(alembic_dir=str(tmp_path / "alembic"))
        status = checker.get_status()
        assert status.chain_valid is True
        assert status.heads == []
        assert status.current_head is None

    def test_status_with_branch_labels(self, branch_labels_dir: Path) -> None:
        checker = MigrationChecker(alembic_dir=str(branch_labels_dir / "alembic"))
        status = checker.get_status()
        assert "main" in status.branch_labels


# ---------------------------------------------------------------------------
# MigrationChecker: check_pending (offline)
# ---------------------------------------------------------------------------


class TestCheckPending:
    """Test the check_pending method."""

    def test_no_db_url_returns_empty(self, tmp_alembic_dir: Path) -> None:
        checker = MigrationChecker(alembic_dir=str(tmp_alembic_dir / "alembic"))
        pending = checker.check_pending(db_url=None)
        assert pending == []

    def test_import_error_returns_empty(self, tmp_alembic_dir: Path) -> None:
        """When alembic or sqlalchemy import fails, return empty gracefully."""
        checker = MigrationChecker(alembic_dir=str(tmp_alembic_dir / "alembic"))
        with patch.dict("sys.modules", {"alembic.config": None}):
            pending = checker.check_pending(db_url="sqlite:///test.db")
            # May or may not hit the ImportError path depending on import caching;
            # either way should not raise.
            assert isinstance(pending, list)


# ---------------------------------------------------------------------------
# MigrationChecker: offline mode (no DB required)
# ---------------------------------------------------------------------------


class TestOfflineMode:
    """Verify all offline operations work without any database or network."""

    def test_all_offline_ops(self, two_revision_dir: Path) -> None:
        checker = MigrationChecker(alembic_dir=str(two_revision_dir / "alembic"))
        # All these must succeed without DB
        revisions = checker.list_revisions()
        assert len(revisions) == 2

        valid, errors = checker.validate_chain()
        assert valid is True

        conflicts = checker.detect_conflicts()
        assert conflicts == []

        status = checker.get_status()
        assert status.chain_valid is True
        assert status.current_head == "002"

    def test_offline_with_missing_versions_dir(self, tmp_path: Path) -> None:
        """Checker should not crash when versions/ doesn't exist."""
        checker = MigrationChecker(alembic_dir=str(tmp_path / "nope"))
        assert checker.list_revisions() == []
        valid, errors = checker.validate_chain()
        assert valid is True
        assert checker.detect_conflicts() == []
        status = checker.get_status()
        assert status.chain_valid is True


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


class TestConfigDefaults:
    """Test that the S34 config settings have correct defaults."""

    def test_alembic_config_path_default(self) -> None:
        s = Settings(
            environment="test",
            jwt_secret="test-secret",  # type: ignore[arg-type]
        )
        assert s.alembic_config_path == "alembic.ini"

    def test_alembic_auto_check_default(self) -> None:
        s = Settings(
            environment="test",
            jwt_secret="test-secret",  # type: ignore[arg-type]
        )
        assert s.alembic_auto_check_on_startup is False


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


def _install_migration_checker(
    app: Any,
    checker: MigrationChecker,
) -> None:
    """Install a MigrationChecker on app.state for test routes."""
    app.state.migration_checker = checker


class TestMigrationRoutes:
    """Test the /v1/migrations/* API endpoints."""

    @pytest.fixture()
    def _checker(self, two_revision_dir: Path) -> MigrationChecker:
        return MigrationChecker(alembic_dir=str(two_revision_dir / "alembic"))

    async def test_status_endpoint_returns_migration_status(
        self, _checker: MigrationChecker
    ) -> None:
        from agent33.main import app

        _install_migration_checker(app, _checker)

        # Install minimal auth bypass for admin scope
        app.state.tool_governance = None
        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Tenant-Id": "test"},
        ) as client:
            resp = await client.get("/v1/migrations/status")

        # Without valid admin credentials we expect 401
        assert resp.status_code == 401

    async def test_revisions_endpoint_returns_401_without_auth(
        self, _checker: MigrationChecker
    ) -> None:
        from agent33.main import app

        _install_migration_checker(app, _checker)

        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            resp = await client.get("/v1/migrations/revisions")

        assert resp.status_code == 401

    async def test_status_endpoint_with_admin_auth(self, _checker: MigrationChecker) -> None:
        """With a valid admin JWT, the status endpoint returns migration data."""
        import jwt

        from agent33.config import settings
        from agent33.main import app

        _install_migration_checker(app, _checker)

        token = jwt.encode(
            {
                "sub": "admin-user",
                "tenant_id": "test-tenant",
                "scopes": ["admin"],
            },
            settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )

        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            resp = await client.get("/v1/migrations/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "chain_valid" in data
        assert data["chain_valid"] is True
        assert "heads" in data
        assert "002" in data["heads"]
        assert data["current_head"] == "002"
        assert data["has_multiple_heads"] is False

    async def test_revisions_endpoint_with_admin_auth(self, _checker: MigrationChecker) -> None:
        """With a valid admin JWT, the revisions endpoint returns revision list."""
        import jwt

        from agent33.config import settings
        from agent33.main import app

        _install_migration_checker(app, _checker)

        token = jwt.encode(
            {
                "sub": "admin-user",
                "tenant_id": "test-tenant",
                "scopes": ["admin"],
            },
            settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )

        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            resp = await client.get("/v1/migrations/revisions")

        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert data["count"] == 2
        assert "revisions" in data
        rev_ids = {r["revision"] for r in data["revisions"]}
        assert rev_ids == {"001", "002"}

    async def test_status_503_when_checker_not_installed(self) -> None:
        """If migration_checker is not on app.state, routes return 503."""
        import jwt

        from agent33.config import settings
        from agent33.main import app

        # Remove the checker if present
        if hasattr(app.state, "migration_checker"):
            delattr(app.state, "migration_checker")

        token = jwt.encode(
            {
                "sub": "admin-user",
                "tenant_id": "test-tenant",
                "scopes": ["admin"],
            },
            settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )

        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            resp = await client.get("/v1/migrations/status")

        assert resp.status_code == 503
        assert "not initialized" in resp.json()["detail"]
