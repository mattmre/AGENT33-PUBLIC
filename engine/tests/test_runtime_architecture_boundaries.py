"""Tests for the Cluster 0.1 runtime import-boundary contract."""

from __future__ import annotations

from pathlib import Path

from agent33.testing.import_boundaries import (
    collect_allowlisted_importers,
    collect_module_imports,
    evaluate_runtime_boundaries,
    format_violations,
)


def test_runtime_import_boundaries_match_current_tree() -> None:
    package_root = Path(__file__).resolve().parents[1] / "src" / "agent33"
    violations = evaluate_runtime_boundaries(package_root)
    assert not violations, format_violations(violations)


def test_runtime_boundary_allowlist_stays_explicit_and_small() -> None:
    assert collect_allowlisted_importers() == {
        "agent33.api.routes.training",
        "agent33.services.operations_hub",
    }


def test_core_runtime_rules_cover_skills_relative_imports(tmp_path: Path) -> None:
    package_root = tmp_path / "agent33"
    (package_root / "api").mkdir(parents=True)
    (package_root / "skills").mkdir(parents=True)
    (package_root / "api" / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "skills" / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "skills" / "demo.py").write_text(
        "from .. import api\n",
        encoding="utf-8",
    )

    violations = evaluate_runtime_boundaries(package_root)

    assert [(violation.importer, violation.imported) for violation in violations] == [
        ("agent33.skills.demo", "agent33.api")
    ]


def test_collect_module_imports_preserves_from_import_targets(tmp_path: Path) -> None:
    package_root = tmp_path / "agent33"
    (package_root / "api").mkdir(parents=True)
    (package_root / "skills").mkdir(parents=True)
    (package_root / "api" / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "skills" / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "skills" / "demo.py").write_text(
        "from agent33.api import routes\n",
        encoding="utf-8",
    )

    imports = list(collect_module_imports(package_root))

    assert [(module_name, imported) for module_name, imported, _path, _line in imports] == [
        ("agent33.skills.demo", "agent33.api.routes")
    ]
