"""Minimal Phase 23 smoke-server wrapper around the real AGENT-33 app."""

from __future__ import annotations

from pathlib import Path

from agent33.config import settings
from agent33.main import app
from agent33.phase23_lifecycle import install_phase23_lifecycle_repositories
from agent33.state_paths import RuntimeStatePaths

_state_paths = RuntimeStatePaths.from_app_root(Path.cwd().resolve())
app.state.runtime_state_paths = _state_paths
app.state.phase23_lifecycle_repositories = install_phase23_lifecycle_repositories(
    settings,
    _state_paths,
)
