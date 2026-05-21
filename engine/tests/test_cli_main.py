"""Tests for the AGENT-33 CLI application (agent33.cli.main)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import httpx
import typer.testing

from agent33.cli.main import app

runner = typer.testing.CliRunner()


def _make_response(
    status_code: int,
    *,
    json_body: dict | None = None,
    method: str = "GET",
    url: str = "http://test",
) -> httpx.Response:
    """Build an ``httpx.Response`` with a request attached so raise_for_status works."""
    resp = httpx.Response(
        status_code,
        json=json_body,
        request=httpx.Request(method, url),
    )
    return resp


def _mock_httpx_client(
    *,
    method: str = "get",
    response: httpx.Response | None = None,
    side_effect: Exception | None = None,
) -> MagicMock:
    """Build a MagicMock that behaves like ``httpx.Client`` as a context manager."""
    client = MagicMock()
    target = getattr(client, method)
    if side_effect:
        target.side_effect = side_effect
    else:
        target.return_value = response
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


# ---------------------------------------------------------------------------
# Help / top-level
# ---------------------------------------------------------------------------


class TestHelpText:
    """Verify that the CLI advertises all commands and descriptions."""

    def test_top_level_help_lists_all_commands(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for cmd in ("init", "run", "test", "chat", "status"):
            assert cmd in result.output, f"'{cmd}' missing from --help output"

    def test_top_level_help_contains_app_description(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert "AGENT-33" in result.output


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------


class TestInitCommand:
    """Scaffold agent/workflow JSON definitions."""

    def test_init_agent_creates_valid_json_file(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["init", "my-bot", "-o", str(tmp_path)])
        assert result.exit_code == 0

        file = tmp_path / "my-bot.agent.json"
        assert file.exists(), "Agent JSON file was not created"
        data = json.loads(file.read_text(encoding="utf-8"))

        assert data["name"] == "my-bot"
        assert data["version"] == "0.1.0"
        assert data["role"] == "worker"
        assert data["constraints"]["max_tokens"] == 4096
        assert data["inputs"]["query"]["required"] is True

    def test_init_workflow_creates_valid_json_file(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["init", "deploy-pipeline", "-k", "workflow", "-o", str(tmp_path)]
        )
        assert result.exit_code == 0

        file = tmp_path / "deploy-pipeline.workflow.json"
        assert file.exists(), "Workflow JSON file was not created"
        data = json.loads(file.read_text(encoding="utf-8"))

        assert data["name"] == "deploy-pipeline"
        assert data["steps"][0]["action"] == "invoke-agent"
        assert data["execution"]["mode"] == "sequential"
        assert data["triggers"]["manual"] is True

    def test_init_unknown_kind_returns_error(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["init", "x", "-k", "banana", "-o", str(tmp_path)])
        assert result.exit_code == 1
        assert "Unknown kind: banana" in result.output


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------


class TestStatusCommand:
    """Call /health and display the result."""

    def test_status_displays_health_json_on_success(self) -> None:
        health_payload = {"status": "ok", "uptime": 42}
        mock_resp = _make_response(200, json_body=health_payload)
        mock_client = _mock_httpx_client(method="get", response=mock_resp)

        with patch("httpx.Client", return_value=mock_client):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert output_data["status"] == "ok"
        assert output_data["uptime"] == 42

    def test_status_connection_error_exits_1(self) -> None:
        mock_client = _mock_httpx_client(method="get", side_effect=httpx.ConnectError("refused"))

        with patch("httpx.Client", return_value=mock_client):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 1
        assert "Cannot connect to" in result.output


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------


class TestRunCommand:
    """Execute a workflow via the API."""

    def test_run_posts_workflow_and_prints_result(self) -> None:
        api_response = {"execution_id": "exec-1", "status": "completed"}
        mock_resp = _make_response(200, json_body=api_response, method="POST")
        mock_client = _mock_httpx_client(method="post", response=mock_resp)

        with patch("httpx.Client", return_value=mock_client):
            result = runner.invoke(
                app,
                ["run", "my-workflow", "-i", '{"key": "val"}', "-t", "secret-token"],
            )

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert output_data["execution_id"] == "exec-1"

        # Verify the POST was called with correct path, payload, and auth header
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/v1/workflows/my-workflow/execute"
        assert call_args[1]["json"]["inputs"] == {"key": "val"}
        assert call_args[1]["headers"]["Authorization"] == "Bearer secret-token"

    def test_run_invalid_json_inputs_exits_1(self) -> None:
        result = runner.invoke(app, ["run", "wf", "-i", "{bad json}"])
        assert result.exit_code == 1
        assert "Invalid JSON inputs" in result.output

    def test_run_api_error_exits_1(self) -> None:
        error_response = _make_response(
            403,
            json_body={"detail": "forbidden"},
            method="POST",
            url="http://localhost:8000/v1/workflows/wf/execute",
        )
        mock_client = _mock_httpx_client(method="post", response=error_response)

        with patch("httpx.Client", return_value=mock_client):
            result = runner.invoke(app, ["run", "wf"])

        assert result.exit_code == 1
        assert "API error 403" in result.output


# ---------------------------------------------------------------------------
# chat command
# ---------------------------------------------------------------------------


class TestChatCommand:
    """Send a chat message with optional skill preloading."""

    def test_chat_sends_message_with_preloaded_skills(self) -> None:
        api_response = {"reply": "hello back", "skill_used": "research-agent"}
        mock_resp = _make_response(200, json_body=api_response, method="POST")
        mock_client = _mock_httpx_client(method="post", response=mock_resp)

        with patch("httpx.Client", return_value=mock_client):
            result = runner.invoke(
                app,
                [
                    "chat",
                    "/research-agent analyze this",
                    "-p",
                    "research-agent",
                    "-p",
                    "deploy",
                ],
            )

        assert result.exit_code == 0
        output_data = json.loads(result.output)
        assert output_data["reply"] == "hello back"

        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/v1/chat"
        payload = call_args[1]["json"]
        assert payload["message"] == "/research-agent analyze this"
        assert payload["preloaded_skills"] == ["research-agent", "deploy"]

    def test_chat_uses_token_env_var_when_flag_omitted(self) -> None:
        mock_resp = _make_response(200, json_body={"reply": "ok"}, method="POST")
        mock_client = _mock_httpx_client(method="post", response=mock_resp)

        with (
            patch("httpx.Client", return_value=mock_client),
            patch.dict("os.environ", {"TOKEN": "env-secret"}, clear=False),
        ):
            result = runner.invoke(app, ["chat", "hi"])

        assert result.exit_code == 0
        call_args = mock_client.post.call_args
        assert call_args[1]["headers"]["Authorization"] == "Bearer env-secret"


# ---------------------------------------------------------------------------
# test command
# ---------------------------------------------------------------------------


class TestTestCommand:
    """Invoke pytest as a subprocess."""

    def test_test_command_invokes_pytest_with_path(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            result = runner.invoke(app, ["test", "tests/unit"])

        assert result.exit_code == 0
        cmd = mock_run.call_args[0][0]
        assert cmd[-1] == "tests/unit"
        assert "-m" in cmd and "pytest" in cmd

    def test_test_command_verbose_flag_appended(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            result = runner.invoke(app, ["test", "--verbose"])

        assert result.exit_code == 0
        cmd = mock_run.call_args[0][0]
        assert "-v" in cmd
