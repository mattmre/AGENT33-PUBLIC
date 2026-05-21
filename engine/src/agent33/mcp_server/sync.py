"""Cross-CLI MCP configuration sync for registering AGENT-33 across CLI environments."""

from __future__ import annotations

import json
import logging
import os
import shutil
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SyncConfigError(Exception):
    """Raised when an MCP CLI config cannot be read safely."""


class CLITarget(StrEnum):
    """Supported CLI environments for MCP sync."""

    CLAUDE_CODE = "claude_code"
    CLAUDE_DESKTOP = "claude_desktop"
    CURSOR = "cursor"
    GEMINI = "gemini"


class NormalizedMCPEntry(BaseModel):
    """CLI-agnostic MCP server registration."""

    name: str = "agent33"
    command: str = "uvx"
    args: list[str] = Field(default_factory=lambda: ["agent33", "mcp", "serve"])
    env: dict[str, str] = Field(default_factory=dict)
    transport: str = "stdio"
    url: str = ""

    def to_cli_dict(self) -> dict[str, Any]:
        """Serialize to the format expected by Claude/Cursor CLI configs."""
        entry: dict[str, Any] = {}
        if self.transport == "sse" and self.url:
            entry["transport"] = "sse"
            entry["url"] = self.url
        else:
            entry["command"] = self.command
            if self.args:
                entry["args"] = self.args
        if self.env:
            entry["env"] = self.env
        return entry


class SyncConfig(BaseModel):
    """Configuration for a sync operation."""

    entry: NormalizedMCPEntry = Field(default_factory=NormalizedMCPEntry)
    targets: list[CLITarget] = Field(default_factory=lambda: [CLITarget.CLAUDE_CODE])
    force: bool = False


class SyncResult(BaseModel):
    """Result of a sync operation for a single target."""

    target: str
    config_path: str
    status: str  # "added", "updated", "skipped", "conflict", "error", "not_found"
    message: str = ""
    existing_entry: dict[str, Any] | None = None


class DiffEntry(BaseModel):
    """Diff result for a single target."""

    target: str
    config_path: str
    present: bool = False
    matches: bool = False
    current: dict[str, Any] | None = None
    expected: dict[str, Any] | None = None
    error: str = ""


class PullResult(BaseModel):
    """Result of pulling MCP server registrations from a CLI config."""

    target: str
    config_path: str
    servers: list[dict[str, Any]] = Field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------------------
# Config path resolution
# ---------------------------------------------------------------------------


def _get_config_path(target: CLITarget) -> Path | None:
    """Resolve the config file path for a CLI target."""
    home = Path.home()

    if target == CLITarget.CLAUDE_CODE:
        return home / ".claude.json"

    if target == CLITarget.CLAUDE_DESKTOP:
        if os.name == "nt":
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                return Path(appdata) / "Claude" / "claude_desktop_config.json"
        else:
            return (
                home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
            )
        return None

    if target == CLITarget.CURSOR:
        return home / ".cursor" / "mcp.json"

    if target == CLITarget.GEMINI:
        return home / ".gemini" / "settings.json"

    return None


def get_target_paths() -> dict[str, str]:
    """Return resolved config file paths for all CLI targets."""
    result: dict[str, str] = {}
    for target in CLITarget:
        path = _get_config_path(target)
        result[target.value] = str(path) if path else ""
    return result


# ---------------------------------------------------------------------------
# Sync operations
# ---------------------------------------------------------------------------


def _read_config(path: Path) -> dict[str, Any]:
    """Read a JSON config file, returning empty dict if not found."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("sync_config_read_error: path=%s error=%s", path, exc)
        raise SyncConfigError(f"Unable to read config '{path}': {exc}") from exc


def _write_config(path: Path, data: dict[str, Any], backup: bool = True) -> None:
    """Write a JSON config file with optional backup."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        bak = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(str(path), str(bak))
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _normalize_path(path_str: str) -> str:
    """Normalize path separators for cross-platform JSON configs."""
    return path_str.replace("\\", "/")


def push_sync(config: SyncConfig, backup: bool = True) -> list[SyncResult]:
    """Push AGENT-33 MCP registration to target CLI configs."""
    results: list[SyncResult] = []
    entry_dict = config.entry.to_cli_dict()
    entry_name = config.entry.name

    for target in config.targets:
        path = _get_config_path(target)
        if path is None:
            results.append(
                SyncResult(
                    target=target.value,
                    config_path="",
                    status="error",
                    message=f"Cannot resolve config path for {target.value}",
                )
            )
            continue

        try:
            data = _read_config(path)
        except SyncConfigError as exc:
            results.append(
                SyncResult(
                    target=target.value,
                    config_path=str(path),
                    status="error",
                    message=str(exc),
                )
            )
            continue

        mcp_servers = data.get("mcpServers", {})
        if "mcpServers" in data and not isinstance(mcp_servers, dict):
            results.append(
                SyncResult(
                    target=target.value,
                    config_path=str(path),
                    status="error",
                    message="mcpServers is not a valid object",
                )
            )
            continue

        existing = mcp_servers.get(entry_name)
        if existing is not None and not config.force:
            results.append(
                SyncResult(
                    target=target.value,
                    config_path=str(path),
                    status="conflict",
                    message=f"Entry '{entry_name}' already exists. Use force=True to overwrite.",
                    existing_entry=existing,
                )
            )
            continue

        status = "updated" if existing is not None else "added"
        mcp_servers[entry_name] = entry_dict
        data["mcpServers"] = mcp_servers
        _write_config(path, data, backup=backup)
        results.append(
            SyncResult(
                target=target.value,
                config_path=str(path),
                status=status,
                message=f"AGENT-33 MCP registration {status} in {target.value}",
            )
        )

    return results


def pull_sync(target: CLITarget) -> PullResult:
    """Pull MCP server registrations from a CLI config."""
    path = _get_config_path(target)
    if path is None:
        return PullResult(
            target=target.value,
            config_path="",
            error=f"Cannot resolve config path for {target.value}",
        )

    try:
        data = _read_config(path)
    except SyncConfigError as exc:
        return PullResult(
            target=target.value,
            config_path=str(path),
            error=str(exc),
        )
    mcp_servers = data.get("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        return PullResult(
            target=target.value,
            config_path=str(path),
            error="mcpServers is not a valid object",
        )

    servers: list[dict[str, Any]] = []
    for name, entry in mcp_servers.items():
        if name == "agent33":
            continue  # skip self-registration
        server_entry: dict[str, Any] = {"name": name}
        if isinstance(entry, dict):
            server_entry.update(entry)
        servers.append(server_entry)

    return PullResult(
        target=target.value,
        config_path=str(path),
        servers=servers,
    )


def diff_sync(entry: NormalizedMCPEntry | None = None) -> list[DiffEntry]:
    """Diff AGENT-33 registration across all CLI targets."""
    if entry is None:
        entry = NormalizedMCPEntry()

    expected_dict = entry.to_cli_dict()
    results: list[DiffEntry] = []

    for target in CLITarget:
        path = _get_config_path(target)
        if path is None:
            results.append(
                DiffEntry(
                    target=target.value,
                    config_path="",
                    present=False,
                    matches=False,
                    expected=expected_dict,
                )
            )
            continue

        try:
            data = _read_config(path)
        except SyncConfigError as exc:
            results.append(
                DiffEntry(
                    target=target.value,
                    config_path=str(path),
                    present=False,
                    matches=False,
                    expected=expected_dict,
                    error=str(exc),
                )
            )
            continue
        mcp_servers = data.get("mcpServers", {})
        if "mcpServers" in data and not isinstance(mcp_servers, dict):
            results.append(
                DiffEntry(
                    target=target.value,
                    config_path=str(path),
                    present=False,
                    matches=False,
                    expected=expected_dict,
                    error="mcpServers is not a valid object",
                )
            )
            continue

        current = mcp_servers.get(entry.name) if isinstance(mcp_servers, dict) else None

        results.append(
            DiffEntry(
                target=target.value,
                config_path=str(path),
                present=current is not None,
                matches=current == expected_dict if current is not None else False,
                current=current,
                expected=expected_dict,
            )
        )

    return results
