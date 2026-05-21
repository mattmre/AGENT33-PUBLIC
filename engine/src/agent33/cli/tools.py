"""CLI commands for tool discovery and approval (P69a)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import typer

tools_app = typer.Typer(name="tools", help="Tool discovery and approval commands.")

APPROVED_TOOLS_PATH = Path.home() / ".agent33" / "approved-tools.json"


def _load_approved() -> dict[str, dict[str, Any]]:
    """Load approved tools from ~/.agent33/approved-tools.json."""
    if not APPROVED_TOOLS_PATH.exists():
        return {}
    try:
        return json.loads(APPROVED_TOOLS_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return {}


def _save_approved(data: dict[str, dict[str, Any]]) -> None:
    """Save approved tools to ~/.agent33/approved-tools.json."""
    APPROVED_TOOLS_PATH.parent.mkdir(parents=True, exist_ok=True)
    APPROVED_TOOLS_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


@tools_app.command("search")
def search_tools(
    query: str = typer.Argument(..., help="Search query for tools."),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results to show."),
    api_url: str = typer.Option("http://localhost:8000", "--api-url", envvar="AGENT33_API_URL"),
    token: str = typer.Option("", "--token", envvar="TOKEN"),
) -> None:
    """Search for available tools by capability description."""
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = httpx.get(
            f"{api_url}/v1/discovery/tools",
            params={"q": query, "limit": limit},
            headers=headers,
            timeout=10.0,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    payload = resp.json()
    matches: list[dict[str, Any]] = payload.get("matches", [])
    if not matches:
        typer.echo("No matching tools found.")
        return

    approved = _load_approved()
    for i, item in enumerate(matches, 1):
        name: str = item.get("name", "?")
        desc: str = item.get("description", "")
        score: float = item.get("score", 0.0)
        mark = "[v]" if name in approved else "[ ]"
        typer.echo(f"{mark} {i}. {name} (score: {score:.2f})")
        if desc:
            typer.echo(f"    {desc[:100]}")


@tools_app.command("approve")
def approve_tool(
    name: str = typer.Argument(..., help="Tool name to approve."),
    reason: str = typer.Option("", "--reason", help="Reason for approval (optional)."),
) -> None:
    """Permanently approve a tool for use by agents."""
    approved = _load_approved()
    if name in approved:
        typer.echo(f"Tool '{name}' is already approved.")
        return
    approved[name] = {
        "approved_at": datetime.now(tz=UTC).isoformat(),
        "reason": reason,
    }
    _save_approved(approved)
    typer.echo(f"Tool '{name}' approved. It will be available in future agent sessions.")


@tools_app.command("revoke")
def revoke_tool(
    name: str = typer.Argument(..., help="Tool name to revoke."),
) -> None:
    """Revoke approval for a tool."""
    approved = _load_approved()
    if name not in approved:
        typer.echo(f"Tool '{name}' is not approved.")
        return
    del approved[name]
    _save_approved(approved)
    typer.echo(f"Tool '{name}' approval revoked.")


@tools_app.command("list")
def list_approved() -> None:
    """List all currently approved tools."""
    approved = _load_approved()
    if not approved:
        typer.echo("No tools approved yet. Use 'agent33 tools approve <name>' to approve tools.")
        return
    typer.echo(f"Approved tools ({len(approved)}):")
    for name, meta in approved.items():
        at: str = meta.get("approved_at", "?")[:10]
        reason_text = f" -- {meta['reason']}" if meta.get("reason") else ""
        typer.echo(f"  [v] {name} (approved {at}){reason_text}")
