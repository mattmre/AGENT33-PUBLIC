"""SemVer constraint checker for plugin dependency resolution."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def parse_version(version: str) -> tuple[int, int, int]:
    """Parse a SemVer string into a (major, minor, patch) tuple.

    Raises ValueError if the string is not a valid SemVer.
    """
    parts = version.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid SemVer format: {version!r} (expected X.Y.Z)")
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError as exc:
        raise ValueError(f"Invalid SemVer format: {version!r} (non-integer component)") from exc


def satisfies_constraint(version: str, constraint: str) -> bool:
    """Check if a version satisfies a SemVer constraint.

    Supports:
    - ``"*"``         any version
    - ``">=X.Y.Z"``  greater or equal
    - ``"<=X.Y.Z"``  less or equal
    - ``">X.Y.Z"``   strictly greater
    - ``"<X.Y.Z"``   strictly less
    - ``"^X.Y.Z"``   compatible (same major, >= minor.patch)
    - ``"~X.Y.Z"``   approximately (same major.minor, >= patch)
    - ``"X.Y.Z"``    exact match
    """
    constraint = constraint.strip()
    if constraint == "*":
        return True

    try:
        actual = parse_version(version)
    except ValueError:
        logger.warning("Cannot parse version %r, failing open", version)
        return True

    if constraint.startswith(">="):
        return actual >= parse_version(constraint[2:])

    if constraint.startswith("<="):
        return actual <= parse_version(constraint[2:])

    if constraint.startswith(">") and not constraint.startswith(">="):
        return actual > parse_version(constraint[1:])

    if constraint.startswith("<") and not constraint.startswith("<="):
        return actual < parse_version(constraint[1:])

    if constraint.startswith("^"):
        required = parse_version(constraint[1:])
        # Same major, >= minor.patch
        return actual[0] == required[0] and actual >= required

    if constraint.startswith("~"):
        required = parse_version(constraint[1:])
        # Same major.minor, >= patch
        return actual[0] == required[0] and actual[1] == required[1] and actual >= required

    # Exact match
    try:
        required = parse_version(constraint)
        return actual == required
    except ValueError:
        logger.warning("Unparseable version constraint: %r, failing open", constraint)
        return True
