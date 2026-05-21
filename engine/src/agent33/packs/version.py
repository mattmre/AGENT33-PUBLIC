"""Semver constraint parsing, version comparison, and dependency resolution.

Supports the constraint syntax documented in the architecture:
  ^1.2.3   -- compatible with 1.x.x (>=1.2.3, <2.0.0)
  ~1.2.3   -- approximately (>=1.2.3, <1.3.0)
  >=1.0.0  -- greater than or equal
  <2.0.0   -- less than
  >=1.0.0, <2.0.0  -- range (comma-separated AND)
  1.2.3    -- exact version
  *        -- any version
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

import structlog

logger = structlog.get_logger()

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True, order=True)
class Version:
    """A parsed semantic version (MAJOR.MINOR.PATCH)."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def parse(cls, raw: str) -> Version:
        """Parse a version string like '1.2.3'.

        Raises ValueError if the format is invalid.
        """
        match = _SEMVER_RE.match(raw.strip())
        if not match:
            raise ValueError(f"Invalid semver: '{raw}' (expected MAJOR.MINOR.PATCH)")
        return cls(
            major=int(match.group(1)),
            minor=int(match.group(2)),
            patch=int(match.group(3)),
        )


@dataclass(frozen=True)
class VersionRange:
    """A single comparison (e.g. >= 1.0.0 or < 2.0.0)."""

    operator: str  # ">=", "<=", ">", "<", "="
    version: Version

    def contains(self, v: Version) -> bool:
        """Check if version v satisfies this range."""
        if self.operator == ">=":
            return v >= self.version
        if self.operator == "<=":
            return v <= self.version
        if self.operator == ">":
            return v > self.version
        if self.operator == "<":
            return v < self.version
        if self.operator == "=":
            return v == self.version
        raise ValueError(f"Unknown operator: {self.operator}")


@dataclass(frozen=True)
class VersionConstraint:
    """A parsed semver constraint (may contain multiple ranges ANDed together)."""

    raw: str
    ranges: tuple[VersionRange, ...]

    def satisfies(self, version: Version) -> bool:
        """Check if a concrete version satisfies all ranges in this constraint."""
        return all(r.contains(version) for r in self.ranges)

    @classmethod
    def parse(cls, raw: str) -> VersionConstraint:
        """Parse a constraint string into ranges.

        Supports: ^, ~, >=, <=, >, <, =, exact version, * (any).
        Comma-separated constraints are ANDed.
        """
        raw = raw.strip()

        if raw == "*":
            return cls(raw=raw, ranges=())

        # Split on comma for AND constraints
        parts = [p.strip() for p in raw.split(",")]
        all_ranges: list[VersionRange] = []

        for part in parts:
            ranges = _parse_single_constraint(part)
            all_ranges.extend(ranges)

        return cls(raw=raw, ranges=tuple(all_ranges))


def _parse_single_constraint(part: str) -> list[VersionRange]:
    """Parse a single constraint part (no commas)."""
    part = part.strip()

    if part.startswith("^"):
        # Caret: >=version, <next_major
        ver = Version.parse(part[1:])
        return [
            VersionRange(">=", ver),
            VersionRange("<", Version(ver.major + 1, 0, 0)),
        ]

    if part.startswith("~"):
        # Tilde: >=version, <next_minor
        ver = Version.parse(part[1:])
        return [
            VersionRange(">=", ver),
            VersionRange("<", Version(ver.major, ver.minor + 1, 0)),
        ]

    if part.startswith(">="):
        ver = Version.parse(part[2:])
        return [VersionRange(">=", ver)]

    if part.startswith("<="):
        ver = Version.parse(part[2:])
        return [VersionRange("<=", ver)]

    if part.startswith(">"):
        ver = Version.parse(part[1:])
        return [VersionRange(">", ver)]

    if part.startswith("<"):
        ver = Version.parse(part[1:])
        return [VersionRange("<", ver)]

    if part.startswith("="):
        ver = Version.parse(part[1:])
        return [VersionRange("=", ver)]

    # Exact version (no operator)
    ver = Version.parse(part)
    return [VersionRange("=", ver)]


@dataclass(frozen=True)
class ConflictDetail:
    """Describes a dependency conflict."""

    package: str
    required_by: dict[str, str]  # {requirer_name: constraint_string}
    available_versions: list[str]
    reason: str


@dataclass
class ResolutionResult:
    """Outcome of dependency resolution."""

    resolved: dict[str, str] | None  # {pack_name: version} if successful
    conflicts: list[ConflictDetail] = field(default_factory=list)
    graph: dict[str, list[str]] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.resolved is not None and len(self.conflicts) == 0


class DependencyResolver:
    """Resolve pack dependencies using greedy backtracking.

    The resolver operates on the set of installed packs to check if
    requirements can be satisfied.
    """

    def __init__(self, available_packs: dict[str, list[str]] | None = None) -> None:
        """Initialize with available packs and their versions.

        Args:
            available_packs: mapping of pack_name -> list of available version strings
        """
        self._available: dict[str, list[Version]] = {}
        if available_packs:
            for name, versions in available_packs.items():
                parsed = sorted([Version.parse(v) for v in versions], reverse=True)
                self._available[name] = parsed

    def add_available(self, name: str, version: str) -> None:
        """Register an available pack version."""
        ver = Version.parse(version)
        if name not in self._available:
            self._available[name] = []
        if ver not in self._available[name]:
            self._available[name].append(ver)
            self._available[name].sort(reverse=True)

    def resolve(
        self,
        requirements: list[tuple[str, str]],
    ) -> ResolutionResult:
        """Resolve a set of requirements to concrete versions.

        Args:
            requirements: list of (pack_name, constraint_string) tuples

        Returns:
            ResolutionResult with resolved versions or conflict details.
        """
        resolved: dict[str, str] = {}
        constraints_by_name: dict[str, dict[str, str]] = {}
        graph: dict[str, list[str]] = {}
        conflicts: list[ConflictDetail] = []

        # Track who requires what
        for req_name, constraint_str in requirements:
            if req_name not in constraints_by_name:
                constraints_by_name[req_name] = {}
            constraints_by_name[req_name]["root"] = constraint_str

        # Check for circular dependencies (simple detection)
        visited: set[str] = set()

        def _resolve_one(name: str, constraint_str: str, requirer: str) -> bool:
            if name in visited and name not in resolved:
                conflicts.append(
                    ConflictDetail(
                        package=name,
                        required_by=constraints_by_name.get(name, {}),
                        available_versions=[str(v) for v in self._available.get(name, [])],
                        reason=f"Circular dependency detected: {requirer} -> {name}",
                    )
                )
                return False

            visited.add(name)

            constraint = VersionConstraint.parse(constraint_str)

            if name in resolved:
                # Already resolved -- check compatibility
                existing_ver = Version.parse(resolved[name])
                if constraint.satisfies(existing_ver):
                    return True
                # Incompatible with existing resolution
                if name not in constraints_by_name:
                    constraints_by_name[name] = {}
                constraints_by_name[name][requirer] = constraint_str
                conflicts.append(
                    ConflictDetail(
                        package=name,
                        required_by=constraints_by_name[name],
                        available_versions=[str(v) for v in self._available.get(name, [])],
                        reason=(
                            f"Version conflict: already resolved to {resolved[name]} "
                            f"but {requirer} requires {constraint_str}"
                        ),
                    )
                )
                return False

            available = self._available.get(name, [])
            if not available:
                if name not in constraints_by_name:
                    constraints_by_name[name] = {}
                constraints_by_name[name][requirer] = constraint_str
                conflicts.append(
                    ConflictDetail(
                        package=name,
                        required_by=constraints_by_name[name],
                        available_versions=[],
                        reason=f"Pack '{name}' not found in any registry",
                    )
                )
                return False

            # Select highest version satisfying constraint
            for ver in available:
                if constraint.satisfies(ver):
                    resolved[name] = str(ver)
                    if requirer not in graph:
                        graph[requirer] = []
                    graph[requirer].append(name)
                    return True

            # No version satisfies
            if name not in constraints_by_name:
                constraints_by_name[name] = {}
            constraints_by_name[name][requirer] = constraint_str
            conflicts.append(
                ConflictDetail(
                    package=name,
                    required_by=constraints_by_name[name],
                    available_versions=[str(v) for v in available],
                    reason=(
                        f"No version of '{name}' satisfies constraint "
                        f"'{constraint_str}' (available: {[str(v) for v in available]})"
                    ),
                )
            )
            return False

        for req_name, constraint_str in requirements:
            _resolve_one(req_name, constraint_str, "root")

        if conflicts:
            return ResolutionResult(resolved=None, conflicts=conflicts, graph=graph)

        return ResolutionResult(resolved=resolved, conflicts=[], graph=graph)


def generate_lock_content(
    resolved: dict[str, str],
    engine_version: str = "0.1.0",
    sources: dict[str, str] | None = None,
    constraints: dict[str, str] | None = None,
    checksums: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Generate the content of a PACK.lock file.

    Returns a dictionary suitable for YAML serialization.
    """
    from datetime import datetime

    packages: dict[str, dict[str, str]] = {}
    for name, version in sorted(resolved.items()):
        entry: dict[str, str] = {"version": version}
        if checksums and name in checksums:
            entry["checksum"] = checksums[name]
        if sources and name in sources:
            entry["source"] = sources[name]
        else:
            entry["source"] = "local"
        if constraints and name in constraints:
            entry["resolved_from"] = constraints[name]
        packages[name] = entry

    return {
        "lock_version": "1",
        "engine_version": engine_version,
        "resolved_at": datetime.now(UTC).isoformat(),
        "resolver": "greedy-backtrack-v1",
        "packages": packages,
    }


def parse_lock_content(data: dict[str, Any]) -> dict[str, str]:
    """Parse a PACK.lock file content into a {name: version} mapping."""
    packages = data.get("packages", {})
    result: dict[str, str] = {}
    for name, info in packages.items():
        if isinstance(info, dict):
            result[name] = info.get("version", "")
        elif isinstance(info, str):
            result[name] = info
    return result
