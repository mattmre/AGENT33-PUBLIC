"""agent33 diagnose — traffic-light health check for all subsystems."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import httpx

from agent33.cli.output import OutputMode


class Status(Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class CheckResult:
    name: str
    status: Status
    message: str
    fix_hint: str = field(default="")
    auto_fixable: bool = field(default=False)


def _icon(status: Status) -> str:
    icons = {
        Status.OK: "✓",
        Status.WARN: "!",
        Status.FAIL: "✗",
        Status.SKIP: "-",
    }
    return icons[status]


def _check_python_version() -> CheckResult:
    """Check Python version is >= 3.11."""
    v = sys.version_info
    if v >= (3, 11):
        return CheckResult("Python version", Status.OK, f"Python {v.major}.{v.minor}.{v.micro}")
    return CheckResult(
        "Python version",
        Status.FAIL,
        f"Python {v.major}.{v.minor} — requires 3.11+",
        fix_hint="Upgrade to Python 3.11 or later",
    )


def _check_env_file() -> CheckResult:
    """Check that .env or AGENT33_MODE environment variable is set."""
    env_path = Path(".env")
    env_local_path = Path(".env.local")
    agent33_mode = os.environ.get("AGENT33_MODE")

    if env_path.exists():
        return CheckResult(
            name="Environment config",
            status=Status.OK,
            message=".env found",
        )
    if env_local_path.exists():
        return CheckResult(
            name="Environment config",
            status=Status.OK,
            message=".env.local found",
        )
    if agent33_mode:
        return CheckResult(
            name="Environment config",
            status=Status.OK,
            message=f"AGENT33_MODE={agent33_mode}",
        )
    return CheckResult(
        name="Environment config",
        status=Status.WARN,
        message="No .env file and AGENT33_MODE not set",
        fix_hint="Run `agent33 bootstrap` to generate a .env.local with sensible defaults",
        auto_fixable=False,
    )


def _check_disk_space() -> CheckResult:
    """Check available disk space (warn <2 GB, fail <500 MB)."""
    try:
        total, used, free = shutil.disk_usage(".")
        free_gb = free / (1024**3)
        if free_gb >= 2.0:
            return CheckResult("Disk space", Status.OK, f"{free_gb:.1f} GB free")
        if free_gb >= 0.5:
            return CheckResult(
                "Disk space",
                Status.WARN,
                f"{free_gb:.1f} GB free — low",
                fix_hint="Free up disk space before running models",
            )
        return CheckResult(
            "Disk space",
            Status.FAIL,
            f"{free_gb:.1f} GB free — critically low",
            fix_hint="Free up at least 2 GB before running agent33",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult("Disk space", Status.SKIP, f"Could not check: {exc}")


def _check_port(port: int) -> CheckResult:
    """Check if a TCP port is available (not already in use)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(("127.0.0.1", port))
            if result == 0:
                return CheckResult(
                    f"Port {port}",
                    Status.WARN,
                    f"Port {port} is already in use",
                    fix_hint=f"Stop the process using port {port} or change AGENT33_PORT",
                )
            return CheckResult(f"Port {port}", Status.OK, f"Port {port} is available")
    except Exception as exc:  # noqa: BLE001
        return CheckResult(f"Port {port}", Status.SKIP, f"Could not check: {exc}")


def _check_ollama() -> CheckResult:
    """Check Ollama availability and running state."""
    import platform
    import urllib.request

    ollama_path = shutil.which("ollama")
    if not ollama_path:
        system = platform.system()
        if system == "Darwin":
            hint = "Install Ollama: brew install ollama  OR  https://ollama.ai/download"
        elif system == "Linux":
            hint = "Install Ollama: curl -fsSL https://ollama.ai/install.sh | sh"
        else:
            hint = "Install Ollama: https://ollama.ai/download"
        return CheckResult(
            "Ollama",
            Status.WARN,
            "Ollama not installed — needed for local LLM inference",
            fix_hint=hint,
        )

    # Check if ollama is running via HTTP
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)  # noqa: S310
        return CheckResult("Ollama", Status.OK, "Ollama is installed and running")
    except Exception:  # noqa: BLE001
        return CheckResult(
            "Ollama",
            Status.WARN,
            "Ollama is installed but not running",
            fix_hint="Start Ollama: `ollama serve` (or open the Ollama app)",
            auto_fixable=True,
        )


def _check_llm_config() -> CheckResult:
    """Check that some LLM provider is configured."""
    import urllib.request

    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    ollama_base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("DEFAULT_MODEL", "")

    if openrouter_key:
        model_info = f" (model: {model})" if model else ""
        return CheckResult("LLM provider", Status.OK, f"OpenRouter API key configured{model_info}")
    if openai_key:
        return CheckResult("LLM provider", Status.OK, "OpenAI API key configured")
    if anthropic_key:
        return CheckResult("LLM provider", Status.OK, "Anthropic API key configured")

    # Check if Ollama is accessible
    try:
        urllib.request.urlopen(f"{ollama_base}/api/tags", timeout=2)  # noqa: S310
        model_info = f" (model: {model})" if model else ""
        return CheckResult("LLM provider", Status.OK, f"Ollama reachable{model_info}")
    except Exception:  # noqa: BLE001
        pass

    return CheckResult(
        "LLM provider",
        Status.FAIL,
        "No LLM provider configured or reachable",
        fix_hint=(
            "Either: set OPENROUTER_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY, "
            "or install+start Ollama (https://ollama.ai/download)"
        ),
    )


def _check_database(db_url: str | None) -> CheckResult:
    """Check database configuration."""
    if not db_url:
        return CheckResult(
            "Database",
            Status.SKIP,
            "DATABASE_URL not set — using lite mode (no external DB required)",
        )
    if db_url.startswith("postgresql"):
        return CheckResult(
            "Database",
            Status.WARN,
            "PostgreSQL URL configured — connectivity not tested in diagnose",
            fix_hint="Ensure PostgreSQL is running and DATABASE_URL is correct",
        )
    return CheckResult("Database", Status.OK, f"Database URL configured: {db_url[:30]}...")


def _check_redis(redis_url: str | None) -> CheckResult:
    """Check Redis connectivity."""
    if not redis_url:
        return CheckResult(
            "Redis",
            Status.SKIP,
            "REDIS_URL not set — will use in-process cache in lite mode",
        )
    try:
        host = "localhost"
        port = 6379
        if "://" in redis_url:
            parts = redis_url.split("://")[-1].split(":")
            host = parts[0] or "localhost"
            port = int(parts[1].split("/")[0]) if len(parts) > 1 else 6379
        with socket.create_connection((host, port), timeout=2):
            return CheckResult("Redis", Status.OK, f"Redis reachable at {host}:{port}")
    except Exception:  # noqa: BLE001
        return CheckResult(
            "Redis",
            Status.FAIL,
            "Redis configured but not reachable",
            fix_hint="Start Redis: `redis-server` or `docker run -p 6379:6379 redis`",
        )


def _count_pack_manifests(pack_dir: Path) -> int:
    """Count pack manifest files under the configured pack directory."""
    if not pack_dir.is_dir():
        return 0
    return sum(1 for path in pack_dir.rglob("*") if path.name.lower() == "pack.yaml")


def _check_pack_workspace() -> CheckResult:
    """Check local pack configuration and signing readiness."""
    from agent33.config import Settings
    from agent33.packs.hub import PackHubConfig

    settings = Settings()
    pack_dir = Path(settings.pack_definitions_dir)
    cache_path = PackHubConfig().local_cache_path
    remote_sources_raw = settings.pack_marketplace_remote_sources.strip()
    remote_count = 0
    invalid_remote_sources = False

    if remote_sources_raw:
        try:
            parsed_sources = json.loads(remote_sources_raw)
            if isinstance(parsed_sources, list):
                remote_count = sum(1 for item in parsed_sources if isinstance(item, dict))
            else:
                invalid_remote_sources = True
        except json.JSONDecodeError:
            invalid_remote_sources = True

    manifest_count = _count_pack_manifests(pack_dir)
    cache_state = "present" if cache_path.exists() else "missing"
    sigstore_available = importlib.util.find_spec("sigstore") is not None
    message = (
        f"{manifest_count} manifest(s); remote sources={remote_count}; "
        f"hub cache {cache_state}; sigstore {'available' if sigstore_available else 'missing'}"
    )

    if invalid_remote_sources:
        return CheckResult(
            "Pack workspace",
            Status.WARN,
            "Pack remote sources config is not valid JSON",
            fix_hint=(
                "Set PACK_MARKETPLACE_REMOTE_SOURCES to a JSON array of remote source objects"
            ),
        )
    if remote_count > 0 and not sigstore_available:
        return CheckResult(
            "Pack workspace",
            Status.WARN,
            message,
            fix_hint="Install the optional sigstore package to enable keyless pack verification",
        )
    if not pack_dir.exists():
        return CheckResult(
            "Pack workspace",
            Status.WARN,
            message,
            fix_hint=f"Create {pack_dir} or point PACK_DEFINITIONS_DIR at your pack directory",
        )
    return CheckResult("Pack workspace", Status.OK, message)


def _check_pack_health_api(api_url: str, token: str | None) -> CheckResult:
    """Check live pack health summary from the running API when reachable."""
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = httpx.get(f"{api_url}/v1/packs/health", headers=headers, timeout=5)
    except httpx.ConnectError:
        return CheckResult(
            "Pack health API",
            Status.SKIP,
            f"{api_url} not reachable — skipping live pack health",
        )

    if resp.status_code in (401, 403):
        return CheckResult(
            "Pack health API",
            Status.WARN,
            f"Pack health API denied access ({resp.status_code})",
            fix_hint="Set TOKEN with agents:read scope or run the API in a trusted local context",
        )

    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return CheckResult(
            "Pack health API",
            Status.WARN,
            f"Pack health check failed ({exc.response.status_code})",
            fix_hint="Start agent33 and ensure /v1/packs/health is available",
        )
    try:
        payload = resp.json()
    except ValueError:
        return CheckResult(
            "Pack health API",
            Status.WARN,
            "Pack health API returned a non-JSON response",
            fix_hint="Check the API/proxy path and ensure /v1/packs/health returns JSON",
        )

    return CheckResult(
        "Pack health API",
        Status.OK,
        (
            f"{payload.get('total_packs', 0)} packs — "
            f"healthy {payload.get('healthy', 0)}, "
            f"degraded {payload.get('degraded', 0)}, "
            f"unhealthy {payload.get('unhealthy', 0)}"
        ),
    )


def _run_all_checks(
    *,
    api_url: str = "http://localhost:8000",
    token: str | None = None,
) -> list[CheckResult]:
    """Run all diagnostic checks and return results."""
    db_url = os.environ.get("DATABASE_URL")
    redis_url = os.environ.get("REDIS_URL")

    return [
        _check_python_version(),
        _check_env_file(),
        _check_disk_space(),
        _check_port(8000),
        _check_ollama(),
        _check_llm_config(),
        _check_database(db_url),
        _check_redis(redis_url),
        _check_pack_workspace(),
        _check_pack_health_api(api_url, token),
    ]


def _exit_code(results: list[CheckResult]) -> int:
    """Return the CLI exit code for a set of results."""
    if any(result.status == Status.FAIL for result in results):
        return 2
    if any(result.status == Status.WARN for result in results):
        return 1
    return 0


def _result_payload(results: list[CheckResult]) -> dict[str, object]:
    """Build a structured payload for JSON rendering."""
    return {
        "checks": [
            {
                "name": result.name,
                "status": result.status.value,
                "message": result.message,
                "fix_hint": result.fix_hint,
                "auto_fixable": result.auto_fixable,
            }
            for result in results
        ],
        "summary": {
            "exit_code": _exit_code(results),
            "ok": sum(1 for result in results if result.status == Status.OK),
            "warn": sum(1 for result in results if result.status == Status.WARN),
            "fail": sum(1 for result in results if result.status == Status.FAIL),
            "skip": sum(1 for result in results if result.status == Status.SKIP),
        },
    }


def _print_results(results: list[CheckResult], output_mode: OutputMode = OutputMode.HUMAN) -> int:
    """Print a traffic-light summary table.

    Returns exit code: 0 = all OK, 1 = warnings only, 2 = at least one FAIL.
    """
    exit_code = _exit_code(results)
    if output_mode == OutputMode.JSON:
        print(json.dumps(_result_payload(results), indent=2))
        return exit_code
    if output_mode == OutputMode.PLAIN:
        for result in results:
            print(
                "\t".join(
                    [
                        result.status.value,
                        result.name,
                        result.message,
                        result.fix_hint,
                    ]
                )
            )
        return exit_code

    print("\n=== AGENT-33 Diagnostic Report ===\n")
    has_fail = False
    has_warn = False

    for r in results:
        icon = _icon(r.status)
        print(f"  {icon}  {r.name:<25} {r.message}")
        if r.fix_hint:
            print(f"       {'':25} Hint: {r.fix_hint}")
        if r.status == Status.FAIL:
            has_fail = True
        if r.status == Status.WARN:
            has_warn = True

    print()
    if has_fail:
        print("  FAIL — fix the issues above before starting agent33")
        return 2
    if has_warn:
        print("  WARN — some optional features may not work")
        return 1
    print("  OK — all checks passed")
    return 0


def _apply_fixes(results: list[CheckResult]) -> None:
    """Apply auto-remediable fixes where safe."""
    import platform
    import subprocess

    fixable = [r for r in results if r.auto_fixable and r.status != Status.OK]
    if not fixable:
        print("No auto-fixable issues found.")
        return

    for r in fixable:
        print(f"\nFixing: {r.name}")
        if r.name == "Ollama" and "not running" in r.message:
            system = platform.system()
            if system == "Windows":
                print(
                    "  Starting Ollama... "
                    "(open the Ollama app or run 'ollama serve' in a terminal)"
                )
            else:
                try:
                    subprocess.Popen(  # noqa: S603
                        ["ollama", "serve"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    print("  Started 'ollama serve' in background")
                except Exception as exc:  # noqa: BLE001
                    print(f"  Could not start Ollama: {exc}")


def diagnose(
    fix: bool = False,
    *,
    output_mode: OutputMode = OutputMode.HUMAN,
    api_url: str = "http://localhost:8000",
    token: str | None = None,
) -> int:
    """Run diagnostic checks on all AGENT-33 subsystems.

    Checks Python version, environment config, disk space, port availability,
    Ollama, LLM provider, database, and Redis connectivity.

    Args:
        fix: Auto-remediate issues where safe to do so.

    Returns:
        Exit code: 0 = all OK, 1 = warnings, 2 = failures.
    """
    results = _run_all_checks(api_url=api_url, token=token)
    if fix and output_mode != OutputMode.HUMAN:
        _apply_fixes(results)
        results = _run_all_checks(api_url=api_url, token=token)
        return _print_results(results, output_mode=output_mode)

    exit_code = _print_results(results, output_mode=output_mode)

    if fix:
        if output_mode == OutputMode.HUMAN:
            print("\n--- Applying fixes ---")
        _apply_fixes(results)
        if output_mode == OutputMode.HUMAN:
            print("\n--- Re-checking after fixes ---")
        results = _run_all_checks(api_url=api_url, token=token)
        exit_code = _print_results(results, output_mode=output_mode)

    return exit_code
