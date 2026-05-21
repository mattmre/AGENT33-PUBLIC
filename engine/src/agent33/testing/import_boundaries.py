"""Runtime import-boundary checks for the AGENT-33 engine."""

from __future__ import annotations

import ast
import importlib.util
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@dataclass(frozen=True)
class BoundaryRule:
    """One directional import-boundary rule."""

    name: str
    importer_prefixes: tuple[str, ...]
    forbidden_prefixes: tuple[str, ...]
    allowed_importers: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class BoundaryViolation:
    """A concrete import that violates a boundary rule."""

    rule_name: str
    importer: str
    imported: str
    path: str
    line: int
    description: str


APP_SHELL_PREFIXES = (
    "agent33.api",
    "agent33.cli",
    "agent33.main",
    "agent33.mcp_server",
)

CORE_RUNTIME_PREFIXES = (
    "agent33.agents",
    "agent33.execution",
    "agent33.llm",
    "agent33.memory",
    "agent33.security",
    "agent33.skills",
    "agent33.tools",
    "agent33.workflows",
)

SERVICE_PREFIXES = ("agent33.services",)

RUNTIME_BOUNDARY_RULES: tuple[BoundaryRule, ...] = (
    BoundaryRule(
        name="core-runtime-no-app-shell",
        importer_prefixes=CORE_RUNTIME_PREFIXES,
        forbidden_prefixes=APP_SHELL_PREFIXES,
        description=(
            "Core runtime packages must stay independent from FastAPI routes, the CLI, "
            "the MCP server shell, and main.py wiring."
        ),
    ),
    BoundaryRule(
        name="services-no-api-routes",
        importer_prefixes=SERVICE_PREFIXES,
        forbidden_prefixes=("agent33.api.routes",),
        allowed_importers=("agent33.services.operations_hub",),
        description=(
            "Service modules should not reach upward into FastAPI route helpers. "
            "Inject route dependencies instead."
        ),
    ),
    BoundaryRule(
        name="routes-no-main",
        importer_prefixes=("agent33.api.routes",),
        forbidden_prefixes=("agent33.main",),
        allowed_importers=("agent33.api.routes.training",),
        description=(
            "Route modules should not import main.py directly. Read app state through "
            "request-scoped dependencies instead."
        ),
    ),
)


def collect_allowlisted_importers() -> set[str]:
    """Return the explicit importer allowlist used by the boundary checker."""
    allowlisted: set[str] = set()
    for rule in RUNTIME_BOUNDARY_RULES:
        allowlisted.update(rule.allowed_importers)
    return allowlisted


class _ImportCollector(ast.NodeVisitor):
    """Collect absolute import targets from a Python module."""

    def __init__(self, module_name: str, package_context: str) -> None:
        self.module_name = module_name
        self.package_context = package_context
        self.imports: list[tuple[str, int]] = []

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        if _is_type_checking_guard(node.test):
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self.imports.append((alias.name, node.lineno))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        self.imports.extend(
            (resolved, node.lineno)
            for resolved in _resolve_from_import_targets(self.package_context, node)
        )


def _is_type_checking_guard(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "TYPE_CHECKING"
        and isinstance(node.value, ast.Name)
        and node.value.id == "typing"
    )


def _resolve_from_import_targets(package_context: str, node: ast.ImportFrom) -> list[str]:
    module = node.module or ""
    if node.level == 0:
        base_name = module or None
    else:
        relative_name = "." * node.level + module
        try:
            base_name = importlib.util.resolve_name(relative_name, package_context)
        except ImportError:
            return []
    if base_name is None:
        return []
    if any(alias.name == "*" for alias in node.names):
        return [base_name]
    return [f"{base_name}.{alias.name}" for alias in node.names]


def _module_name_for_path(package_root: Path, file_path: Path) -> str:
    rel = file_path.relative_to(package_root)
    parts = rel.with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join((package_root.name, *parts))


def iter_python_modules(package_root: Path) -> Iterator[tuple[str, Path]]:
    """Yield module names and file paths under the package root."""
    for file_path in sorted(package_root.rglob("*.py")):
        module_name = _module_name_for_path(package_root, file_path)
        yield module_name, file_path


def collect_module_imports(package_root: Path) -> Iterator[tuple[str, str, Path, int]]:
    """Yield all absolute imports inside the runtime package."""
    for module_name, file_path in iter_python_modules(package_root):
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        package_context = (
            module_name if file_path.stem == "__init__" else module_name.rsplit(".", 1)[0]
        )
        collector = _ImportCollector(module_name, package_context)
        collector.visit(tree)
        for imported, line in collector.imports:
            yield module_name, imported, file_path, line


def evaluate_runtime_boundaries(package_root: Path) -> list[BoundaryViolation]:
    """Return all import-boundary violations under ``package_root``."""
    violations: list[BoundaryViolation] = []
    for importer, imported, file_path, line in collect_module_imports(package_root):
        if not imported.startswith("agent33."):
            continue
        for rule in RUNTIME_BOUNDARY_RULES:
            if importer in rule.allowed_importers:
                continue
            if not _matches_any_prefix(importer, rule.importer_prefixes):
                continue
            if not _matches_any_prefix(imported, rule.forbidden_prefixes):
                continue
            violations.append(
                BoundaryViolation(
                    rule_name=rule.name,
                    importer=importer,
                    imported=imported,
                    path=str(file_path),
                    line=line,
                    description=rule.description,
                )
            )
    return violations


def format_violations(violations: list[BoundaryViolation]) -> str:
    """Render violations for pytest and CI output."""
    if not violations:
        return "No runtime import-boundary violations found."
    lines = ["Runtime import-boundary violations:"]
    for violation in violations:
        lines.append(
            f"- [{violation.rule_name}] {violation.importer} -> {violation.imported} "
            f"at {violation.path}:{violation.line}"
        )
        if violation.description:
            lines.append(f"  {violation.description}")
    return "\n".join(lines)


def _matches_any_prefix(value: str, prefixes: tuple[str, ...]) -> bool:
    return any(value == prefix or value.startswith(f"{prefix}.") for prefix in prefixes)
