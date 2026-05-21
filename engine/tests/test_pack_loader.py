"""Tests for pack loader: PACK.yaml parsing, directory validation, skill loading.

Tests cover: manifest loading, skill loading from pack directories,
path traversal protection, checksum verification, directory validation,
and checksum computation.
"""

from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path

import pytest

from agent33.packs.loader import (
    compute_pack_checksum,
    load_pack_manifest,
    load_pack_skills,
    validate_pack_directory,
    verify_checksums,
)
from agent33.packs.manifest import PackManifest
from agent33.packs.models import PackSkillEntry


def _write_pack(tmp_path: Path, *, name: str = "test-pack") -> Path:
    """Create a minimal valid pack directory for testing."""
    pack_dir = tmp_path / name
    pack_dir.mkdir()

    # PACK.yaml
    (pack_dir / "PACK.yaml").write_text(
        textwrap.dedent(f"""\
        schema_version: "1"
        name: {name}
        version: 1.0.0
        description: Test pack
        author: tester
        skills:
          - name: my-skill
            path: skills/my-skill
        """),
        encoding="utf-8",
    )

    # Skill directory
    skill_dir = pack_dir / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent("""\
        ---
        name: my-skill
        version: 1.0.0
        description: A test skill
        ---
        # My Skill
        Do the thing.
        """),
        encoding="utf-8",
    )

    return pack_dir


class TestLoadPackManifest:
    """Test PACK.yaml loading from directories."""

    def test_load_valid_manifest(self, tmp_path: Path) -> None:
        pack_dir = _write_pack(tmp_path)
        manifest = load_pack_manifest(pack_dir)
        assert manifest.name == "test-pack"
        assert manifest.version == "1.0.0"
        assert len(manifest.skills) == 1

    def test_load_lowercase_filename(self, tmp_path: Path) -> None:
        """Accepts both PACK.yaml and pack.yaml."""
        pack_dir = tmp_path / "lc-pack"
        pack_dir.mkdir()
        (pack_dir / "pack.yaml").write_text(
            textwrap.dedent("""\
            name: lc-pack
            version: 1.0.0
            description: Lowercase
            author: tester
            skills:
              - name: s
                path: s
            """),
            encoding="utf-8",
        )
        manifest = load_pack_manifest(pack_dir)
        assert manifest.name == "lc-pack"

    def test_load_missing_manifest(self, tmp_path: Path) -> None:
        pack_dir = tmp_path / "empty"
        pack_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="No PACK.yaml"):
            load_pack_manifest(pack_dir)


class TestLoadPackSkills:
    """Test skill loading from pack directories."""

    def test_load_skills_success(self, tmp_path: Path) -> None:
        pack_dir = _write_pack(tmp_path)
        manifest = load_pack_manifest(pack_dir)
        skills, errors = load_pack_skills(pack_dir, manifest)
        assert len(skills) == 1
        assert skills[0].name == "my-skill"
        assert "Do the thing" in skills[0].instructions
        assert len(errors) == 0

    def test_required_skill_missing_produces_error(self, tmp_path: Path) -> None:
        pack_dir = tmp_path / "bad-pack"
        pack_dir.mkdir()
        manifest = PackManifest(
            name="bad-pack",
            version="1.0.0",
            description="Bad",
            author="tester",
            skills=[PackSkillEntry(name="missing", path="skills/missing", required=True)],
        )
        skills, errors = load_pack_skills(pack_dir, manifest)
        assert len(skills) == 0
        assert len(errors) == 1
        assert "missing" in errors[0]

    def test_optional_skill_missing_no_error(self, tmp_path: Path) -> None:
        pack_dir = tmp_path / "opt-pack"
        pack_dir.mkdir()
        manifest = PackManifest(
            name="opt-pack",
            version="1.0.0",
            description="Optional",
            author="tester",
            skills=[
                PackSkillEntry(name="missing", path="skills/missing", required=False),
            ],
        )
        skills, errors = load_pack_skills(pack_dir, manifest)
        assert len(skills) == 0
        assert len(errors) == 0  # no errors for optional skills

    def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        pack_dir = tmp_path / "traversal-pack"
        pack_dir.mkdir()
        manifest = PackManifest(
            name="traversal-pack",
            version="1.0.0",
            description="Traversal",
            author="tester",
            skills=[
                PackSkillEntry(name="evil", path="../../etc/passwd", required=True),
            ],
        )
        skills, errors = load_pack_skills(pack_dir, manifest)
        assert len(skills) == 0
        assert len(errors) == 1
        assert "Path traversal blocked" in errors[0]

    def test_multiple_skills_loaded(self, tmp_path: Path) -> None:
        pack_dir = tmp_path / "multi-pack"
        pack_dir.mkdir()
        (pack_dir / "PACK.yaml").write_text(
            textwrap.dedent("""\
            name: multi-pack
            version: 1.0.0
            description: Multi
            author: tester
            skills:
              - name: skill-a
                path: skills/skill-a
              - name: skill-b
                path: skills/skill-b
            """),
            encoding="utf-8",
        )
        for sname in ("skill-a", "skill-b"):
            sdir = pack_dir / "skills" / sname
            sdir.mkdir(parents=True)
            (sdir / "SKILL.md").write_text(
                textwrap.dedent(f"""\
                ---
                name: {sname}
                version: 1.0.0
                description: Skill {sname}
                ---
                # {sname}
                Instructions for {sname}.
                """),
                encoding="utf-8",
            )
        manifest = load_pack_manifest(pack_dir)
        skills, errors = load_pack_skills(pack_dir, manifest)
        assert len(skills) == 2
        assert len(errors) == 0
        assert {s.name for s in skills} == {"skill-a", "skill-b"}

    def test_repo_phase47_imported_packs_load_successfully(self) -> None:
        repo_packs_dir = Path(__file__).resolve().parents[1] / "packs"
        expected_packs = {"hive-family", "platform-builder", "workflow-ops"}

        discovered = {
            pack_dir.name
            for pack_dir in repo_packs_dir.iterdir()
            if (pack_dir / "PACK.yaml").is_file()
        }
        assert expected_packs.issubset(discovered)

        for pack_name in expected_packs:
            pack_dir = repo_packs_dir / pack_name
            manifest = load_pack_manifest(pack_dir)
            skills, errors = load_pack_skills(pack_dir, manifest)
            assert errors == []
            assert len(skills) == len(manifest.skills)


class TestValidatePackDirectory:
    """Test structural validation of pack directories."""

    def test_valid_directory(self, tmp_path: Path) -> None:
        pack_dir = _write_pack(tmp_path)
        errors = validate_pack_directory(pack_dir)
        assert errors == []

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        errors = validate_pack_directory(tmp_path / "nope")
        assert len(errors) == 1
        assert "does not exist" in errors[0]

    def test_missing_pack_yaml(self, tmp_path: Path) -> None:
        pack_dir = tmp_path / "no-yaml"
        pack_dir.mkdir()
        errors = validate_pack_directory(pack_dir)
        assert len(errors) == 1
        assert "No PACK.yaml" in errors[0]

    def test_missing_skill_path(self, tmp_path: Path) -> None:
        pack_dir = tmp_path / "missing-skill"
        pack_dir.mkdir()
        (pack_dir / "PACK.yaml").write_text(
            textwrap.dedent("""\
            name: missing-skill
            version: 1.0.0
            description: Missing
            author: tester
            skills:
              - name: ghost
                path: skills/ghost
            """),
            encoding="utf-8",
        )
        errors = validate_pack_directory(pack_dir)
        assert len(errors) == 1
        assert "not found" in errors[0]


class TestVerifyChecksums:
    """Test checksum verification."""

    def test_no_checksums_file(self, tmp_path: Path) -> None:
        """Missing CHECKSUMS.sha256 means skip (pass)."""
        valid, mismatches = verify_checksums(tmp_path)
        assert valid is True
        assert mismatches == []

    def test_valid_checksums(self, tmp_path: Path) -> None:
        content = b"hello world"
        (tmp_path / "test.txt").write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        (tmp_path / "CHECKSUMS.sha256").write_text(
            f"sha256:{expected}  test.txt\n", encoding="utf-8"
        )
        valid, mismatches = verify_checksums(tmp_path)
        assert valid is True
        assert mismatches == []

    def test_invalid_checksum(self, tmp_path: Path) -> None:
        (tmp_path / "test.txt").write_bytes(b"hello")
        (tmp_path / "CHECKSUMS.sha256").write_text(
            "sha256:0000000000000000  test.txt\n", encoding="utf-8"
        )
        valid, mismatches = verify_checksums(tmp_path)
        assert valid is False
        assert len(mismatches) == 1
        assert "mismatch" in mismatches[0].lower()

    def test_missing_file_in_checksums(self, tmp_path: Path) -> None:
        (tmp_path / "CHECKSUMS.sha256").write_text(
            "sha256:abc123  nonexistent.txt\n", encoding="utf-8"
        )
        valid, mismatches = verify_checksums(tmp_path)
        assert valid is False
        assert "not found" in mismatches[0].lower()

    def test_path_traversal_in_checksums_blocked(self, tmp_path: Path) -> None:
        (tmp_path / "CHECKSUMS.sha256").write_text(
            "sha256:abc123  ../outside.txt\n", encoding="utf-8"
        )
        valid, mismatches = verify_checksums(tmp_path)
        assert valid is False
        assert "path traversal" in mismatches[0].lower()


class TestComputePackChecksum:
    """Test pack checksum computation."""

    def test_deterministic(self, tmp_path: Path) -> None:
        pack_dir = _write_pack(tmp_path)
        checksum1 = compute_pack_checksum(pack_dir)
        checksum2 = compute_pack_checksum(pack_dir)
        assert checksum1 == checksum2
        assert checksum1.startswith("sha256:")

    def test_changes_with_content(self, tmp_path: Path) -> None:
        pack_dir = _write_pack(tmp_path)
        checksum_before = compute_pack_checksum(pack_dir)

        # Add a new file
        (pack_dir / "extra.txt").write_text("extra", encoding="utf-8")
        checksum_after = compute_pack_checksum(pack_dir)

        assert checksum_before != checksum_after
