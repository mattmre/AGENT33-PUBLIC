from __future__ import annotations

from agent33 import config as config_module
from agent33.config import Settings


def test_runtime_service_url_rewrites_loopback_inside_container(
    monkeypatch,
) -> None:
    monkeypatch.setattr(config_module.os.path, "exists", lambda path: path == "/.dockerenv")

    resolved = config_module.resolve_runtime_service_url("http://localhost:11434")

    assert resolved == "http://host.docker.internal:11434"


def test_runtime_service_url_preserves_non_loopback_hosts(monkeypatch) -> None:
    monkeypatch.setattr(config_module.os.path, "exists", lambda path: path == "/.dockerenv")

    resolved = config_module.resolve_runtime_service_url("http://ollama:11434")

    assert resolved == "http://ollama:11434"


def test_runtime_local_orchestration_base_url_rewrites_loopback_inside_container(
    monkeypatch,
) -> None:
    monkeypatch.setattr(config_module.os.path, "exists", lambda path: path == "/.dockerenv")

    settings = Settings(local_orchestration_base_url="http://localhost:8033/v1")

    assert settings.runtime_local_orchestration_base_url == "http://host.docker.internal:8033/v1"
