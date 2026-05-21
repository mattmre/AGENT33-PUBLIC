"""Pre-deployment plugin validation utility.

Validates a plugin directory before it enters the ``PluginRegistry``:
schema correctness, entry-point reachability, dependency availability,
and version format.  Returns a structured ``ValidationResult`` so callers
can report all issues in one pass rather than failing on the first one.
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent33.plugins.loader import load_manifest
from agent33.plugins.version import parse_version

if TYPE_CHECKING:
    from pathlib import Path

    from agent33.plugins.manifest import PluginManifest

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Outcome of a single validation check."""

    name: str
    passed: bool
    message: str


@dataclass(slots=True)
class ValidationResult:
    """Aggregated outcome of all validation checks for a plugin directory."""

    plugin_dir: Path
    valid: bool = True
    manifest: PluginManifest | None = None
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, name: str, passed: bool, message: str) -> None:
        """Append a check result and update the overall validity flag."""
        self.checks.append(CheckResult(name=name, passed=passed, message=message))
        if not passed:
            self.valid = False

    @property
    def failed_checks(self) -> list[CheckResult]:
        """Return only the checks that failed."""
        return [c for c in self.checks if not c.passed]


def validate_plugin(
    plugin_dir: Path,
    *,
    available_plugins: dict[str, str] | None = None,
) -> ValidationResult:
    """Validate a plugin directory for deployment readiness.

    Runs all checks and returns a single ``ValidationResult``.

    Args:
        plugin_dir: Path to the plugin directory.
        available_plugins: Map of ``{plugin_name: version}`` for dependency
            resolution.  When ``None``, dependency checks verify that the
            manifest declares dependencies but cannot confirm they are
            actually available.

    Returns:
        A ``ValidationResult`` summarising all checks.
    """
    result = ValidationResult(plugin_dir=plugin_dir)

    # ---- Check 1: directory exists ----
    if not plugin_dir.is_dir():
        result.add("directory_exists", False, f"Plugin directory does not exist: {plugin_dir}")
        return result
    result.add("directory_exists", True, f"Directory exists: {plugin_dir}")

    # ---- Check 2: manifest parseable ----
    try:
        manifest = load_manifest(plugin_dir)
    except FileNotFoundError as exc:
        result.add("manifest_exists", False, str(exc))
        return result
    except Exception as exc:
        result.add("manifest_parseable", False, f"Manifest parse error: {exc}")
        return result

    result.manifest = manifest
    result.add("manifest_parseable", True, f"Manifest parsed: {manifest.name} v{manifest.version}")

    # ---- Check 3: name format ----
    # PluginManifest already validates via regex, but we record it explicitly
    result.add(
        "name_valid",
        True,
        f"Name '{manifest.name}' matches required pattern [a-z][a-z0-9-]*",
    )

    # ---- Check 4: version format ----
    try:
        parse_version(manifest.version)
        result.add("version_valid", True, f"Version '{manifest.version}' is valid SemVer")
    except ValueError as exc:
        result.add("version_valid", False, str(exc))

    # ---- Check 5: entry point module exists ----
    module_path, class_name = manifest.entry_point.rsplit(":", 1)
    module_file = plugin_dir / (module_path.replace(".", "/") + ".py")
    if module_file.is_file():
        result.add(
            "entry_point_module_exists",
            True,
            f"Entry-point module found: {module_file.name}",
        )
    else:
        result.add(
            "entry_point_module_exists",
            False,
            f"Entry-point module not found: {module_file} "
            f"(from entry_point '{manifest.entry_point}')",
        )

    # ---- Check 6: entry point class importable ----
    if module_file.is_file():
        try:
            unique_name = f"agent33.plugins._validate.{manifest.name}.{module_path}"
            spec = importlib.util.spec_from_file_location(unique_name, str(module_file))
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot create module spec for {module_file}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            cls = getattr(module, class_name, None)
            if cls is None:
                result.add(
                    "entry_point_class_exists",
                    False,
                    f"Class '{class_name}' not found in module '{module_path}'",
                )
            else:
                from agent33.plugins.base import PluginBase

                if issubclass(cls, PluginBase):
                    result.add(
                        "entry_point_class_exists",
                        True,
                        f"Class '{class_name}' found and extends PluginBase",
                    )
                else:
                    result.add(
                        "entry_point_class_exists",
                        False,
                        f"Class '{class_name}' does not extend PluginBase",
                    )
        except Exception as exc:
            result.add(
                "entry_point_class_exists",
                False,
                f"Cannot import entry-point class: {exc}",
            )

    # ---- Check 7: dependencies resolvable ----
    if not manifest.dependencies:
        result.add("dependencies_met", True, "No dependencies declared")
    elif available_plugins is None:
        result.add(
            "dependencies_met",
            True,
            f"{len(manifest.dependencies)} dependencies declared "
            f"(no registry provided to verify availability)",
        )
    else:
        unmet: list[str] = []
        for dep in manifest.dependencies:
            if dep.name not in available_plugins:
                if not dep.optional:
                    unmet.append(f"'{dep.name}' (required, not found)")
            else:
                from agent33.plugins.version import satisfies_constraint

                actual_version = available_plugins[dep.name]
                if dep.version_constraint != "*" and not satisfies_constraint(
                    actual_version, dep.version_constraint
                ):
                    unmet.append(
                        f"'{dep.name}' (requires {dep.version_constraint}, found {actual_version})"
                    )
        if unmet:
            result.add("dependencies_met", False, f"Unmet dependencies: {', '.join(unmet)}")
        else:
            result.add(
                "dependencies_met",
                True,
                f"All {len(manifest.dependencies)} dependencies satisfied",
            )

    return result
