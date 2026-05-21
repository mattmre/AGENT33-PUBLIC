"""CLI commands for environment detection."""

from __future__ import annotations

import json
import platform as _platform
from dataclasses import asdict
from typing import Annotated

import typer

from agent33.env.detect import ENV_CACHE_PATH, detect_env

app = typer.Typer(
    name="env",
    help="Environment detection and self-adaptation commands.",
    add_completion=False,
)


@app.command("show")
def env_show(
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Force re-detection even if cache is fresh.")
    ] = False,
    json_out: Annotated[
        bool | None, typer.Option("--json-output", help="Output as JSON.")
    ] = False,
) -> None:
    """Show current environment profile and model recommendation."""
    profile = detect_env(force_refresh=refresh)

    if json_out:
        typer.echo(json.dumps(asdict(profile), indent=2))
        return

    hw = profile.hardware
    tools = profile.tools
    model = profile.selected_model

    typer.echo("\n=== AGENT-33 Environment Profile ===\n")
    typer.echo(f"OS:          {hw.os_type} {hw.os_version[:40]}")
    typer.echo(f"CPU:         {hw.cpu_brand} ({hw.cpu_cores} cores)")
    typer.echo(f"RAM:         {hw.ram_gb:.1f} GB")
    if hw.gpu_vram_gb > 0:
        typer.echo(f"GPU:         {hw.gpu_brand} ({hw.gpu_vram_gb:.1f} GB VRAM)")
    else:
        typer.echo("GPU:         None detected")
    typer.echo(f"Disk free:   {hw.disk_free_gb:.1f} GB")
    typer.echo("")
    typer.echo("Tools:")
    typer.echo(f"  Python:    {tools.python_version} ({tools.python_path})")

    def _tf(v: bool) -> str:
        if v:
            return typer.style("yes", fg=typer.colors.GREEN)
        return typer.style("no", fg=typer.colors.RED)

    typer.echo(f"  Docker:    {_tf(tools.docker_available)}")
    typer.echo(f"  Git:       {_tf(tools.git_available)}")
    typer.echo(f"  Ollama:    {_tf(tools.ollama_available)}")
    typer.echo(f"  Node:      {_tf(tools.node_available)}")
    typer.echo(f"  curl:      {_tf(tools.curl_available)}")
    typer.echo("")
    typer.echo("Recommended LLM:")
    if model.fallback_to_api:
        typer.echo("  No local inference hardware detected.")
        typer.echo("  Use an API key (OpenAI / Anthropic) or install Ollama + a quantized model.")
    else:
        typer.echo(f"  Model:     {model.ollama_model}")
        typer.echo(f"  Size:      {model.size_gb:.1f} GB")
        typer.echo(f"  Reason:    {model.reason}")
        if not tools.ollama_available:
            typer.echo("")
            system = _platform.system()
            if system == "Darwin":
                typer.echo("  Ollama not found. Install: brew install ollama")
                typer.echo("  Or: https://ollama.ai/download")
            elif system == "Linux":
                typer.echo(
                    "  Ollama not found. Install: curl -fsSL https://ollama.ai/install.sh | sh"
                )
            else:
                typer.echo("  Ollama not found. Download: https://ollama.ai/download")
    typer.echo(f"\nMode:        {profile.mode}")
    typer.echo(f"LLM source:  {profile.llm_source}")
    cache_note = f" (cached at {ENV_CACHE_PATH})" if not refresh else " (freshly detected)"
    typer.echo(f"Detected at: {profile.detected_at[:19]}{cache_note}\n")
