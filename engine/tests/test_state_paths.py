"""Tests for canonical runtime durable state roots."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agent33.state_paths import (
    RuntimeStatePaths,
    RuntimeStatePathSpec,
    StatePathError,
    StateRootKind,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_resolve_repo_relative_var_path(tmp_path: Path) -> None:
    state_paths = RuntimeStatePaths.from_app_root(tmp_path, home_dir=tmp_path / "home")

    resolved = state_paths.resolve_approved("var/process-manager")

    assert resolved == (tmp_path / "var" / "process-manager").resolve()
    assert state_paths.classify(resolved) == StateRootKind.APP_VAR


def test_default_user_state_dir_uses_home_override(tmp_path: Path) -> None:
    state_paths = RuntimeStatePaths.from_app_root(tmp_path, home_dir=tmp_path / "home")

    assert (
        state_paths.default_user_state_dir("sessions")
        == (tmp_path / "home" / ".agent33" / "sessions").resolve()
    )


def test_resolve_repo_relative_trajectory_dir_is_approved(tmp_path: Path) -> None:
    state_paths = RuntimeStatePaths.from_app_root(tmp_path, home_dir=tmp_path / "home")

    resolved = state_paths.resolve_approved("trajectories")

    assert resolved == (tmp_path / "trajectories").resolve()
    assert state_paths.classify(resolved) == StateRootKind.APP_ROOT


def test_reject_path_outside_approved_roots(tmp_path: Path) -> None:
    outside_root = tmp_path.parent / "outside"
    state_paths = RuntimeStatePaths.from_app_root(tmp_path, home_dir=tmp_path / "home")

    with pytest.raises(StatePathError):
        state_paths.resolve_approved(outside_root / "escape.json")


def test_default_user_state_dir_rejects_traversal(tmp_path: Path) -> None:
    state_paths = RuntimeStatePaths.from_app_root(tmp_path, home_dir=tmp_path / "home")

    with pytest.raises(StatePathError):
        state_paths.default_user_state_dir("../escape")


class _AuditSettings:
    p69b_db_path = "var/p69b.db"
    operator_session_base_dir = ""
    trajectory_output_dir = "trajectories"
    unsafe_path = "../outside/state.db"
    disabled_path = ""


def test_state_path_audit_classifies_restart_safe_configured_paths(tmp_path: Path) -> None:
    state_paths = RuntimeStatePaths.from_app_root(tmp_path, home_dir=tmp_path / "home")

    audit = state_paths.audit_configured_state_paths(
        _AuditSettings(),
        specs=(
            RuntimeStatePathSpec("p69b", "Paused approvals", "p69b_db_path"),
            RuntimeStatePathSpec("sessions", "Operator sessions", "operator_session_base_dir"),
            RuntimeStatePathSpec("trajectory", "Trajectory output", "trajectory_output_dir"),
        ),
    )

    assert audit.overall == "ok"
    assert audit.restart_safe is True
    assert [item.root for item in audit.items] == [
        StateRootKind.APP_VAR,
        StateRootKind.USER_STATE,
        StateRootKind.APP_ROOT,
    ]
    assert all(item.restart_safe for item in audit.items)


def test_state_path_audit_reports_unsafe_and_missing_paths(tmp_path: Path) -> None:
    state_paths = RuntimeStatePaths.from_app_root(tmp_path, home_dir=tmp_path / "home")

    audit = state_paths.audit_configured_state_paths(
        _AuditSettings(),
        specs=(
            RuntimeStatePathSpec("unsafe", "Unsafe path", "unsafe_path"),
            RuntimeStatePathSpec("missing", "Missing required path", "disabled_path"),
        ),
    )

    assert audit.overall == "error"
    assert audit.restart_safe is False
    assert audit.items[0].status == "error"
    assert audit.items[0].restart_safe is False
    assert audit.items[0].root is None
    assert "escapes approved runtime state roots" in audit.items[0].message
    assert audit.items[1].message == "Required restart-sensitive state path is not configured."
