"""Build and report live status-line snapshots from operator continuity state."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


class StatusLineService:
    """Build renderable operator status snapshots and expose their health."""

    def __init__(
        self,
        *,
        app_state: Any,
        workspace_root: Path,
        voice_probe: Any | None = None,
    ) -> None:
        self._app_state = app_state
        self._workspace_root = workspace_root
        self._voice_probe = voice_probe
        self._last_snapshot_at: datetime | None = None

    async def build_snapshot(self, session: Any) -> dict[str, Any]:
        """Build a deterministic status snapshot to persist in ``OperatorSession.cache``."""
        now = datetime.now(UTC)
        counts = self._collect_counts()
        git = self._git_snapshot()
        voice = await self._voice_snapshot()
        rendered = (
            f"{git['branch']}@{git['commit']}{'*' if git['dirty'] else ''} | "
            f"tools:{counts['tools']} skills:{counts['skills']} packs:{counts['packs']} "
            f"plugins:{counts['plugins']} hooks:{counts['hooks']} procs:{counts['processes']} "
            f"voice:{voice['status']}"
        )
        snapshot = {
            "generated_at": now.isoformat(),
            "session_id": session.session_id,
            "rendered": rendered,
            "counts": counts,
            "git": git,
            "voice": voice,
        }
        self._last_snapshot_at = now
        return snapshot

    async def health_snapshot(self) -> dict[str, Any]:
        """Return status-line health for `/health` and operator status surfaces."""
        discovery = getattr(self._app_state, "script_hook_discovery", None)
        hook_present = False
        if discovery is not None:
            hook_present = "status-line" in discovery.discovered_hooks
        if hook_present or getattr(self._app_state, "operator_session_service", None) is not None:
            status = "ok"
        else:
            status = "unavailable"
        return {
            "status": status,
            "hook_present": hook_present,
            "last_snapshot_at": self._last_snapshot_at.isoformat()
            if self._last_snapshot_at
            else None,
            "workspace_root": str(self._workspace_root),
        }

    def _collect_counts(self) -> dict[str, int]:
        return {
            "tools": self._registry_count("tool_registry"),
            "skills": self._registry_count("skill_registry"),
            "packs": self._registry_count("pack_registry"),
            "plugins": self._registry_count("plugin_registry"),
            "hooks": self._hook_count(),
            "processes": self._process_count(),
        }

    def _registry_count(self, attribute: str) -> int:
        registry = getattr(self._app_state, attribute, None)
        if registry is None:
            return 0
        list_all = getattr(registry, "list_all", None)
        if callable(list_all):
            return len(list_all())
        return 0

    def _hook_count(self) -> int:
        registry = getattr(self._app_state, "hook_registry", None)
        if registry is None:
            return 0
        count = getattr(registry, "count", None)
        return int(count()) if callable(count) else 0

    def _process_count(self) -> int:
        process_manager = getattr(self._app_state, "process_manager_service", None)
        if process_manager is None:
            return 0
        inventory = process_manager.inventory()
        return int(inventory.get("active", inventory.get("count", 0)))

    def _git_snapshot(self) -> dict[str, Any]:
        branch = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"]) or "unknown"
        commit = self._run_git(["rev-parse", "--short", "HEAD"]) or "unknown"
        dirty = bool(self._run_git(["status", "--porcelain"]))
        return {
            "branch": branch,
            "commit": commit,
            "dirty": dirty,
        }

    def _run_git(self, args: list[str]) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self._workspace_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=2.0,
            )
        except Exception:
            return ""
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    async def _voice_snapshot(self) -> dict[str, Any]:
        if self._voice_probe is None:
            return {"status": "unconfigured"}
        snapshot = await self._voice_probe.health_snapshot()
        if isinstance(snapshot, dict):
            return dict(snapshot)
        return {"status": "unavailable"}
