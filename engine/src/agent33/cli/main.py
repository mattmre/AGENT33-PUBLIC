"""AGENT-33 CLI application."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import typer

from agent33.cli.bench import bench_app
from agent33.cli.bootstrap import _bootstrap_generate
from agent33.cli.output import resolve_output_mode
from agent33.cli.packs import packs_app
from agent33.cli.skills import skills_app
from agent33.cli.tools import tools_app
from agent33.env.cli import app as env_app

app = typer.Typer(
    name="agent33",
    help="AGENT-33 -- Autonomous AI agent orchestration engine.",
    add_completion=False,
)
app.add_typer(bench_app, name="bench")
app.add_typer(env_app, name="env")
app.add_typer(tools_app)
app.add_typer(skills_app)
app.add_typer(packs_app, name="packs")


@app.command()
def init(
    name: str = typer.Argument(..., help="Name of the agent or workflow to scaffold."),
    kind: str = typer.Option(
        "agent",
        "--kind",
        "-k",
        help="Type of definition to create: 'agent' or 'workflow'.",
    ),
    output_dir: str = typer.Option(
        ".",
        "--output",
        "-o",
        help="Directory to write the scaffolded file into.",
    ),
) -> None:
    """Scaffold a new agent or workflow definition."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    definition: dict[str, Any]
    if kind == "agent":
        definition = {
            "name": name,
            "version": "0.1.0",
            "role": "worker",
            "description": f"{name} agent",
            "capabilities": [],
            "inputs": {
                "query": {
                    "type": "string",
                    "description": "Input query",
                    "required": True,
                }
            },
            "outputs": {
                "result": {
                    "type": "string",
                    "description": "Output result",
                }
            },
            "dependencies": [],
            "prompts": {"system": "", "user": "", "examples": []},
            "constraints": {
                "max_tokens": 4096,
                "timeout_seconds": 120,
                "max_retries": 2,
                "parallel_allowed": True,
            },
            "metadata": {"author": "", "tags": []},
        }
        file_path = out / f"{name}.agent.json"
    elif kind == "workflow":
        definition = {
            "name": name,
            "version": "0.1.0",
            "description": f"{name} workflow",
            "triggers": {"manual": True},
            "inputs": {},
            "outputs": {},
            "steps": [
                {
                    "id": "step-1",
                    "name": "First step",
                    "action": "invoke-agent",
                    "agent": "my-agent",
                    "inputs": {},
                    "outputs": {},
                }
            ],
            "execution": {"mode": "sequential"},
            "metadata": {"author": "", "tags": []},
        }
        file_path = out / f"{name}.workflow.json"
    else:
        typer.echo(f"Unknown kind: {kind}. Use 'agent' or 'workflow'.", err=True)
        raise typer.Exit(code=1)

    file_path.write_text(json.dumps(definition, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"Created {file_path}")


@app.command()
def run(
    workflow: str = typer.Argument(..., help="Name of the workflow to execute."),
    base_url: str = typer.Option(
        "http://localhost:8000",
        "--base-url",
        "-b",
        help="API base URL.",
    ),
    inputs: str | None = typer.Option(
        None,
        "--inputs",
        "-i",
        help="JSON string of workflow inputs.",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        "-t",
        help="Bearer token for protected workflow execution. Falls back to TOKEN env var.",
    ),
) -> None:
    """Execute a workflow by name via the API."""
    import httpx

    payload: dict[str, object] = {"inputs": {}}
    if inputs:
        try:
            payload["inputs"] = json.loads(inputs)
        except json.JSONDecodeError as exc:
            typer.echo(f"Invalid JSON inputs: {exc}", err=True)
            raise typer.Exit(code=1) from exc

    auth_token = token or os.getenv("TOKEN")
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    try:
        with httpx.Client(base_url=base_url, timeout=120.0) as client:
            resp = client.post(
                f"/v1/workflows/{workflow}/execute",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            typer.echo(json.dumps(resp.json(), indent=2))
    except httpx.HTTPStatusError as exc:
        typer.echo(f"API error {exc.response.status_code}: {exc.response.text}", err=True)
        raise typer.Exit(code=1) from exc
    except httpx.ConnectError as exc:
        typer.echo(f"Cannot connect to {base_url}: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def test(
    path: str = typer.Argument("tests", help="Path to the test directory or file."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output."),
) -> None:
    """Run the test suite using pytest."""
    import subprocess

    cmd = [sys.executable, "-m", "pytest", path]
    if verbose:
        cmd.append("-v")
    result = subprocess.run(cmd, check=False)
    raise typer.Exit(code=result.returncode)


@app.command()
def chat(
    message: str = typer.Argument(..., help="Message text (may start with /skill-name)."),
    base_url: str = typer.Option(
        "http://localhost:8000",
        "--base-url",
        "-b",
        help="API base URL.",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        "-t",
        help="Bearer token. Falls back to TOKEN env var.",
    ),
    preload: list[str] | None = typer.Option(  # noqa: B008
        None,
        "--preload",
        "-p",
        help="Skills to preload for the session (repeatable).",
    ),
) -> None:
    """Send a chat message with optional slash-command skill routing.

    Examples::

        agent33 chat "/research-agent analyze this codebase"
        agent33 chat "hello" --preload research-agent --preload deploy
    """
    import httpx

    auth_token = token or os.getenv("TOKEN")
    headers: dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    payload: dict[str, object] = {
        "message": message,
    }
    if preload:
        payload["preloaded_skills"] = preload

    try:
        with httpx.Client(base_url=base_url, timeout=120.0) as client:
            resp = client.post(
                "/v1/chat",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            typer.echo(json.dumps(resp.json(), indent=2))
    except httpx.HTTPStatusError as exc:
        typer.echo(f"API error {exc.response.status_code}: {exc.response.text}", err=True)
        raise typer.Exit(code=1) from exc
    except httpx.ConnectError as exc:
        typer.echo(f"Cannot connect to {base_url}: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def status(
    base_url: str = typer.Option(
        "http://localhost:8000",
        "--base-url",
        "-b",
        help="API base URL.",
    ),
) -> None:
    """Show system status by calling the /health endpoint."""
    import httpx

    try:
        with httpx.Client(base_url=base_url, timeout=10.0) as client:
            resp = client.get("/health")
            resp.raise_for_status()
            data = resp.json()
            typer.echo(json.dumps(data, indent=2))
    except httpx.HTTPStatusError as exc:
        msg = f"Health check failed ({exc.response.status_code}): {exc.response.text}"
        typer.echo(msg, err=True)
        raise typer.Exit(code=1) from exc
    except httpx.ConnectError as exc:
        typer.echo(f"Cannot connect to {base_url}: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def diagnose(
    fix: bool = typer.Option(False, "--fix", help="Auto-remediate safe issues."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    plain_output: bool = typer.Option(False, "--plain", help="Emit compact plain-text output."),
    api_url: str = typer.Option(
        "http://localhost:8000",
        "--api-url",
        envvar="AGENT33_API_URL",
        help="API base URL for live pack health checks.",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        "-t",
        envvar="TOKEN",
        help="Bearer token for pack health API checks. Falls back to TOKEN env var.",
    ),
) -> None:
    """Run diagnostic checks on all AGENT-33 subsystems.

    Checks Python version, environment config, disk space, port availability,
    Ollama, LLM provider, database, and Redis connectivity.

    Use --fix to auto-remediate issues where safe to do so.
    """
    from agent33.cli.diagnose import diagnose as _run_diagnose

    output_mode = resolve_output_mode(json_output=json_output, plain_output=plain_output)
    exit_code = _run_diagnose(
        fix=fix,
        output_mode=output_mode,
        api_url=api_url,
        token=token,
    )
    raise typer.Exit(code=exit_code)


@app.command()
def bootstrap(
    output: Path = typer.Option(  # noqa: B008
        Path(".env.local"),  # noqa: B008
        "--output",
        "-o",
        help="Output file path.",
    ),
    force: bool = typer.Option(  # noqa: B008
        False,
        "--force",
        "-f",
        help="Overwrite existing file.",
    ),
) -> None:
    """Generate a .env.local file with secure defaults for local development.

    Generates a cryptographically random JWT_SECRET and dev API key.
    The output file is safe for local dev/lite mode — do NOT use in production.
    """
    _bootstrap_generate(output=output, force=force)


@app.command()
def start(
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-P",
        help=(
            "Configuration profile to activate. "
            "One of: minimal, developer, production, enterprise, airgapped. "
            "Sets AGENT33_PROFILE before loading settings; env vars still override."
        ),
    ),
    host: str = typer.Option("0.0.0.0", "--host", help="Host to bind to."),  # noqa: S104
    port: int = typer.Option(8000, "--port", help="Port to listen on."),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload (development only)."),
) -> None:
    """Start the AGENT-33 server.

    Examples::

        agent33 start --profile developer
        agent33 start --profile production --port 9000
    """
    import subprocess

    if profile:
        import os

        from agent33.config_profiles import PROFILES

        if profile not in PROFILES:
            from agent33.config_profiles import PROFILE_NAMES

            typer.echo(
                f"Unknown profile: {profile!r}. Valid profiles: {', '.join(PROFILE_NAMES)}",
                err=True,
            )
            raise typer.Exit(code=1)
        os.environ["AGENT33_PROFILE"] = profile
        typer.echo(f"Using profile: {profile}")

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "agent33.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if reload:
        cmd.append("--reload")

    result = subprocess.run(cmd, check=False)
    raise typer.Exit(code=result.returncode)


@app.command()
def wizard(
    env_path: Path = typer.Option(  # noqa: B008
        Path(".env.local"),  # noqa: B008
        "--env",
        "-e",
        help="Path where the wizard writes generated .env variables.",
    ),
) -> None:
    """Interactive first-run setup wizard.

    Guides you through environment detection, LLM provider selection,
    a test invocation, and template selection in about 5 minutes.

    Examples::

        agent33 wizard
        agent33 wizard --env /path/to/.env.local
    """
    from agent33.cli.wizard import FirstRunWizard, TerminalWizardIO

    result = FirstRunWizard(io=TerminalWizardIO(), env_path=env_path).run()
    raise typer.Exit(code=0 if result.completed else 1)


if __name__ == "__main__":
    app()
