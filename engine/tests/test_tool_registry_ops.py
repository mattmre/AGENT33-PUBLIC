"""Tests for Phase 12 – Tool Registry Operations & Change Control."""

from __future__ import annotations

import textwrap
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from agent33.tools.base import ToolContext, ToolResult
from agent33.tools.registry import ToolRegistry
from agent33.tools.registry_entry import (
    ToolApproval,
    ToolProvenance,
    ToolRegistryEntry,
    ToolScope,
    ToolStatus,
)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


class _StubTool:
    """Minimal concrete tool for testing."""

    def __init__(self, name: str = "stub", description: str = "A stub tool") -> None:
        self._name = name
        self._description = description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult.ok("ok")


def _make_entry(
    name: str = "stub",
    version: str = "1.0",
    status: ToolStatus = ToolStatus.ACTIVE,
) -> ToolRegistryEntry:
    return ToolRegistryEntry(
        tool_id=name,
        name=name,
        version=version,
        status=status,
    )


# ------------------------------------------------------------------
# ToolRegistryEntry model tests
# ------------------------------------------------------------------


class TestToolRegistryEntry:
    def test_minimal_creation(self) -> None:
        entry = ToolRegistryEntry(tool_id="t1", name="t1", version="1.0")
        assert entry.tool_id == "t1"
        assert entry.status == ToolStatus.ACTIVE
        assert entry.deprecation_message == ""
        assert entry.tags == []

    def test_full_creation(self) -> None:
        entry = ToolRegistryEntry(
            tool_id="browser",
            name="browser",
            version="2.1",
            description="Browser tool",
            owner="team-a",
            provenance=ToolProvenance(
                repo_url="https://example.com",
                commit_or_tag="abc123",
                checksum="sha256:deadbeef",
                license="MIT",
            ),
            scope=ToolScope(
                commands=["curl"],
                endpoints=["/api"],
                data_access="read",
                network=True,
                filesystem=["/tmp"],
            ),
            approval=ToolApproval(
                approver="alice",
                approved_date=date(2025, 1, 1),
                evidence="PR-42",
            ),
            status=ToolStatus.DEPRECATED,
            last_review=date(2025, 6, 1),
            next_review=date(2026, 6, 1),
            deprecation_message="Use browser_v2 instead.",
            tags=["web", "automation"],
        )
        assert entry.version == "2.1"
        assert entry.provenance.license == "MIT"
        assert entry.scope.network is True
        assert entry.approval.approver == "alice"
        assert entry.status == ToolStatus.DEPRECATED
        assert entry.deprecation_message == "Use browser_v2 instead."
        assert entry.tags == ["web", "automation"]


class TestToolStatus:
    def test_enum_values(self) -> None:
        assert ToolStatus.ACTIVE.value == "active"
        assert ToolStatus.DEPRECATED.value == "deprecated"
        assert ToolStatus.BLOCKED.value == "blocked"

    def test_from_string(self) -> None:
        assert ToolStatus("active") is ToolStatus.ACTIVE
        assert ToolStatus("deprecated") is ToolStatus.DEPRECATED


class TestToolProvenance:
    def test_defaults(self) -> None:
        p = ToolProvenance()
        assert p.repo_url == ""
        assert p.checksum == ""

    def test_populated(self) -> None:
        p = ToolProvenance(repo_url="https://gh.com", license="Apache-2.0")
        assert p.license == "Apache-2.0"


# ------------------------------------------------------------------
# ToolRegistry – Phase 12 methods
# ------------------------------------------------------------------


class TestRegisterWithEntry:
    def test_stores_tool_and_entry(self) -> None:
        reg = ToolRegistry()
        tool = _StubTool(name="shell")
        entry = _make_entry(name="shell")

        reg.register_with_entry(tool, entry)

        assert reg.get("shell") is tool
        assert reg.get_entry("shell") is not None
        assert reg.get_entry("shell").version == "1.0"

    def test_overwrites_previous(self) -> None:
        reg = ToolRegistry()
        tool_v1 = _StubTool(name="shell")
        tool_v2 = _StubTool(name="shell", description="v2")
        reg.register_with_entry(tool_v1, _make_entry(name="shell", version="1.0"))
        reg.register_with_entry(tool_v2, _make_entry(name="shell", version="2.0"))

        assert reg.get("shell") is tool_v2
        assert reg.get_entry("shell").version == "2.0"


class TestGetEntry:
    def test_returns_none_for_unknown(self) -> None:
        reg = ToolRegistry()
        assert reg.get_entry("nonexistent") is None

    def test_returns_entry(self) -> None:
        reg = ToolRegistry()
        reg.register_with_entry(_StubTool(), _make_entry())
        assert reg.get_entry("stub") is not None


class TestListEntries:
    def test_empty(self) -> None:
        reg = ToolRegistry()
        assert reg.list_entries() == []

    def test_returns_all(self) -> None:
        reg = ToolRegistry()
        reg.register_with_entry(_StubTool("a"), _make_entry("a"))
        reg.register_with_entry(_StubTool("b"), _make_entry("b"))
        names = {e.name for e in reg.list_entries()}
        assert names == {"a", "b"}


class TestSetStatus:
    def test_updates_status(self) -> None:
        reg = ToolRegistry()
        reg.register_with_entry(_StubTool(), _make_entry())

        result = reg.set_status("stub", ToolStatus.DEPRECATED, "Use v2")

        assert result is True
        entry = reg.get_entry("stub")
        assert entry.status == ToolStatus.DEPRECATED
        assert entry.deprecation_message == "Use v2"

    def test_returns_false_for_unknown(self) -> None:
        reg = ToolRegistry()
        assert reg.set_status("ghost", ToolStatus.BLOCKED) is False

    def test_blocked_status(self) -> None:
        reg = ToolRegistry()
        reg.register_with_entry(_StubTool(), _make_entry())
        reg.set_status("stub", ToolStatus.BLOCKED, "Security issue")
        assert reg.get_entry("stub").status == ToolStatus.BLOCKED


# ------------------------------------------------------------------
# load_definitions
# ------------------------------------------------------------------


class TestLoadDefinitions:
    def test_loads_yaml_files(self, tmp_path: Path) -> None:
        (tmp_path / "tool_a.yml").write_text(
            textwrap.dedent("""\
                name: tool_a
                version: "1.0"
                owner: team-x
                provenance:
                  repo_url: https://example.com
                  license: MIT
                status: active
                description: Tool A
            """),
            encoding="utf-8",
        )
        (tmp_path / "tool_b.yaml").write_text(
            textwrap.dedent("""\
                name: tool_b
                version: "2.0"
                status: deprecated
                description: Tool B
            """),
            encoding="utf-8",
        )

        reg = ToolRegistry()
        count = reg.load_definitions(str(tmp_path))

        assert count == 2
        a = reg.get_entry("tool_a")
        assert a is not None
        assert a.owner == "team-x"
        assert a.provenance.license == "MIT"
        b = reg.get_entry("tool_b")
        assert b is not None
        assert b.status == ToolStatus.DEPRECATED

    def test_skips_non_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("not yaml", encoding="utf-8")
        (tmp_path / "tool.yml").write_text("name: t\nversion: '1'\n", encoding="utf-8")

        reg = ToolRegistry()
        assert reg.load_definitions(str(tmp_path)) == 1

    def test_skips_invalid_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "bad.yml").write_text("- just a list\n", encoding="utf-8")
        (tmp_path / "no_name.yml").write_text("version: '1'\n", encoding="utf-8")

        reg = ToolRegistry()
        assert reg.load_definitions(str(tmp_path)) == 0

    def test_nonexistent_dir(self) -> None:
        reg = ToolRegistry()
        assert reg.load_definitions("/nonexistent/path") == 0

    def test_loads_real_definitions(self) -> None:
        """Load the actual tool-definitions/ directory shipped with the engine."""
        defs_dir = Path(__file__).resolve().parent.parent / "tool-definitions"
        if not defs_dir.is_dir():
            pytest.skip("tool-definitions directory not found")
        reg = ToolRegistry()
        count = reg.load_definitions(str(defs_dir))
        assert count >= 6  # shell + 5 new definitions
        assert reg.get_entry("shell") is not None
        assert reg.get_entry("browser") is not None


# ------------------------------------------------------------------
# Backward compatibility – existing API unchanged
# ------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_register_without_entry(self) -> None:
        reg = ToolRegistry()
        tool = _StubTool()
        reg.register(tool)
        assert reg.get("stub") is tool
        assert reg.get_entry("stub") is None  # no entry created

    def test_list_all_unaffected(self) -> None:
        reg = ToolRegistry()
        reg.register(_StubTool("a"))
        reg.register_with_entry(_StubTool("b"), _make_entry("b"))
        names = {t.name for t in reg.list_all()}
        assert names == {"a", "b"}
