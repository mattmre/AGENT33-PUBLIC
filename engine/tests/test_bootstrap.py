"""Tests for agent33 bootstrap command."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from agent33.cli.bootstrap import ENV_TEMPLATE, _generate_api_key, _generate_secret, app

if TYPE_CHECKING:
    from pathlib import Path


def test_generate_secret_length() -> None:
    secret = _generate_secret(64)
    assert len(secret) == 64


def test_generate_secret_custom_length() -> None:
    secret = _generate_secret(32)
    assert len(secret) == 32


def test_generate_secret_uniqueness() -> None:
    s1 = _generate_secret()
    s2 = _generate_secret()
    assert s1 != s2


def test_generate_secret_alphanumeric() -> None:
    """All characters must be alphanumeric (no special chars that break shell quoting)."""
    secret = _generate_secret(128)
    assert secret.isalnum()


def test_generate_api_key_prefix() -> None:
    key = _generate_api_key()
    assert key.startswith("agent33_dev_")


def test_generate_api_key_uniqueness() -> None:
    k1 = _generate_api_key()
    k2 = _generate_api_key()
    assert k1 != k2


def test_generate_api_key_length() -> None:
    """Key should be well over 20 chars due to base64url suffix."""
    key = _generate_api_key()
    assert len(key) > 20


def test_env_template_contains_required_fields() -> None:
    """Template must have placeholder slots for jwt_secret and api_key."""
    assert "{jwt_secret}" in ENV_TEMPLATE
    assert "{api_key}" in ENV_TEMPLATE
    assert "AGENT33_MODE=lite" in ENV_TEMPLATE
    assert "JWT_SECRET=" in ENV_TEMPLATE
    assert "AGENT33_DEV_API_KEY=" in ENV_TEMPLATE


def test_bootstrap_creates_file(tmp_path: Path) -> None:
    runner = CliRunner()
    output = tmp_path / ".env.local"
    result = runner.invoke(app, ["--output", str(output)])
    assert result.exit_code == 0
    assert output.exists()
    content = output.read_text()
    assert "JWT_SECRET=" in content
    assert "AGENT33_MODE=lite" in content
    assert "AGENT33_DEV_API_KEY=" in content
    assert "OLLAMA_DEFAULT_MODEL=llama3.2:3b" in content


def test_bootstrap_secret_in_file_is_64_chars(tmp_path: Path) -> None:
    """The generated JWT_SECRET written to the file must be exactly 64 chars."""
    runner = CliRunner()
    output = tmp_path / ".env.local"
    runner.invoke(app, ["--output", str(output)])
    content = output.read_text()
    jwt_line = next(line for line in content.splitlines() if line.startswith("JWT_SECRET="))
    value = jwt_line.split("=", 1)[1]
    assert len(value) == 64, f"Expected 64 chars, got {len(value)}: {value!r}"


def test_bootstrap_api_key_in_file_has_prefix(tmp_path: Path) -> None:
    runner = CliRunner()
    output = tmp_path / ".env.local"
    runner.invoke(app, ["--output", str(output)])
    content = output.read_text()
    api_line = next(
        line for line in content.splitlines() if line.startswith("AGENT33_DEV_API_KEY=")
    )
    value = api_line.split("=", 1)[1]
    assert value.startswith("agent33_dev_")


def test_bootstrap_contains_warnings(tmp_path: Path) -> None:
    runner = CliRunner()
    output = tmp_path / ".env.local"
    result = runner.invoke(app, ["--output", str(output)])
    # WARNING should appear either in stdout or in the file itself
    assert "WARNING" in result.output or "WARNING" in output.read_text()


def test_bootstrap_no_overwrite_by_default(tmp_path: Path) -> None:
    runner = CliRunner()
    output = tmp_path / ".env.local"
    output.write_text("existing content")
    result = runner.invoke(app, ["--output", str(output)])
    assert result.exit_code == 1
    assert output.read_text() == "existing content"


def test_bootstrap_force_overwrite(tmp_path: Path) -> None:
    runner = CliRunner()
    output = tmp_path / ".env.local"
    output.write_text("old content")
    result = runner.invoke(app, ["--output", str(output), "--force"])
    assert result.exit_code == 0
    content = output.read_text()
    assert "JWT_SECRET=" in content
    assert "old content" not in content


def test_bootstrap_generates_unique_secrets(tmp_path: Path) -> None:
    runner = CliRunner()
    out1 = tmp_path / "env1"
    out2 = tmp_path / "env2"
    runner.invoke(app, ["--output", str(out1)])
    runner.invoke(app, ["--output", str(out2)])
    c1 = out1.read_text()
    c2 = out2.read_text()
    jwt1 = next(line for line in c1.splitlines() if line.startswith("JWT_SECRET="))
    jwt2 = next(line for line in c2.splitlines() if line.startswith("JWT_SECRET="))
    assert jwt1 != jwt2, "Two bootstrap runs must not produce the same JWT_SECRET"


def test_bootstrap_generates_unique_api_keys(tmp_path: Path) -> None:
    runner = CliRunner()
    out1 = tmp_path / "env1"
    out2 = tmp_path / "env2"
    runner.invoke(app, ["--output", str(out1)])
    runner.invoke(app, ["--output", str(out2)])
    c1 = out1.read_text()
    c2 = out2.read_text()
    key1 = next(line for line in c1.splitlines() if line.startswith("AGENT33_DEV_API_KEY="))
    key2 = next(line for line in c2.splitlines() if line.startswith("AGENT33_DEV_API_KEY="))
    assert key1 != key2, "Two bootstrap runs must not produce the same API key"


def test_bootstrap_output_contains_next_steps(tmp_path: Path) -> None:
    runner = CliRunner()
    output = tmp_path / ".env.local"
    result = runner.invoke(app, ["--output", str(output)])
    assert "Next steps" in result.output


def test_bootstrap_via_main_app(tmp_path: Path) -> None:
    """bootstrap command must be reachable via the top-level `agent33` CLI."""
    from agent33.cli.main import app as main_app

    runner = CliRunner()
    output = tmp_path / ".env.local"
    result = runner.invoke(main_app, ["bootstrap", "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert output.exists()
    assert "JWT_SECRET=" in output.read_text()


def test_config_auto_jwt_in_lite_mode() -> None:
    """In lite mode with default JWT_SECRET, config auto-generates a secret."""
    from agent33.config import Settings

    s = Settings(
        agent33_mode="lite",
        environment="production",  # would normally fail, but lite mode auto-generates
    )
    # Must NOT be the default placeholder
    assert s.jwt_secret.get_secret_value() != "change-me-in-production"
    # Must be 64 chars (our generated length)
    assert len(s.jwt_secret.get_secret_value()) == 64


def test_config_auto_jwt_in_development_env() -> None:
    """In development environment, config auto-generates if secret is default."""
    from agent33.config import Settings

    s = Settings(environment="development")
    assert s.jwt_secret.get_secret_value() != "change-me-in-production"


def test_config_explicit_jwt_secret_preserved() -> None:
    """An explicitly provided JWT_SECRET must never be replaced."""
    from pydantic import SecretStr

    from agent33.config import Settings

    explicit = "my-explicit-secret-that-is-very-long-and-random"
    s = Settings(agent33_mode="lite", jwt_secret=SecretStr(explicit))
    assert s.jwt_secret.get_secret_value() == explicit


def test_settings_load_env_local_after_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings should load .env.local and let it override .env values."""
    from agent33.config import Settings

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OLLAMA_DEFAULT_MODEL", raising=False)
    (tmp_path / ".env").write_text("OLLAMA_DEFAULT_MODEL=tinyllama:1.1b\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text(
        "OLLAMA_DEFAULT_MODEL=llama3.1:8b\n",
        encoding="utf-8",
    )

    settings = Settings()

    assert settings.ollama_default_model == "llama3.1:8b"


def test_config_standard_mode_non_dev_env_raises() -> None:
    """Standard mode + non-dev environment + default JWT_SECRET must SystemExit."""
    from agent33.config import Settings

    with pytest.raises(SystemExit):
        Settings(agent33_mode="standard", environment="production")
