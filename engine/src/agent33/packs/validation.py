"""Shared validators for pack manifest models."""

from __future__ import annotations

import re

PACK_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def validate_pack_name(value: str, *, entity: str = "Pack") -> str:
    """Validate a pack-style slug."""
    if not PACK_NAME_RE.match(value):
        raise ValueError(
            f"{entity} name '{value}' must be lowercase letters, digits, and hyphens "
            f"(1-64 chars, must start and end with letter or digit)"
        )
    return value


def validate_semver(value: str, *, entity: str = "Pack") -> str:
    """Validate MAJOR.MINOR.PATCH semver used by pack manifests."""
    if not SEMVER_RE.match(value):
        raise ValueError(f"{entity} version '{value}' must be valid semver (MAJOR.MINOR.PATCH)")
    return value


def validate_relative_pack_path(value: str, *, field_name: str) -> str:
    """Validate a portable, relative path inside a pack manifest."""
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    if value != value.strip():
        raise ValueError(f"{field_name} must not contain leading or trailing whitespace")
    if "\\" in value:
        raise ValueError(f"{field_name} must use forward slashes")
    if value.startswith("/") or ":" in value:
        raise ValueError(f"{field_name} must be relative")

    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(
            f"{field_name} must not contain empty, current-directory, or traversal segments"
        )
    return value
