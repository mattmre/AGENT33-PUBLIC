"""ScriptHookDiscovery: discover and register file-based hooks from the filesystem."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from agent33.hooks.script_hook import ScriptHook

if TYPE_CHECKING:
    from pathlib import Path

    from agent33.hooks.registry import HookRegistry

logger = logging.getLogger(__name__)

# Supported script extensions
_SUPPORTED_EXTENSIONS = {".py", ".sh", ".ps1", ".js"}
_EVENT_TYPE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def resolve_project_hooks_dir(project_root: Path) -> Path:
    """Resolve the default project hooks directory."""
    scripts_hooks = project_root / "scripts" / "hooks"
    if scripts_hooks.is_dir():
        return scripts_hooks
    return project_root / ".claude" / "hooks"


class ScriptHookDiscovery:
    """Discovers and registers file-based hooks from filesystem paths.

    Hook scripts follow the naming convention:
        <event-type>--<hook-name>[.ext]

    For example:
        session.start--purpose-gate.py
        tool.execute.pre--damage-control.sh
    """

    def __init__(
        self,
        hook_registry: HookRegistry,
        project_hooks_dir: Path | None = None,
        user_hooks_dir: Path | None = None,
        default_timeout_ms: float = 5000.0,
        max_timeout_ms: float = 30000.0,
    ) -> None:
        self._registry = hook_registry
        self._project_dir = project_hooks_dir
        self._user_dir = user_hooks_dir
        self._default_timeout_ms = default_timeout_ms
        self._max_timeout_ms = max_timeout_ms
        self._discovered: dict[str, ScriptHook] = {}

    @property
    def discovered_hooks(self) -> dict[str, ScriptHook]:
        """Map of hook name to ScriptHook instance."""
        return dict(self._discovered)

    def discover(self) -> int:
        """Scan directories, parse filenames, register ScriptHook instances.

        Returns the number of hooks discovered and registered.
        Project-level hooks take priority over user-level hooks with the
        same name (project overrides user).
        """
        hooks_by_name: dict[str, tuple[str, str, Path]] = {}

        # User-level first (will be overridden by project-level)
        if self._user_dir and self._user_dir.is_dir():
            for path in self._user_dir.iterdir():
                if not path.is_file():
                    continue
                parsed = self._parse_hook_filename(path)
                if parsed is not None:
                    event_type, hook_name = parsed
                    hooks_by_name[hook_name] = (event_type, hook_name, path)

        # Project-level overrides user-level
        if self._project_dir and self._project_dir.is_dir():
            for path in self._project_dir.iterdir():
                if not path.is_file():
                    continue
                parsed = self._parse_hook_filename(path)
                if parsed is not None:
                    event_type, hook_name = parsed
                    hooks_by_name[hook_name] = (event_type, hook_name, path)

        count = 0
        for event_type, hook_name, script_path in hooks_by_name.values():
            try:
                hook = ScriptHook(
                    name=f"script.{hook_name}",
                    event_type=event_type,
                    script_path=script_path,
                    timeout_ms=min(self._default_timeout_ms, self._max_timeout_ms),
                    fail_mode="open",
                    priority=200,
                )
                self._registry.register(hook)
                self._discovered[hook_name] = hook
                count += 1
                logger.info(
                    "script_hook_discovered name=%s event=%s path=%s",
                    hook_name,
                    event_type,
                    script_path,
                )
            except (ValueError, PermissionError) as exc:
                logger.warning(
                    "script_hook_registration_failed name=%s error=%s",
                    hook_name,
                    exc,
                )

        logger.info("script_hook_discovery_complete count=%d", count)
        return count

    def rediscover(self) -> int:
        """Re-scan filesystem and re-register hooks.

        Deregisters previously discovered hooks first, then re-discovers.
        """
        # Deregister previously discovered hooks
        for _hook_name, hook in self._discovered.items():
            self._registry.deregister(hook.name, hook.event_type)
        self._discovered.clear()
        return self.discover()

    @staticmethod
    def _parse_hook_filename(path: Path) -> tuple[str, str] | None:
        """Parse '<event-type>--<hook-name>[.ext]' -> (event_type, name).

        Returns None for unparseable filenames.
        """
        name = path.stem  # filename without extension
        suffix = path.suffix.lower()

        # Check extension
        if suffix not in _SUPPORTED_EXTENSIONS:
            return None

        # Must contain '--' separator
        if "--" not in name:
            return None

        parts = name.split("--", 1)
        if len(parts) != 2:
            return None

        event_type = parts[0].strip()
        hook_name = parts[1].strip()

        if not event_type or not hook_name:
            return None

        # Validate event type looks reasonable (dots-separated segments)
        if not all(_EVENT_TYPE_SEGMENT_RE.fullmatch(seg) for seg in event_type.split(".")):
            return None

        return event_type, hook_name
