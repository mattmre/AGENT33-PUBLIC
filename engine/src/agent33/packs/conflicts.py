"""Version conflict detection and resolution between installed packs.

Detects skill name overlaps and version range incompatibilities when
multiple packs are present, and provides resolution strategies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import structlog

from agent33.packs.version import Version, VersionConstraint

if TYPE_CHECKING:
    from agent33.packs.manifest import PackManifest

logger = structlog.get_logger()


class ConflictKind(StrEnum):
    """Classification of a version/pack conflict."""

    SKILL_NAME_OVERLAP = "skill_name_overlap"
    VERSION_RANGE_INCOMPATIBLE = "version_range_incompatible"
    DEPENDENCY_MISMATCH = "dependency_mismatch"


@dataclass(frozen=True)
class VersionConflict:
    """A detected conflict between two packs."""

    kind: ConflictKind
    pack_a: str
    pack_b: str
    detail: str
    skill_name: str = ""
    constraint_a: str = ""
    constraint_b: str = ""


class ResolutionAction(StrEnum):
    """Action taken to resolve a conflict."""

    USE_A = "use_a"
    USE_B = "use_b"
    REJECT = "reject"
    MANUAL = "manual"


@dataclass(frozen=True)
class Resolution:
    """Outcome of resolving a single conflict."""

    conflict: VersionConflict
    action: ResolutionAction
    chosen_pack: str = ""
    reason: str = ""


def detect_conflicts(
    pack_a: PackManifest,
    pack_b: PackManifest,
) -> list[VersionConflict]:
    """Detect conflicts between two pack manifests.

    Checks for:
    - Skill name overlaps (both packs declare a skill with the same name)
    - Version range incompatibilities in shared dependencies

    Args:
        pack_a: First pack manifest.
        pack_b: Second pack manifest.

    Returns:
        List of detected conflicts (empty if none).
    """
    conflicts: list[VersionConflict] = []

    # --- Skill name overlaps ---
    skills_a = {s.name for s in pack_a.skills}
    skills_b = {s.name for s in pack_b.skills}
    overlapping = skills_a & skills_b

    for skill_name in sorted(overlapping):
        conflicts.append(
            VersionConflict(
                kind=ConflictKind.SKILL_NAME_OVERLAP,
                pack_a=pack_a.name,
                pack_b=pack_b.name,
                skill_name=skill_name,
                detail=(
                    f"Skill '{skill_name}' is declared in both '{pack_a.name}' and '{pack_b.name}'"
                ),
            )
        )

    # --- Shared dependency version range incompatibilities ---
    deps_a = {d.name: d.version_constraint for d in pack_a.dependencies.packs}
    deps_b = {d.name: d.version_constraint for d in pack_b.dependencies.packs}
    shared_deps = set(deps_a.keys()) & set(deps_b.keys())

    for dep_name in sorted(shared_deps):
        constraint_a_str = deps_a[dep_name]
        constraint_b_str = deps_b[dep_name]

        constraint_a = VersionConstraint.parse(constraint_a_str)
        constraint_b = VersionConstraint.parse(constraint_b_str)

        # Check if there is any overlap: try a range of plausible versions
        if not _constraints_overlap(constraint_a, constraint_b):
            conflicts.append(
                VersionConflict(
                    kind=ConflictKind.VERSION_RANGE_INCOMPATIBLE,
                    pack_a=pack_a.name,
                    pack_b=pack_b.name,
                    detail=(
                        f"Dependency '{dep_name}': constraint '{constraint_a_str}' "
                        f"(from '{pack_a.name}') is incompatible with "
                        f"'{constraint_b_str}' (from '{pack_b.name}')"
                    ),
                    constraint_a=constraint_a_str,
                    constraint_b=constraint_b_str,
                )
            )

    if conflicts:
        logger.info(
            "pack_conflicts_detected",
            pack_a=pack_a.name,
            pack_b=pack_b.name,
            count=len(conflicts),
        )

    return conflicts


def _constraints_overlap(a: VersionConstraint, b: VersionConstraint) -> bool:
    """Check whether two version constraints have any overlapping versions.

    Uses a brute-force probe of common version numbers up to 20.x.x.
    This is a pragmatic approach for the constraint syntax we support;
    a full interval-intersection algorithm is unnecessary at this stage.
    """
    # Wildcard constraints overlap with everything
    if not a.ranges or not b.ranges:
        return True

    for major in range(21):
        for minor in range(21):
            for patch in range(6):
                v = Version(major, minor, patch)
                if a.satisfies(v) and b.satisfies(v):
                    return True
    return False


def resolve_conflicts(
    conflicts: list[VersionConflict],
    strategy: str = "latest",
    *,
    versions: dict[str, str] | None = None,
) -> list[Resolution]:
    """Resolve a list of conflicts using the given strategy.

    Strategies:
        - ``"latest"``: Prefer the pack with the higher version.
          Requires ``versions`` dict mapping pack name to version string.
        - ``"manual"``: Mark every conflict as requiring manual resolution.
        - ``"reject"``: Reject all conflicts outright (no resolution possible).

    Args:
        conflicts: List of conflicts to resolve.
        strategy: Resolution strategy name.
        versions: Mapping of pack name → version string (for "latest" strategy).

    Returns:
        List of Resolution objects, one per conflict.

    Raises:
        ValueError: If strategy is unknown.
    """
    if strategy not in ("latest", "manual", "reject"):
        raise ValueError(
            f"Unknown conflict resolution strategy '{strategy}'. "
            f"Supported: 'latest', 'manual', 'reject'"
        )

    resolutions: list[Resolution] = []

    for conflict in conflicts:
        if strategy == "reject":
            resolutions.append(
                Resolution(
                    conflict=conflict,
                    action=ResolutionAction.REJECT,
                    reason="Policy rejects all conflicts",
                )
            )
        elif strategy == "manual":
            resolutions.append(
                Resolution(
                    conflict=conflict,
                    action=ResolutionAction.MANUAL,
                    reason="Conflict requires manual resolution",
                )
            )
        elif strategy == "latest":
            resolution = _resolve_by_latest(conflict, versions or {})
            resolutions.append(resolution)

    return resolutions


def _resolve_by_latest(
    conflict: VersionConflict,
    versions: dict[str, str],
) -> Resolution:
    """Resolve a conflict by preferring the pack with the higher version."""
    ver_a_str = versions.get(conflict.pack_a)
    ver_b_str = versions.get(conflict.pack_b)

    if ver_a_str is None or ver_b_str is None:
        return Resolution(
            conflict=conflict,
            action=ResolutionAction.MANUAL,
            reason=(
                f"Cannot apply 'latest' strategy: missing version info for "
                f"'{conflict.pack_a if ver_a_str is None else conflict.pack_b}'"
            ),
        )

    try:
        ver_a = Version.parse(ver_a_str)
        ver_b = Version.parse(ver_b_str)
    except ValueError as exc:
        return Resolution(
            conflict=conflict,
            action=ResolutionAction.MANUAL,
            reason=f"Cannot parse version for 'latest' strategy: {exc}",
        )

    if ver_a >= ver_b:
        return Resolution(
            conflict=conflict,
            action=ResolutionAction.USE_A,
            chosen_pack=conflict.pack_a,
            reason=f"Pack '{conflict.pack_a}' v{ver_a} >= '{conflict.pack_b}' v{ver_b}",
        )
    else:
        return Resolution(
            conflict=conflict,
            action=ResolutionAction.USE_B,
            chosen_pack=conflict.pack_b,
            reason=f"Pack '{conflict.pack_b}' v{ver_b} > '{conflict.pack_a}' v{ver_a}",
        )
