"""Tests for first-run Ollama provisioning helpers."""

from __future__ import annotations

import subprocess

import pytest

from agent33.env.ollama_setup import (
    find_bundled_ollama_compose_dir,
    inspect_ollama_environment,
    start_bundled_ollama_service,
)


def test_find_bundled_ollama_compose_dir_prefers_engine_directory(tmp_path) -> None:
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    (engine_dir / "docker-compose.yml").write_text(
        "services:\n"
        "  ollama:\n"
        "    image: ollama/ollama:latest\n"
        "    profiles:\n"
        "      - local-ollama\n",
        encoding="utf-8",
    )

    found = find_bundled_ollama_compose_dir(tmp_path)

    assert found == engine_dir


def test_inspect_ollama_environment_reports_binary_and_bundled_paths(
    tmp_path,
    monkeypatch,
) -> None:
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    (engine_dir / "docker-compose.yml").write_text(
        "services:\n"
        "  ollama:\n"
        "    image: ollama/ollama:latest\n"
        "    profiles:\n"
        "      - local-ollama\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "agent33.env.ollama_setup.shutil.which",
        lambda cmd: "/usr/bin/ollama" if cmd == "ollama" else None,
    )
    monkeypatch.setattr("agent33.env.ollama_setup.is_ollama_reachable", lambda _base_url: False)
    monkeypatch.setattr("agent33.env.ollama_setup.docker_compose_available", lambda: True)

    env = inspect_ollama_environment(search_start=tmp_path)

    assert env.binary_available is True
    assert env.reachable is False
    assert env.docker_compose_available is True
    assert env.bundled_compose_dir == engine_dir


def test_start_bundled_ollama_service_surfaces_compose_output(
    tmp_path,
    monkeypatch,
) -> None:
    def _fail(*_args, **_kwargs):
        raise subprocess.CalledProcessError(
            1,
            ["docker", "compose"],
            output="compose stdout",
            stderr="compose stderr",
        )

    monkeypatch.setattr("agent33.env.ollama_setup.subprocess.run", _fail)

    with pytest.raises(RuntimeError) as exc_info:
        start_bundled_ollama_service(tmp_path)

    message = str(exc_info.value)
    assert "compose stderr" in message
    assert "compose stdout" in message
