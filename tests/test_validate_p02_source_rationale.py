from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_p02_source_rationale import validate


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _manifest(path: Path, files: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "manifest_id": "test",
                "coverage_groups": [
                    {
                        "id": "covered",
                        "sources": ["source.md"],
                        "rationale": "test rationale",
                        "files": files,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_missing_core_markdown_without_manifest_or_markers_fails(tmp_path: Path) -> None:
    _write(tmp_path / "core" / "covered.md", "# Covered\n")
    _write(tmp_path / "core" / "missing.md", "# Missing\n")
    _manifest(tmp_path / "core" / "P02_SOURCE_RATIONALE_MANIFEST.json", ["core/covered.md"])

    report = validate(tmp_path, tmp_path / "core" / "P02_SOURCE_RATIONALE_MANIFEST.json")

    assert report["healthy"] is False
    assert report["missingCoverage"] == ["core/missing.md"]


def test_direct_source_and_rationale_markers_satisfy_coverage(tmp_path: Path) -> None:
    _write(tmp_path / "core" / "covered.md", "# Covered\n")
    _write(
        tmp_path / "core" / "direct.md",
        "# Direct\n\nSources: source.md\n\nRationale: explicit markers\n",
    )
    _manifest(tmp_path / "core" / "P02_SOURCE_RATIONALE_MANIFEST.json", ["core/covered.md"])

    report = validate(tmp_path, tmp_path / "core" / "P02_SOURCE_RATIONALE_MANIFEST.json")

    assert report["healthy"] is True
    assert report["directMarkerCoverage"] == 1
    assert report["manifestCoverage"] == 1


def test_stale_manifest_file_fails(tmp_path: Path) -> None:
    _write(tmp_path / "core" / "covered.md", "# Covered\n")
    _manifest(
        tmp_path / "core" / "P02_SOURCE_RATIONALE_MANIFEST.json",
        ["core/covered.md", "core/deleted.md"],
    )

    report = validate(tmp_path, tmp_path / "core" / "P02_SOURCE_RATIONALE_MANIFEST.json")

    assert report["healthy"] is False
    assert report["staleManifestFiles"] == ["core/deleted.md"]
