"""Tests for P69a: tool/skill discovery CLI and approval flow.

Covers:
- Approved-tools persistent store (approve / revoke / list / idempotency)
- JSON file format and reason tracking
- search_ranked() on SkillRegistry (empty, populated, scoring)
- CLI search commands with mocked HTTP (tools search, skills search, skills list)
- Error handling when the API is unreachable
"""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003
from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from agent33.cli.main import app

runner = CliRunner()


# ---- Helper: redirect APPROVED_TOOLS_PATH to tmp_path ----


@pytest.fixture()
def _patch_approved_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the approved-tools file at a temp directory."""
    target = tmp_path / "approved-tools.json"
    monkeypatch.setattr("agent33.cli.tools.APPROVED_TOOLS_PATH", target)
    return target


# ====================================================================
# Tools: approve / revoke / list
# ====================================================================


class TestToolsApproveRevoke:
    """Approval persistence round-trips through the JSON file."""

    def test_list_empty(
        self,
        _patch_approved_path: Path,  # noqa: PT019
    ) -> None:
        result = runner.invoke(app, ["tools", "list"])
        assert result.exit_code == 0
        assert "No tools approved" in result.output

    def test_approve_and_list(
        self,
        _patch_approved_path: Path,  # noqa: PT019
    ) -> None:
        result = runner.invoke(app, ["tools", "approve", "web_fetch"])
        assert result.exit_code == 0
        assert "approved" in result.output.lower()

        result2 = runner.invoke(app, ["tools", "list"])
        assert result2.exit_code == 0
        assert "web_fetch" in result2.output

    def test_approve_idempotent(
        self,
        _patch_approved_path: Path,  # noqa: PT019
    ) -> None:
        runner.invoke(app, ["tools", "approve", "shell"])
        result = runner.invoke(app, ["tools", "approve", "shell"])
        assert result.exit_code == 0
        assert "already approved" in result.output.lower()

    def test_revoke(
        self,
        _patch_approved_path: Path,  # noqa: PT019
    ) -> None:
        runner.invoke(app, ["tools", "approve", "shell"])
        result = runner.invoke(app, ["tools", "revoke", "shell"])
        assert result.exit_code == 0
        assert "revoked" in result.output.lower()

        result2 = runner.invoke(app, ["tools", "list"])
        # After revoking the only tool, the list should be empty
        assert "No tools approved" in result2.output

    def test_revoke_not_found(
        self,
        _patch_approved_path: Path,  # noqa: PT019
    ) -> None:
        result = runner.invoke(app, ["tools", "revoke", "nonexistent"])
        assert result.exit_code == 0
        assert "not approved" in result.output.lower()

    def test_approve_multiple_tools(
        self,
        _patch_approved_path: Path,  # noqa: PT019
    ) -> None:
        runner.invoke(app, ["tools", "approve", "web_fetch"])
        runner.invoke(app, ["tools", "approve", "shell"])
        runner.invoke(app, ["tools", "approve", "file_ops"])
        result = runner.invoke(app, ["tools", "list"])
        assert "3" in result.output
        assert "web_fetch" in result.output
        assert "shell" in result.output
        assert "file_ops" in result.output


# ====================================================================
# Tools: JSON format
# ====================================================================


class TestApprovedToolsJsonFormat:
    """The JSON file stores approval metadata correctly."""

    def test_json_format_with_reason(
        self,
        _patch_approved_path: Path,  # noqa: PT019
    ) -> None:
        runner.invoke(
            app,
            ["tools", "approve", "web_fetch", "--reason", "needed for research"],
        )
        data = json.loads(_patch_approved_path.read_text(encoding="utf-8"))
        assert "web_fetch" in data
        assert "approved_at" in data["web_fetch"]
        assert data["web_fetch"]["reason"] == "needed for research"

    def test_json_format_without_reason(
        self,
        _patch_approved_path: Path,  # noqa: PT019
    ) -> None:
        runner.invoke(app, ["tools", "approve", "shell"])
        data = json.loads(_patch_approved_path.read_text(encoding="utf-8"))
        assert "shell" in data
        assert data["shell"]["reason"] == ""

    def test_revoke_removes_from_json(
        self,
        _patch_approved_path: Path,  # noqa: PT019
    ) -> None:
        runner.invoke(app, ["tools", "approve", "shell"])
        runner.invoke(app, ["tools", "approve", "web_fetch"])
        runner.invoke(app, ["tools", "revoke", "shell"])
        data = json.loads(_patch_approved_path.read_text(encoding="utf-8"))
        assert "shell" not in data
        assert "web_fetch" in data


# ====================================================================
# SkillRegistry.search_ranked()
# ====================================================================


class TestSkillRegistrySearchRanked:
    """BM25-scored ranked search on SkillRegistry."""

    def test_empty_registry_returns_empty(self) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        results = registry.search_ranked("web search", top_k=3)
        assert isinstance(results, list)
        assert len(results) == 0

    def test_ranked_search_returns_scored_results(self) -> None:
        from agent33.skills.definition import SkillDefinition
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.register(
            SkillDefinition(
                name="web-search",
                description="Search the web for information",
                tags=["search", "web", "research"],
            )
        )
        registry.register(
            SkillDefinition(
                name="web-scraper",
                description="Scrape data from web pages",
                tags=["web", "scrape", "data"],
            )
        )
        registry.register(
            SkillDefinition(
                name="deploy-k8s",
                description="Deploy applications to Kubernetes clusters",
                tags=["kubernetes", "deploy", "cloud"],
            )
        )

        results = registry.search_ranked("web search", top_k=3)
        # "web-search" has both "web" and "search" terms;
        # "web-scraper" has "web" only; deploy-k8s has neither.
        assert len(results) >= 1
        # Each result is (SkillDefinition, float)
        assert results[0][0].name == "web-search"
        assert results[0][1] > 0
        # If multiple results, first should score higher
        if len(results) > 1:
            assert results[0][1] >= results[1][1]

    def test_ranked_search_top_k_limits(self) -> None:
        from agent33.skills.definition import SkillDefinition
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        for i in range(10):
            registry.register(
                SkillDefinition(
                    name=f"skill-{i}",
                    description=f"A test skill number {i} for searching",
                    tags=["test"],
                )
            )

        results = registry.search_ranked("test skill", top_k=3)
        assert len(results) <= 3

    def test_ranked_search_preserves_original_search(self) -> None:
        """search_ranked() does not break the existing search() method."""
        from agent33.skills.definition import SkillDefinition
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.register(
            SkillDefinition(
                name="web-search",
                description="Search the web",
                tags=["web"],
            )
        )
        # Original substring search still works
        original = registry.search("web")
        assert len(original) == 1
        assert original[0].name == "web-search"

        # Ranked search also works
        ranked = registry.search_ranked("web", top_k=3)
        assert len(ranked) == 1
        assert ranked[0][0].name == "web-search"


# ====================================================================
# Tools search (mocked HTTP)
# ====================================================================


class TestToolsSearchCli:
    """CLI tools search command calls the discovery API correctly."""

    def test_search_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Tools search displays results from the API."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "query": "file",
            "matches": [
                {"name": "file_ops", "description": "File operations tool", "score": 8.5},
                {"name": "file_read", "description": "Read files from disk", "score": 5.2},
            ],
        }
        mock_response.raise_for_status = MagicMock()

        monkeypatch.setattr("httpx.get", lambda *_a, **_kw: mock_response)

        result = runner.invoke(app, ["tools", "search", "file"])
        assert result.exit_code == 0
        assert "file_ops" in result.output
        assert "8.50" in result.output
        assert "file_read" in result.output

    def test_search_no_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"query": "xyz", "matches": []}
        mock_response.raise_for_status = MagicMock()

        monkeypatch.setattr("httpx.get", lambda *_a, **_kw: mock_response)

        result = runner.invoke(app, ["tools", "search", "xyz"])
        assert result.exit_code == 0
        assert "No matching tools found" in result.output

    def test_search_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Connection errors are handled gracefully."""

        def _raise(*_a: Any, **_kw: Any) -> None:
            raise httpx.ConnectError("Connection refused")

        import httpx

        monkeypatch.setattr("httpx.get", _raise)

        result = runner.invoke(app, ["tools", "search", "web"])
        assert result.exit_code == 1

    def test_search_shows_approval_mark(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Approved tools show [v] marker in search results."""
        target = tmp_path / "approved-tools.json"
        monkeypatch.setattr("agent33.cli.tools.APPROVED_TOOLS_PATH", target)

        # Pre-approve file_ops
        runner.invoke(app, ["tools", "approve", "file_ops"])

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "query": "file",
            "matches": [
                {"name": "file_ops", "description": "File operations", "score": 8.0},
                {"name": "web_fetch", "description": "Fetch URLs", "score": 3.0},
            ],
        }
        mock_response.raise_for_status = MagicMock()
        monkeypatch.setattr("httpx.get", lambda *_a, **_kw: mock_response)

        result = runner.invoke(app, ["tools", "search", "file"])
        assert result.exit_code == 0
        # file_ops should show [v], web_fetch should show [ ]
        lines = result.output.strip().split("\n")
        file_ops_line = next(line for line in lines if "file_ops" in line)
        web_fetch_line = next(line for line in lines if "web_fetch" in line)
        assert "[v]" in file_ops_line
        assert "[ ]" in web_fetch_line


# ====================================================================
# Skills search / list (mocked HTTP)
# ====================================================================


class TestSkillsSearchCli:
    """CLI skills search command calls the discovery API correctly."""

    def test_search_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "query": "deploy",
            "matches": [
                {
                    "name": "deploy-k8s",
                    "description": "Deploy to Kubernetes",
                    "score": 7.3,
                    "tags": ["k8s"],
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()
        monkeypatch.setattr("httpx.get", lambda *_a, **_kw: mock_response)

        result = runner.invoke(app, ["skills", "search", "deploy"])
        assert result.exit_code == 0
        assert "deploy-k8s" in result.output
        assert "7.30" in result.output

    def test_search_no_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"query": "zzz", "matches": []}
        mock_response.raise_for_status = MagicMock()
        monkeypatch.setattr("httpx.get", lambda *_a, **_kw: mock_response)

        result = runner.invoke(app, ["skills", "search", "zzz"])
        assert result.exit_code == 0
        assert "No matching skills found" in result.output

    def test_list_skills(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "query": "agent",
            "matches": [
                {"name": "research-agent", "description": "Research skill", "score": 5.0},
                {"name": "code-review", "description": "Code review skill", "score": 4.0},
            ],
        }
        mock_response.raise_for_status = MagicMock()
        monkeypatch.setattr("httpx.get", lambda *_a, **_kw: mock_response)

        result = runner.invoke(app, ["skills", "list"])
        assert result.exit_code == 0
        assert "research-agent" in result.output
        assert "code-review" in result.output
        assert "2 found" in result.output

    def test_list_skills_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        def _raise(*_a: Any, **_kw: Any) -> None:
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr("httpx.get", _raise)

        result = runner.invoke(app, ["skills", "list"])
        assert result.exit_code == 1
