"""Pack loading: parse PACK.yaml, validate directory structure, load skills.

The loader is responsible for turning a pack directory on disk into
validated data structures (PackManifest, list of loaded SkillDefinitions).
It delegates to the existing skills loader for individual skill files.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import TYPE_CHECKING

import structlog

from agent33.packs.manifest import PackManifest, parse_pack_yaml

if TYPE_CHECKING:
    from pathlib import Path

    from agent33.skills.definition import SkillDefinition

logger = structlog.get_logger()


def load_pack_manifest(pack_dir: Path) -> PackManifest:
    """Parse and validate the PACK.yaml in a pack directory.

    Args:
        pack_dir: Directory containing PACK.yaml.

    Returns:
        Validated PackManifest.

    Raises:
        FileNotFoundError: If PACK.yaml is not found.
        ValueError: If the manifest is invalid.
    """
    manifest_path = pack_dir / "PACK.yaml"
    if not manifest_path.is_file():
        # Also try lowercase
        manifest_path = pack_dir / "pack.yaml"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"No PACK.yaml found in {pack_dir}")

    return parse_pack_yaml(manifest_path)


def load_pack_skills(
    pack_dir: Path,
    manifest: PackManifest,
) -> tuple[list[SkillDefinition], list[str]]:
    """Load all skill definitions declared in a pack manifest.

    Uses the existing skills loader module to parse each skill from
    its declared path.

    Args:
        pack_dir: Root directory of the pack.
        manifest: Parsed pack manifest.

    Returns:
        Tuple of (loaded_skills, error_messages).
        Required skills that fail to load produce errors.
        Optional skills that fail produce warnings logged but not errors.
    """
    from agent33.skills.loader import (
        load_from_directory,
        load_from_skillmd,
        load_from_yaml,
    )

    loaded: list[SkillDefinition] = []
    errors: list[str] = []

    for skill_entry in manifest.skills:
        skill_path = (pack_dir / skill_entry.path).resolve()

        # Path traversal protection
        try:
            skill_path.relative_to(pack_dir.resolve())
        except ValueError:
            msg = (
                f"Path traversal blocked: skill '{skill_entry.name}' "
                f"path '{skill_entry.path}' escapes pack directory"
            )
            if skill_entry.required:
                errors.append(msg)
            else:
                logger.warning("pack_skill_path_traversal", msg=msg)
            continue

        try:
            if skill_path.is_dir():
                skill = load_from_directory(skill_path)
            elif skill_path.suffix == ".md" and skill_path.name.upper() == "SKILL.MD":
                skill = load_from_skillmd(skill_path)
            elif skill_path.suffix in (".yaml", ".yml"):
                skill = load_from_yaml(skill_path)
            elif skill_path.is_dir():
                skill = load_from_directory(skill_path)
            else:
                # Try as directory
                if skill_path.is_dir():
                    skill = load_from_directory(skill_path)
                else:
                    raise FileNotFoundError(
                        f"Skill path '{skill_path}' is not a directory or recognized file"
                    )

            # Override description if provided in manifest
            if skill_entry.description and not skill.description:
                skill = skill.model_copy(update={"description": skill_entry.description})

            loaded.append(skill)
            logger.debug(
                "pack_skill_loaded",
                pack=manifest.name,
                skill=skill.name,
                version=skill.version,
            )
        except Exception as exc:
            msg = f"Failed to load skill '{skill_entry.name}' from '{skill_entry.path}': {exc}"
            if skill_entry.required:
                errors.append(msg)
                logger.error("pack_required_skill_load_failed", error=msg)
            else:
                logger.warning("pack_optional_skill_load_failed", error=msg)

    return loaded, errors


def validate_pack_directory(pack_dir: Path) -> list[str]:
    """Validate the structure of a pack directory.

    Checks:
    - PACK.yaml exists and is valid
    - All declared skill paths exist
    - No path traversal in skill paths

    Returns a list of validation error messages (empty = valid).
    """
    errors: list[str] = []

    if not pack_dir.is_dir():
        return [f"Pack directory does not exist: {pack_dir}"]

    manifest_path = pack_dir / "PACK.yaml"
    if not manifest_path.is_file():
        manifest_path = pack_dir / "pack.yaml"
        if not manifest_path.is_file():
            return [f"No PACK.yaml found in {pack_dir}"]

    try:
        manifest = parse_pack_yaml(manifest_path)
    except (ValueError, FileNotFoundError) as exc:
        return [f"Invalid PACK.yaml: {exc}"]

    for skill_entry in manifest.skills:
        skill_path = (pack_dir / skill_entry.path).resolve()

        # Path traversal check
        try:
            skill_path.relative_to(pack_dir.resolve())
        except ValueError:
            errors.append(
                f"Path traversal: skill '{skill_entry.name}' "
                f"path '{skill_entry.path}' escapes pack directory"
            )
            continue

        if not skill_path.exists():
            errors.append(
                f"Skill path not found: '{skill_entry.path}' for skill '{skill_entry.name}'"
            )

    return errors


def verify_checksums(pack_dir: Path) -> tuple[bool, list[str]]:
    """Verify checksums for a pack directory.

    Reads CHECKSUMS.sha256 and verifies each listed file.

    Returns:
        Tuple of (all_valid, list_of_mismatches).
        If CHECKSUMS.sha256 does not exist, returns (True, []).
    """
    checksums_file = pack_dir / "CHECKSUMS.sha256"
    if not checksums_file.is_file():
        return True, []

    mismatches: list[str] = []
    content = checksums_file.read_text(encoding="utf-8")

    for line in content.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split(None, 1)
        if len(parts) != 2:
            mismatches.append(f"Malformed checksum line: {line}")
            continue

        expected_hash, file_path = parts

        # Strip sha256: prefix if present
        if expected_hash.startswith("sha256:"):
            expected_hash = expected_hash[7:]

        target = (pack_dir / file_path).resolve()

        # Path traversal check
        try:
            target.relative_to(pack_dir.resolve())
        except ValueError:
            mismatches.append(f"Path traversal in checksum: {file_path}")
            continue

        if not target.is_file():
            mismatches.append(f"File not found: {file_path}")
            continue

        actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if not hmac.compare_digest(actual_hash, expected_hash):
            mismatches.append(
                f"Checksum mismatch for {file_path}: "
                f"expected {expected_hash[:16]}..., got {actual_hash[:16]}..."
            )

    return len(mismatches) == 0, mismatches


def compute_pack_checksum(pack_dir: Path) -> str:
    """Compute an overall SHA-256 checksum of the pack contents.

    Hashes PACK.yaml and all skill files in sorted order for determinism.
    """
    hasher = hashlib.sha256()

    files_to_hash: list[Path] = []
    for p in sorted(pack_dir.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            files_to_hash.append(p)

    for fpath in files_to_hash:
        rel = fpath.relative_to(pack_dir).as_posix()
        hasher.update(rel.encode("utf-8"))
        hasher.update(fpath.read_bytes())

    return f"sha256:{hasher.hexdigest()}"
