"""Agent OS readiness and recovery contracts."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class AgentOSMount(BaseModel):
    host_path: str
    container_path: str = "/workspace"
    read_only: bool = False
    safe: bool = True


class AgentOSReadiness(BaseModel):
    workspace_root: str
    workspace_exists: bool
    safe_mounts: list[AgentOSMount] = Field(default_factory=list)
    dry_run_available: bool = True
    recovery_enabled: bool = True
    restart_instructions: list[str] = Field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.workspace_exists and all(mount.safe for mount in self.safe_mounts)


def build_agent_os_readiness(
    workspace_root: str | Path,
    *,
    recovery_enabled: bool = True,
    dry_run_available: bool = True,
) -> AgentOSReadiness:
    root = Path(workspace_root).expanduser().resolve()
    mount = AgentOSMount(
        host_path=str(root),
        safe=root.exists(),
    )
    return AgentOSReadiness(
        workspace_root=str(root),
        workspace_exists=root.exists(),
        safe_mounts=[mount],
        dry_run_available=dry_run_available,
        recovery_enabled=recovery_enabled,
        restart_instructions=[
            "restart the Agent OS session",
            "re-run readiness checks before mutating the workspace",
        ],
    )
