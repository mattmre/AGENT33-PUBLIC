"""CLI commands for skill discovery and management (P69a)."""

from __future__ import annotations

from typing import Any

import httpx
import typer

skills_app = typer.Typer(name="skills", help="Skill discovery commands.")


@skills_app.command("search")
def search_skills(
    query: str = typer.Argument(..., help="Search query for skills."),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results to show."),
    api_url: str = typer.Option("http://localhost:8000", "--api-url", envvar="AGENT33_API_URL"),
    token: str = typer.Option("", "--token", envvar="TOKEN"),
) -> None:
    """Search for available skills by capability description."""
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = httpx.get(
            f"{api_url}/v1/discovery/skills",
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
        typer.echo("No matching skills found.")
        return

    for i, item in enumerate(matches, 1):
        name: str = item.get("name", "?")
        desc: str = item.get("description", "")[:100]
        score: float = item.get("score", 0.0)
        typer.echo(f"{i}. {name} (score: {score:.2f})")
        if desc:
            typer.echo(f"   {desc}")


@skills_app.command("list")
def list_skills(
    limit: int = typer.Option(20, "--limit", "-n", help="Max skills to display."),
    api_url: str = typer.Option("http://localhost:8000", "--api-url", envvar="AGENT33_API_URL"),
    token: str = typer.Option("", "--token", envvar="TOKEN"),
) -> None:
    """List available skills from the running server via the discovery endpoint.

    Uses a broad wildcard query against ``/v1/discovery/skills`` with a high
    limit to enumerate the skills visible to the current tenant.
    """
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Use the discovery endpoint with a broad single-character query.
    # The scoring function awards partial matches, so "a" will surface
    # most skills; we request a large window and display up to *limit*.
    fetch_limit = max(limit, 50)
    try:
        resp = httpx.get(
            f"{api_url}/v1/discovery/skills",
            params={"q": "agent", "limit": fetch_limit},
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
        typer.echo("No skills found on the server.")
        return

    display = matches[:limit]
    typer.echo(f"Available skills ({len(matches)} found, showing {len(display)}):")
    for item in display:
        name: str = item.get("name", "?")
        desc: str = item.get("description", "")[:80]
        suffix = f" -- {desc}" if desc else ""
        typer.echo(f"  - {name}{suffix}")
    if len(matches) > limit:
        typer.echo(f"  ... and {len(matches) - limit} more (use --limit to see more)")
