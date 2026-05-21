"""Tests for cross-CLI MCP sync operations (Phase 45)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from agent33.mcp_server.sync import (
    CLITarget,
    NormalizedMCPEntry,
    SyncConfig,
    diff_sync,
    get_target_paths,
    pull_sync,
    push_sync,
)


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for config files."""
    return tmp_path


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class TestNormalizedMCPEntry:
    """Entry serialization for CLI configs."""

    def test_stdio_entry(self) -> None:
        entry = NormalizedMCPEntry(
            command="uvx",
            args=["agent33", "mcp", "serve"],
        )
        d = entry.to_cli_dict()
        assert d["command"] == "uvx"
        assert d["args"] == ["agent33", "mcp", "serve"]
        assert "transport" not in d  # stdio is default, not emitted

    def test_sse_entry(self) -> None:
        entry = NormalizedMCPEntry(
            transport="sse",
            url="http://localhost:8000/mcp/sse",
        )
        d = entry.to_cli_dict()
        assert d["transport"] == "sse"
        assert d["url"] == "http://localhost:8000/mcp/sse"
        assert "command" not in d

    def test_env_included(self) -> None:
        entry = NormalizedMCPEntry(
            env={"AGENT33_JWT_SECRET": "${AGENT33_JWT_SECRET}"},
        )
        d = entry.to_cli_dict()
        assert d["env"]["AGENT33_JWT_SECRET"] == "${AGENT33_JWT_SECRET}"


class TestPushSync:
    """Push: write AGENT-33 registration to CLI configs."""

    def test_push_creates_new_entry(self, tmp_config_dir: Path) -> None:
        config_path = tmp_config_dir / ".claude.json"
        _write_json(config_path, {})

        with patch("agent33.mcp_server.sync._get_config_path", return_value=config_path):
            config = SyncConfig(
                entry=NormalizedMCPEntry(),
                targets=[CLITarget.CLAUDE_CODE],
            )
            results = push_sync(config, backup=False)

        assert len(results) == 1
        assert results[0].status == "added"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert "agent33" in data["mcpServers"]
        assert data["mcpServers"]["agent33"]["command"] == "uvx"

    def test_push_conflict_without_force(self, tmp_config_dir: Path) -> None:
        config_path = tmp_config_dir / ".claude.json"
        _write_json(config_path, {"mcpServers": {"agent33": {"command": "old"}}})

        with patch("agent33.mcp_server.sync._get_config_path", return_value=config_path):
            config = SyncConfig(
                entry=NormalizedMCPEntry(),
                targets=[CLITarget.CLAUDE_CODE],
                force=False,
            )
            results = push_sync(config, backup=False)

        assert results[0].status == "conflict"
        assert results[0].existing_entry == {"command": "old"}

    def test_push_force_overwrites(self, tmp_config_dir: Path) -> None:
        config_path = tmp_config_dir / ".claude.json"
        _write_json(config_path, {"mcpServers": {"agent33": {"command": "old"}}})

        with patch("agent33.mcp_server.sync._get_config_path", return_value=config_path):
            config = SyncConfig(
                entry=NormalizedMCPEntry(),
                targets=[CLITarget.CLAUDE_CODE],
                force=True,
            )
            results = push_sync(config, backup=False)

        assert results[0].status == "updated"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["mcpServers"]["agent33"]["command"] == "uvx"

    def test_push_creates_backup(self, tmp_config_dir: Path) -> None:
        config_path = tmp_config_dir / ".claude.json"
        _write_json(config_path, {"mcpServers": {}})

        with patch("agent33.mcp_server.sync._get_config_path", return_value=config_path):
            config = SyncConfig(
                entry=NormalizedMCPEntry(),
                targets=[CLITarget.CLAUDE_CODE],
            )
            push_sync(config, backup=True)

        bak = config_path.with_suffix(".json.bak")
        assert bak.exists()

    def test_push_creates_file_if_not_exists(self, tmp_config_dir: Path) -> None:
        config_path = tmp_config_dir / "new_dir" / ".claude.json"

        with patch("agent33.mcp_server.sync._get_config_path", return_value=config_path):
            config = SyncConfig(
                entry=NormalizedMCPEntry(),
                targets=[CLITarget.CLAUDE_CODE],
            )
            results = push_sync(config, backup=False)

        assert results[0].status == "added"
        assert config_path.exists()

    def test_push_unresolvable_target(self) -> None:
        with patch("agent33.mcp_server.sync._get_config_path", return_value=None):
            config = SyncConfig(targets=[CLITarget.GEMINI])
            results = push_sync(config, backup=False)
        assert results[0].status == "error"

    def test_push_invalid_existing_config_returns_error(self, tmp_config_dir: Path) -> None:
        config_path = tmp_config_dir / ".claude.json"
        config_path.write_text("{", encoding="utf-8")

        with patch("agent33.mcp_server.sync._get_config_path", return_value=config_path):
            config = SyncConfig(targets=[CLITarget.CLAUDE_CODE])
            results = push_sync(config, backup=False)

        assert results[0].status == "error"
        assert "Unable to read config" in results[0].message
        assert config_path.read_text(encoding="utf-8") == "{"


class TestPullSync:
    """Pull: read MCP servers from CLI config."""

    def test_pull_discovers_servers(self, tmp_config_dir: Path) -> None:
        config_path = tmp_config_dir / ".claude.json"
        _write_json(
            config_path,
            {
                "mcpServers": {
                    "agent33": {"command": "uvx"},
                    "elevenlabs": {"command": "npx", "args": ["-y", "elevenlabs-mcp"]},
                    "filesystem": {"command": "npx", "args": ["fs-server"]},
                }
            },
        )

        with patch("agent33.mcp_server.sync._get_config_path", return_value=config_path):
            result = pull_sync(CLITarget.CLAUDE_CODE)

        assert result.error == ""
        assert len(result.servers) == 2  # agent33 excluded
        names = {s["name"] for s in result.servers}
        assert "elevenlabs" in names
        assert "filesystem" in names
        assert "agent33" not in names

    def test_pull_empty_config(self, tmp_config_dir: Path) -> None:
        config_path = tmp_config_dir / ".claude.json"
        _write_json(config_path, {})

        with patch("agent33.mcp_server.sync._get_config_path", return_value=config_path):
            result = pull_sync(CLITarget.CLAUDE_CODE)

        assert result.error == ""
        assert len(result.servers) == 0

    def test_pull_unresolvable_target(self) -> None:
        with patch("agent33.mcp_server.sync._get_config_path", return_value=None):
            result = pull_sync(CLITarget.GEMINI)
        assert result.error != ""

    def test_pull_invalid_config_reports_error(self, tmp_config_dir: Path) -> None:
        config_path = tmp_config_dir / ".claude.json"
        config_path.write_text("{", encoding="utf-8")

        with patch("agent33.mcp_server.sync._get_config_path", return_value=config_path):
            result = pull_sync(CLITarget.CLAUDE_CODE)

        assert "Unable to read config" in result.error


class TestDiffSync:
    """Diff: compare AGENT-33 registration across CLIs."""

    def test_diff_present_and_matching(self, tmp_config_dir: Path) -> None:
        entry = NormalizedMCPEntry()
        config_path = tmp_config_dir / ".claude.json"
        _write_json(config_path, {"mcpServers": {"agent33": entry.to_cli_dict()}})

        with patch("agent33.mcp_server.sync._get_config_path", return_value=config_path):
            results = diff_sync(entry)

        # Multiple targets are checked; find the one for claude_code
        claude_results = [r for r in results if r.target == "claude_code"]
        assert len(claude_results) == 1
        assert claude_results[0].present is True
        assert claude_results[0].matches is True

    def test_diff_absent(self, tmp_config_dir: Path) -> None:
        config_path = tmp_config_dir / ".claude.json"
        _write_json(config_path, {})

        with patch("agent33.mcp_server.sync._get_config_path", return_value=config_path):
            results = diff_sync()

        claude_results = [r for r in results if r.target == "claude_code"]
        assert claude_results[0].present is False
        assert claude_results[0].matches is False

    def test_diff_divergent(self, tmp_config_dir: Path) -> None:
        config_path = tmp_config_dir / ".claude.json"
        _write_json(config_path, {"mcpServers": {"agent33": {"command": "old-cmd"}}})

        with patch("agent33.mcp_server.sync._get_config_path", return_value=config_path):
            results = diff_sync()

        claude_results = [r for r in results if r.target == "claude_code"]
        assert claude_results[0].present is True
        assert claude_results[0].matches is False
        assert claude_results[0].current == {"command": "old-cmd"}

    def test_diff_invalid_config_reports_error(self, tmp_config_dir: Path) -> None:
        config_path = tmp_config_dir / ".claude.json"
        config_path.write_text("{", encoding="utf-8")

        with patch("agent33.mcp_server.sync._get_config_path", return_value=config_path):
            results = diff_sync()

        claude_results = [r for r in results if r.target == "claude_code"]
        assert claude_results[0].error != ""
        assert claude_results[0].present is False


class TestTargetPaths:
    """get_target_paths resolution."""

    def test_returns_all_targets(self) -> None:
        paths = get_target_paths()
        assert "claude_code" in paths
        assert "claude_desktop" in paths
        assert "cursor" in paths
        assert "gemini" in paths

    def test_paths_are_strings(self) -> None:
        paths = get_target_paths()
        for val in paths.values():
            assert isinstance(val, str)
