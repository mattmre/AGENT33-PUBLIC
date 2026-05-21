"""Tests for agent33 diagnose command."""

from __future__ import annotations

import json
import socket
from typing import TYPE_CHECKING
from unittest.mock import patch

from typer.testing import CliRunner

from agent33.cli.diagnose import (
    CheckResult,
    Status,
    _check_database,
    _check_disk_space,
    _check_env_file,
    _check_llm_config,
    _check_ollama,
    _check_pack_health_api,
    _check_pack_workspace,
    _check_port,
    _check_python_version,
    _check_redis,
    _print_results,
    _run_all_checks,
    diagnose,
)
from agent33.cli.main import app

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------


def test_check_python_version_current() -> None:
    """Current interpreter is always >=3.11 in this project."""
    result = _check_python_version()
    assert result.status == Status.OK
    assert "3.1" in result.message  # e.g. "Python 3.11.x"


def test_check_disk_space_returns_result() -> None:
    result = _check_disk_space()
    assert result.name == "Disk space"
    assert result.status in (Status.OK, Status.WARN, Status.FAIL)
    # Should include a GB quantity in the message (unless SKIP)
    if result.status != Status.SKIP:
        assert "GB" in result.message


def test_check_disk_space_critically_low() -> None:
    """Simulate critically low disk space (<500 MB)."""
    # 100 MB free
    one_hundred_mb = 100 * 1024 * 1024
    ten_tb = 10**12
    with patch(
        "shutil.disk_usage",
        return_value=(ten_tb, ten_tb - one_hundred_mb, one_hundred_mb),
    ):
        result = _check_disk_space()
    assert result.status == Status.FAIL
    assert "critically low" in result.message


def test_check_disk_space_low_but_not_critical() -> None:
    """Simulate low but non-critical disk space (500 MB – 2 GB)."""
    one_gb = 1024**3
    with patch("shutil.disk_usage", return_value=(10 * one_gb, 9 * one_gb, one_gb)):
        result = _check_disk_space()
    assert result.status == Status.WARN
    assert "low" in result.message


def test_check_disk_space_ample() -> None:
    """Simulate ample disk space (>2 GB)."""
    five_gb = 5 * 1024**3
    with patch("shutil.disk_usage", return_value=(10 * 1024**3, 5 * 1024**3, five_gb)):
        result = _check_disk_space()
    assert result.status == Status.OK


def test_check_port_available() -> None:
    """Port 19999 is very unlikely to be in use."""
    result = _check_port(19999)
    assert result.status == Status.OK
    assert "available" in result.message


def test_check_port_in_use() -> None:
    """Bind a real port then verify the check detects it as in-use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.listen(1)
        result = _check_port(port)
    assert result.status == Status.WARN
    assert str(port) in result.message
    assert result.fix_hint != ""


def test_check_env_file_with_env_var(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT33_MODE", "lite")
    result = _check_env_file()
    assert result.status == Status.OK
    assert "lite" in result.message


def test_check_env_file_with_dot_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT33_MODE", raising=False)
    monkeypatch.chdir(tmp_path)
    # Create a .env file in the cwd
    (tmp_path / ".env").write_text("FOO=bar\n")
    result = _check_env_file()
    assert result.status == Status.OK
    assert ".env" in result.message


def test_check_env_file_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT33_MODE", raising=False)
    monkeypatch.chdir(tmp_path)
    result = _check_env_file()
    assert result.status == Status.WARN
    assert result.fix_hint != ""


def test_check_ollama_not_installed() -> None:
    with patch("shutil.which", return_value=None):
        result = _check_ollama()
    assert result.status == Status.WARN
    assert "not installed" in result.message.lower()
    assert result.fix_hint != ""


def test_check_ollama_installed_and_running() -> None:
    with patch("shutil.which", return_value="/usr/bin/ollama"), patch("urllib.request.urlopen"):
        result = _check_ollama()
    assert result.status == Status.OK
    assert "running" in result.message.lower()


def test_check_ollama_installed_not_running() -> None:
    with (
        patch("shutil.which", return_value="/usr/bin/ollama"),
        patch("urllib.request.urlopen", side_effect=Exception("Connection refused")),
    ):
        result = _check_ollama()
    assert result.status == Status.WARN
    assert "not running" in result.message.lower()
    assert result.auto_fixable is True


def test_check_llm_config_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("DEFAULT_MODEL", "openrouter/auto")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = _check_llm_config()
    assert result.status == Status.OK
    assert "OpenRouter" in result.message
    assert "openrouter/auto" in result.message


def test_check_redis_no_url() -> None:
    result = _check_redis(None)
    assert result.status == Status.SKIP
    assert "lite mode" in result.message


def test_check_redis_reachable() -> None:
    """Simulate a reachable Redis by mocking socket.create_connection."""
    with patch("socket.create_connection"):
        result = _check_redis("redis://localhost:6379")
    assert result.status == Status.OK
    assert "reachable" in result.message


def test_check_redis_not_reachable() -> None:
    with patch("socket.create_connection", side_effect=OSError("refused")):
        result = _check_redis("redis://localhost:6379")
    assert result.status == Status.FAIL
    assert "not reachable" in result.message
    assert result.fix_hint != ""


def test_check_database_no_url() -> None:
    result = _check_database(None)
    assert result.status == Status.SKIP


def test_check_database_postgresql() -> None:
    result = _check_database("postgresql://user:pass@localhost:5432/db")
    assert result.status == Status.WARN
    assert "PostgreSQL" in result.message


def test_check_database_other_url() -> None:
    result = _check_database("sqlite:///agent33.db")
    assert result.status == Status.OK


def test_check_pack_workspace_with_manifests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packs_dir = tmp_path / "packs"
    pack_dir = packs_dir / "demo-pack"
    pack_dir.mkdir(parents=True)
    (pack_dir / "PACK.yaml").write_text("name: demo-pack\nversion: '1.0.0'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PACK_DEFINITIONS_DIR", str(packs_dir))
    monkeypatch.delenv("PACK_MARKETPLACE_REMOTE_SOURCES", raising=False)

    result = _check_pack_workspace()
    assert result.status == Status.OK
    assert "1 manifest" in result.message


def test_check_pack_workspace_invalid_remote_sources_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PACK_DEFINITIONS_DIR", str(packs_dir))
    monkeypatch.setenv("PACK_MARKETPLACE_REMOTE_SOURCES", "{bad json")

    result = _check_pack_workspace()
    assert result.status == Status.WARN
    assert "not valid JSON" in result.message


def test_check_pack_health_api_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, int]:
            return {"total_packs": 2, "healthy": 1, "degraded": 1, "unhealthy": 0}

    monkeypatch.setattr("httpx.get", lambda *a, **kw: FakeResponse())
    result = _check_pack_health_api("http://localhost:8000", None)
    assert result.status == Status.OK
    assert "2 packs" in result.message


def test_check_pack_health_api_denied_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 403

    monkeypatch.setattr("httpx.get", lambda *a, **kw: FakeResponse())
    result = _check_pack_health_api("http://localhost:8000", None)
    assert result.status == Status.WARN
    assert "denied access" in result.message


def test_check_pack_health_api_invalid_json_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, int]:
            raise json.JSONDecodeError("bad", "body", 0)

    monkeypatch.setattr("httpx.get", lambda *a, **kw: FakeResponse())
    result = _check_pack_health_api("http://localhost:8000", None)
    assert result.status == Status.WARN
    assert "non-JSON" in result.message


def test_check_llm_config_with_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("DEFAULT_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = _check_llm_config()
    assert result.status == Status.OK
    assert "openai" in result.message.lower()


def test_check_llm_config_with_anthropic_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("DEFAULT_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = _check_llm_config()
    assert result.status == Status.OK
    assert "anthropic" in result.message.lower()


def test_check_llm_config_ollama_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("urllib.request.urlopen"):
        result = _check_llm_config()
    assert result.status == Status.OK
    assert "ollama" in result.message.lower()


def test_check_llm_config_no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("urllib.request.urlopen", side_effect=Exception("no ollama")):
        result = _check_llm_config()
    assert result.status == Status.FAIL
    assert result.fix_hint != ""


# ---------------------------------------------------------------------------
# _print_results exit codes
# ---------------------------------------------------------------------------


def test_print_results_all_ok(capsys: pytest.CaptureFixture[str]) -> None:
    results = [CheckResult("A", Status.OK, "good"), CheckResult("B", Status.SKIP, "skipped")]
    code = _print_results(results)
    assert code == 0
    captured = capsys.readouterr()
    assert "OK" in captured.out


def test_print_results_with_warning(capsys: pytest.CaptureFixture[str]) -> None:
    results = [
        CheckResult("A", Status.OK, "good"),
        CheckResult("B", Status.WARN, "something off", fix_hint="do X"),
    ]
    code = _print_results(results)
    assert code == 1
    captured = capsys.readouterr()
    assert "WARN" in captured.out
    assert "Hint: do X" in captured.out


def test_print_results_with_failure(capsys: pytest.CaptureFixture[str]) -> None:
    results = [
        CheckResult("A", Status.FAIL, "broken"),
        CheckResult("B", Status.WARN, "meh"),
    ]
    code = _print_results(results)
    assert code == 2
    captured = capsys.readouterr()
    assert "FAIL" in captured.out


# ---------------------------------------------------------------------------
# _run_all_checks integration
# ---------------------------------------------------------------------------


def test_run_all_checks_returns_list() -> None:
    results = _run_all_checks()
    assert isinstance(results, list)
    assert len(results) >= 5  # at minimum python, env, disk, port, ollama
    names = {r.name for r in results}
    assert "Python version" in names
    assert "Disk space" in names
    assert "Ollama" in names


# ---------------------------------------------------------------------------
# diagnose() function — exit code contract
# ---------------------------------------------------------------------------


def test_diagnose_returns_int(monkeypatch: pytest.MonkeyPatch) -> None:
    """diagnose() returns an int exit code."""
    monkeypatch.setenv("AGENT33_MODE", "lite")
    code = diagnose(fix=False)
    assert isinstance(code, int)
    assert code in (0, 1, 2)


def test_diagnose_fix_reruns_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """diagnose(fix=True) runs checks twice (initial + after fix attempt)."""
    monkeypatch.setenv("AGENT33_MODE", "lite")
    call_count = 0
    original = _run_all_checks

    def counting_run(*args, **kwargs) -> list[CheckResult]:
        nonlocal call_count
        call_count += 1
        return original()

    with patch("agent33.cli.diagnose._run_all_checks", side_effect=counting_run):
        diagnose(fix=True)

    assert call_count == 2


# ---------------------------------------------------------------------------
# Typer CLI integration
# ---------------------------------------------------------------------------


def test_diagnose_cli_command_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """The typer CLI diagnose command runs without crashing."""
    monkeypatch.setenv("AGENT33_MODE", "lite")
    runner = CliRunner()
    result = runner.invoke(app, ["diagnose"])
    # Exit code 0, 1, or 2 are all valid depending on environment
    assert result.exit_code in (0, 1, 2)
    assert "AGENT-33 Diagnostic Report" in result.output


def test_diagnose_cli_fix_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """The --fix flag is accepted by the CLI and triggers fix logic."""
    monkeypatch.setenv("AGENT33_MODE", "lite")
    runner = CliRunner()
    result = runner.invoke(app, ["diagnose", "--fix"])
    assert result.exit_code in (0, 1, 2)
    # fix path emits "Applying fixes" section
    assert "Applying fixes" in result.output


def test_diagnose_cli_json_output() -> None:
    runner = CliRunner()
    sample_results = [
        CheckResult("Python version", Status.OK, "good"),
        CheckResult(
            "Pack workspace",
            Status.WARN,
            "missing sigstore",
            fix_hint="install sigstore",
        ),
    ]
    with patch("agent33.cli.diagnose._run_all_checks", return_value=sample_results):
        result = runner.invoke(app, ["diagnose", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["summary"]["warn"] == 1
    assert payload["checks"][1]["name"] == "Pack workspace"


def test_diagnose_cli_plain_output() -> None:
    runner = CliRunner()
    sample_results = [
        CheckResult("Python version", Status.OK, "good"),
        CheckResult("Pack workspace", Status.WARN, "needs attention", fix_hint="fix it"),
    ]
    with patch("agent33.cli.diagnose._run_all_checks", return_value=sample_results):
        result = runner.invoke(app, ["diagnose", "--plain"])

    assert result.exit_code == 1
    assert "ok\tPython version\tgood\t" in result.output
    assert "warn\tPack workspace\tneeds attention\tfix it" in result.output


def test_diagnose_cli_rejects_conflicting_output_flags() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["diagnose", "--json", "--plain"])
    assert result.exit_code != 0
    assert "Use only one of --json or --plain" in result.output


def test_diagnose_cli_fix_json_outputs_single_payload() -> None:
    runner = CliRunner()
    initial = [CheckResult("Pack workspace", Status.WARN, "warned")]
    final = [CheckResult("Pack workspace", Status.OK, "fixed")]
    with (
        patch("agent33.cli.diagnose._run_all_checks", side_effect=[initial, final]),
        patch("agent33.cli.diagnose._apply_fixes"),
    ):
        result = runner.invoke(app, ["diagnose", "--fix", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["summary"]["ok"] == 1
    assert payload["summary"]["warn"] == 0
