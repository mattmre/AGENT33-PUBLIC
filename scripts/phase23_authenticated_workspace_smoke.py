"""Authenticated browser smoke for Phase 23 workspace live binding."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    engine_dir = repo_root / "engine"
    frontend_dir = repo_root / "frontend"
    evidence_dir = repo_root / "_internal" / "reviews"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = evidence_dir / "phase-23-authenticated-cockpit-smoke-2026-05-24.png"

    backend_port = _available_port(8059)
    frontend_port = _available_port(3059)
    backend_url = f"http://127.0.0.1:{backend_port}"
    frontend_url = f"http://127.0.0.1:{frontend_port}"

    backend = _start_backend(repo_root, engine_dir, backend_port, frontend_url)
    frontend = _start_frontend(frontend_dir, frontend_port)
    try:
        _wait_for_url(f"{backend_url}/health", "backend health")
        _wait_for_url(frontend_url, "frontend dev server")
        _run_browser_smoke(frontend_url, backend_url, screenshot_path)
    finally:
        _stop_process(frontend)
        _stop_process(backend)

    print("PHASE23_AUTH_BROWSER_SMOKE PASS")
    print(f"backend_url={backend_url}")
    print(f"frontend_url={frontend_url}")
    print(f"screenshot={screenshot_path}")
    return 0


def _available_port(preferred: int) -> int:
    if _can_bind(preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _can_bind(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


def _start_backend(
    repo_root: Path,
    engine_dir: Path,
    port: int,
    frontend_url: str,
) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": os.pathsep.join([str(engine_dir / "src"), str(repo_root)]),
            "AGENT33_MODE": "lite",
            "ENVIRONMENT": "test",
            "JWT_SECRET": "phase23-browser-smoke-secret",
            "AUTH_BOOTSTRAP_ENABLED": "true",
            "AUTH_BOOTSTRAP_ADMIN_USERNAME": "admin",
            "AUTH_BOOTSTRAP_ADMIN_PASSWORD": "Phase23Admin1!",
            "AUTH_BOOTSTRAP_ADMIN_SCOPES": (
                "admin,workspaces:read,workspaces:write,sessions:read,sessions:write"
            ),
            "PHASE23_LIFECYCLE_BACKEND": "sqlite",
            "PHASE23_AUTH_DB_PATH": "var/phase23-smoke/auth-lifecycle.db",
            "PHASE23_WORKSPACE_DB_PATH": "var/phase23-smoke/workspace-lifecycle.db",
            "CORS_ALLOWED_ORIGINS": frontend_url,
        }
    )
    python = str(engine_dir / ".venv" / "Scripts" / "python.exe")
    if not Path(python).exists():
        python = sys.executable
    return subprocess.Popen(
        [
            python,
            "-m",
            "uvicorn",
            "scripts.phase23_smoke_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
            "--lifespan",
            "off",
        ],
        cwd=repo_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _start_frontend(frontend_dir: Path, port: int) -> subprocess.Popen[str]:
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError("npm is required for the frontend browser smoke")
    return subprocess.Popen(
        [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port)],
        cwd=frontend_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_for_url(url: str, label: str, timeout_seconds: float = 90.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if 200 <= response.status < 500:
                    return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {label} at {url}: {last_error}")


def _run_browser_smoke(frontend_url: str, backend_url: str, screenshot_path: Path) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route(
            "**/runtime-config.js",
            lambda route: route.fulfill(
                status=200,
                content_type="application/javascript",
                body=f'window.__AGENT33_CONFIG__ = {{ API_BASE_URL: "{backend_url}" }};',
            ),
        )

        page.goto(f"{frontend_url}/?view=setup&workspace=solo-builder", wait_until="networkidle")
        page.get_by_label("Username").fill("admin")
        page.get_by_label("Password").fill("Phase23Admin1!")
        page.get_by_role("button", name="Sign In").click()
        page.wait_for_function(
            "() => (window.localStorage.getItem('agent33.token') || '').length > 20"
        )

        with page.expect_response(
            lambda response: response.url == f"{backend_url}/v1/workspaces/"
            and response.status == 200
        ):
            page.goto(
                f"{frontend_url}/?view=operations&workspace=solo-builder"
                "&permission=ask&operatorMode=pro",
                wait_until="networkidle",
            )
        expect(page.get_by_text("Live backend").first).to_be_visible(timeout=10_000)
        expect(page.get_by_role("heading", name="Solo Builder").first).to_be_visible()
        expect(
            page.get_by_text("No live recovery checkpoints are currently open.").first
        ).to_be_visible()
        page.screenshot(path=str(screenshot_path), full_page=True)
        browser.close()


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
