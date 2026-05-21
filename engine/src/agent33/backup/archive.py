"""Archive helpers for platform backups."""

from __future__ import annotations

import tarfile
from datetime import datetime  # noqa: TC003
from pathlib import Path, PurePosixPath

MANIFEST_FILENAME = "manifest.json"


def build_archive_stem(created_at: datetime, mode: str, short_id: str) -> str:
    """Return the lexical archive stem for a backup."""
    return f"agent33-backup-{created_at.strftime('%Y%m%d-%H%M%S')}-{mode}-{short_id}"


def write_tar_gz(source_dir: Path, destination: Path) -> None:
    """Write a tar.gz archive atomically."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_suffix(f"{destination.suffix}.tmp")
    with tarfile.open(tmp_path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        archive.add(source_dir, arcname=source_dir.name)
    tmp_path.replace(destination)


def is_safe_archive_member(name: str) -> bool:
    """Return True when a tar member path is safe to inspect."""
    path = PurePosixPath(name)
    if path.is_absolute():
        return False
    return all(part not in {"", ".", ".."} for part in path.parts)
