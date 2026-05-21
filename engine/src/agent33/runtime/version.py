"""Runtime version information resolver."""

from __future__ import annotations

import contextlib
import importlib.metadata
import subprocess
import sys

from pydantic import BaseModel


class RuntimeVersionInfo(BaseModel):
    """Snapshot of the engine's runtime identity."""

    version: str = "0.1.0"
    git_short_hash: str = ""
    python_version: str = ""
    platform: str = ""


def resolve_version() -> RuntimeVersionInfo:
    """Build a :class:`RuntimeVersionInfo` from the running environment.

    - Tries ``git rev-parse --short HEAD`` for the git hash.
    - Reads ``sys.version`` and ``sys.platform``.
    - Attempts ``importlib.metadata.version("agent33")`` for the package version.
    """
    git_hash = ""
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            git_hash = result.stdout.strip()
    except Exception:  # noqa: BLE001
        pass

    pkg_version = "0.1.0"
    with contextlib.suppress(importlib.metadata.PackageNotFoundError):
        pkg_version = importlib.metadata.version("agent33")

    return RuntimeVersionInfo(
        version=pkg_version,
        git_short_hash=git_hash,
        python_version=sys.version,
        platform=sys.platform,
    )
