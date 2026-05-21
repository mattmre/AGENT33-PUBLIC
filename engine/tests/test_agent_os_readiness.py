from __future__ import annotations

from agent33.ops.agent_os import build_agent_os_readiness


def test_agent_os_readiness_marks_existing_workspace_ready(tmp_path) -> None:
    readiness = build_agent_os_readiness(tmp_path)

    assert readiness.ready is True
    assert readiness.workspace_exists is True
    assert readiness.safe_mounts[0].host_path == str(tmp_path.resolve())
    assert readiness.safe_mounts[0].container_path == "/workspace"
    assert readiness.dry_run_available is True
    assert readiness.recovery_enabled is True


def test_agent_os_readiness_marks_missing_workspace_not_ready(tmp_path) -> None:
    missing = tmp_path / "missing"

    readiness = build_agent_os_readiness(missing, recovery_enabled=False)

    assert readiness.ready is False
    assert readiness.workspace_exists is False
    assert readiness.safe_mounts[0].safe is False
    assert readiness.recovery_enabled is False
    assert "restart the Agent OS session" in readiness.restart_instructions
