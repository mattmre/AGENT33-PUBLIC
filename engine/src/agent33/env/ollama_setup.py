"""Helpers for first-run Ollama provisioning and model downloads."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
_OLLAMA_STARTUP_TIMEOUT_SECONDS = 90.0
_OLLAMA_PROBE_INTERVAL_SECONDS = 2.0
_OLLAMA_PULL_TIMEOUT_SECONDS = 1800.0


@dataclass(frozen=True)
class OllamaEnvironment:
    """Describe the local Ollama/bootstrap surfaces available to the wizard."""

    base_url: str
    binary_available: bool
    reachable: bool
    docker_compose_available: bool
    bundled_compose_dir: Path | None


def is_ollama_reachable(base_url: str = DEFAULT_OLLAMA_BASE_URL) -> bool:
    """Return True when the Ollama tags endpoint responds successfully."""
    try:
        with httpx.Client(timeout=2.0) as client:
            response = client.get(f"{base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
        return True
    except Exception:
        return False


def list_ollama_models(base_url: str = DEFAULT_OLLAMA_BASE_URL) -> list[str]:
    """Return all model names currently available from Ollama."""
    with httpx.Client(timeout=10.0) as client:
        response = client.get(f"{base_url.rstrip('/')}/api/tags")
        response.raise_for_status()
        payload = response.json()
    raw_models = payload.get("models", [])
    models: list[str] = []
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model")
        if isinstance(name, str) and name:
            models.append(name)
    return models


def pull_ollama_model(
    model: str,
    *,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    timeout: float = _OLLAMA_PULL_TIMEOUT_SECONDS,
) -> None:
    """Download a model into the reachable Ollama service."""
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{base_url.rstrip('/')}/api/pull",
            json={"name": model, "stream": False},
        )
        response.raise_for_status()


def start_local_ollama_service() -> bool:
    """Start ``ollama serve`` in the background when the binary is installed."""
    if shutil.which("ollama") is None:
        return False
    try:
        if os.name == "nt":
            creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0,
            )
            subprocess.Popen(  # noqa: S603
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        else:
            subprocess.Popen(  # noqa: S603
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        return True
    except Exception:
        return False


def start_bundled_ollama_service(compose_dir: Path) -> None:
    """Start the repo's bundled Ollama service via Docker Compose."""
    try:
        subprocess.run(  # noqa: S603
            ["docker", "compose", "--profile", "local-ollama", "up", "-d", "ollama"],
            cwd=compose_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            _format_process_failure(
                "docker compose failed to start bundled Ollama",
                returncode=exc.returncode,
                stdout=exc.stdout,
                stderr=exc.stderr,
            )
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            _format_process_failure(
                "docker compose timed out starting bundled Ollama",
                stdout=exc.stdout,
                stderr=exc.stderr,
            )
        ) from exc


def wait_for_ollama(
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    *,
    timeout: float = _OLLAMA_STARTUP_TIMEOUT_SECONDS,
) -> bool:
    """Poll the Ollama endpoint until it becomes reachable or times out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_ollama_reachable(base_url):
            return True
        time.sleep(_OLLAMA_PROBE_INTERVAL_SECONDS)
    return False


def docker_compose_available() -> bool:
    """Return True when ``docker compose`` is callable."""
    try:
        result = subprocess.run(  # noqa: S603
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def find_bundled_ollama_compose_dir(search_start: Path | None = None) -> Path | None:
    """Locate the repo directory that contains the bundled Ollama compose profile."""
    for candidate in _candidate_dirs(search_start):
        compose_path = candidate / "docker-compose.yml"
        if not compose_path.exists():
            continue
        try:
            content = compose_path.read_text(encoding="utf-8")
        except Exception:
            continue
        if "ollama:" in content and "local-ollama" in content:
            return candidate
    return None


def inspect_ollama_environment(
    *,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    search_start: Path | None = None,
) -> OllamaEnvironment:
    """Inspect whether local or bundled Ollama setup paths are available."""
    return OllamaEnvironment(
        base_url=base_url,
        binary_available=shutil.which("ollama") is not None,
        reachable=is_ollama_reachable(base_url),
        docker_compose_available=docker_compose_available(),
        bundled_compose_dir=find_bundled_ollama_compose_dir(search_start),
    )


def _candidate_dirs(search_start: Path | None) -> list[Path]:
    start = (search_start or Path.cwd()).resolve()
    cwd = Path.cwd().resolve()
    candidates: list[Path] = []
    seen: set[Path] = set()

    def _add(path: Path) -> None:
        if path in seen:
            return
        seen.add(path)
        candidates.append(path)

    for root in (start, cwd):
        for current in (root, *root.parents):
            _add(current)
            _add(current / "engine")
    return candidates


def _format_process_failure(
    message: str,
    *,
    returncode: int | None = None,
    stdout: str | bytes | None = None,
    stderr: str | bytes | None = None,
) -> str:
    """Render subprocess stdout/stderr into a single actionable error."""

    def _normalize(value: str | bytes | None) -> str:
        if isinstance(value, bytes):
            return value.decode(errors="replace").strip()
        if isinstance(value, str):
            return value.strip()
        return ""

    details: list[str] = []
    stderr_text = _normalize(stderr)
    stdout_text = _normalize(stdout)
    if stderr_text:
        details.append(f"stderr: {stderr_text}")
    if stdout_text and stdout_text != stderr_text:
        details.append(f"stdout: {stdout_text}")

    suffix = f" (exit code {returncode})" if returncode is not None else ""
    if not details:
        return f"{message}{suffix}"
    return f"{message}{suffix}: {' | '.join(details)}"
