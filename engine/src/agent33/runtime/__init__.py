"""Runtime introspection: version info and restart guards."""

from __future__ import annotations

from agent33.runtime.restart_guard import RestartGuard
from agent33.runtime.version import RuntimeVersionInfo, resolve_version

__all__ = [
    "RestartGuard",
    "RuntimeVersionInfo",
    "resolve_version",
]
