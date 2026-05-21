"""CLI commands for improvement pack management.

Provides pack management subcommands:
- ``agent33 packs validate`` -- local PACK.yaml validation
- ``agent33 packs apply`` -- apply a pack via the API
- ``agent33 packs list`` -- list installed packs
- ``agent33 packs search`` -- search the community registry (P-PACK v2)
- ``agent33 packs install`` -- install from the registry (P-PACK v2)
- ``agent33 packs update`` -- check for and apply updates (P-PACK v2)
- ``agent33 packs publish`` -- validate and print publish instructions (P-PACK v2)
"""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003 -- typer needs Path at runtime
from typing import Any

import typer

from agent33.cli.output import (
    OutputMode,
    emit_json,
    emit_plain_mapping,
    emit_plain_rows,
    resolve_output_mode,
)

packs_app = typer.Typer(name="packs", help="Improvement pack management.")


def _load_pack_yaml(path: Path) -> dict[str, Any]:
    """Read and parse a PACK.yaml file, returning the raw dict."""
    import yaml

    content = path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    if not isinstance(data, dict):
        raise typer.BadParameter(f"PACK.yaml must be a YAML mapping, got {type(data).__name__}")
    return data


def _emit_list_output(
    payload: dict[str, Any],
    rows: list[tuple[Any, ...]],
    mode: OutputMode,
) -> bool:
    """Emit shared row-oriented output for list/search/update style commands."""
    if mode == OutputMode.JSON:
        emit_json(payload)
        return True
    if mode == OutputMode.PLAIN:
        if rows:
            emit_plain_rows(rows)
        else:
            emit_plain_mapping({"count": payload.get("count", 0)})
        return True
    return False


@packs_app.command("validate")
def validate_pack(
    path: Path = typer.Argument(  # noqa: B008
        ..., help="Path to pack directory or PACK.yaml file."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    plain_output: bool = typer.Option(False, "--plain", help="Emit compact plain-text output."),
) -> None:
    """Validate an improvement pack without applying it (local dry run).

    Reads the PACK.yaml, checks schema, and runs prompt-injection scanning
    on any ``prompt_addenda`` sections.
    """
    pack_yaml = path / "PACK.yaml" if path.is_dir() else path
    if not pack_yaml.exists():
        # Try lowercase fallback
        if path.is_dir():
            pack_yaml = path / "pack.yaml"
        if not pack_yaml.exists():
            typer.echo(f"Error: {pack_yaml} not found", err=True)
            raise typer.Exit(1)

    try:
        data = _load_pack_yaml(pack_yaml)
    except Exception as exc:
        typer.echo(f"Error parsing PACK.yaml: {exc}", err=True)
        raise typer.Exit(1) from exc

    mode = resolve_output_mode(json_output=json_output, plain_output=plain_output)
    name = data.get("name", "?")
    version = data.get("version", "?")
    description = data.get("description", "")

    prompt_addenda: list[str] = data.get("prompt_addenda", [])
    tool_config: dict[str, Any] = data.get("tool_config", {})
    skills: list[Any] = data.get("skills", [])

    # Run injection scanning on prompt_addenda
    from agent33.security.injection import scan_inputs_recursive

    scan_result = scan_inputs_recursive(prompt_addenda)
    if not scan_result.is_safe:
        typer.echo(
            f"\nWARNING: prompt_addenda failed injection scan: {', '.join(scan_result.threats)}",
            err=True,
        )
        typer.echo("Review and sanitize the addenda before applying.", err=True)
        raise typer.Exit(1)

    # Try full Pydantic validation
    try:
        from agent33.packs.manifest import PackManifest

        PackManifest.model_validate(data)
    except Exception as exc:
        typer.echo(f"\nSchema validation failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    payload = {
        "pack": {
            "name": name,
            "version": version,
            "description": description,
        },
        "prompt_addenda_count": len(prompt_addenda),
        "tool_config_keys": list(tool_config.keys()),
        "skills_count": len(skills),
        "validation": "passed",
    }

    if mode == OutputMode.JSON:
        emit_json(payload)
        return
    if mode == OutputMode.PLAIN:
        emit_plain_mapping(
            {
                "name": name,
                "version": version,
                "validation": "passed",
                "prompt_addenda_count": len(prompt_addenda),
                "tool_config_count": len(tool_config),
                "skills_count": len(skills),
            }
        )
        return

    typer.echo(f"Pack: {name} v{version}")
    typer.echo(f"Description: {description}")
    typer.echo("\nWould apply:")
    typer.echo(f"  {len(prompt_addenda)} prompt addenda section(s)")
    typer.echo(f"  {len(tool_config)} tool config override(s): {list(tool_config.keys())}")
    typer.echo(f"  {len(skills)} skill(s) to register")
    typer.echo("\nValidation passed. Use 'agent33 packs apply' to apply.")


@packs_app.command("apply")
def apply_pack(
    name: str = typer.Argument(..., help="Pack name to apply."),
    session: str = typer.Option(
        "", "--session", help="Session ID for session-scoped application."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without applying."),
    api_url: str = typer.Option(
        "http://localhost:8000", envvar="AGENT33_API_URL", help="API base URL."
    ),
    token: str = typer.Option("", envvar="TOKEN", help="Bearer token for authentication."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    plain_output: bool = typer.Option(False, "--plain", help="Emit compact plain-text output."),
) -> None:
    """Apply or preview an improvement pack via the server API."""
    import httpx

    mode = resolve_output_mode(json_output=json_output, plain_output=plain_output)
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        if dry_run:
            params: dict[str, str] = {}
            if session:
                params["session"] = session
            resp = httpx.get(
                f"{api_url}/v1/packs/{name}/dry-run",
                headers=headers,
                params=params,
                timeout=10,
            )
        elif session:
            resp = httpx.post(
                f"{api_url}/v1/packs/{name}/enable-session",
                headers=headers,
                params={"session_id": session},
                timeout=10,
            )
        else:
            resp = httpx.post(
                f"{api_url}/v1/packs/{name}/enable",
                headers=headers,
                timeout=10,
            )
        resp.raise_for_status()
        data = resp.json()
        if mode == OutputMode.JSON:
            emit_json(data)
            return
        if mode == OutputMode.PLAIN:
            emit_plain_mapping(data)
            return
        if dry_run:
            typer.echo(f"Dry run for pack '{name}':")
            typer.echo(json.dumps(data, indent=2))
        else:
            scope = f" for session '{session}'" if session else ""
            typer.echo(f"Pack '{name}' applied{scope} successfully.")
    except httpx.HTTPStatusError as exc:
        typer.echo(f"Error {exc.response.status_code}: {exc.response.text}", err=True)
        raise typer.Exit(1) from exc
    except httpx.ConnectError as exc:
        typer.echo(f"Cannot connect to {api_url}: {exc}", err=True)
        raise typer.Exit(1) from exc


@packs_app.command("list")
def list_packs(
    api_url: str = typer.Option(
        "http://localhost:8000", envvar="AGENT33_API_URL", help="API base URL."
    ),
    token: str = typer.Option("", envvar="TOKEN", help="Bearer token for authentication."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    plain_output: bool = typer.Option(False, "--plain", help="Emit compact plain-text output."),
) -> None:
    """List all installed improvement packs via the server API."""
    import httpx

    mode = resolve_output_mode(json_output=json_output, plain_output=plain_output)
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = httpx.get(f"{api_url}/v1/packs", headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        packs_list: list[dict[str, Any]] = data.get("packs", [])
        rows = [
            (pack.get("name", "?"), pack.get("version", "?"), pack.get("status", "?"))
            for pack in packs_list
        ]
        payload = {"packs": packs_list, "count": len(packs_list)}
        if _emit_list_output(payload, rows, mode):
            return
        if not packs_list:
            typer.echo("No packs installed.")
            return
        typer.echo(f"Installed packs ({len(packs_list)}):")
        for p in packs_list:
            name = p.get("name", "?")
            version = p.get("version", "?")
            status = p.get("status", "?")
            typer.echo(f"  {name} v{version} [{status}]")
    except httpx.HTTPStatusError as exc:
        typer.echo(f"Error {exc.response.status_code}: {exc.response.text}", err=True)
        raise typer.Exit(1) from exc
    except httpx.ConnectError as exc:
        typer.echo(f"Cannot connect to {api_url}: {exc}", err=True)
        raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# P-PACK v2 CLI commands
# ---------------------------------------------------------------------------


@packs_app.command("search")
def search_registry(
    query: str = typer.Argument(..., help="Search query for the pack registry."),
    tags: str = typer.Option("", "--tags", help="Comma-separated tag filter."),
    limit: int = typer.Option(10, "--limit", help="Maximum results."),
    api_url: str = typer.Option(
        "http://localhost:8000", envvar="AGENT33_API_URL", help="API base URL."
    ),
    token: str = typer.Option("", envvar="TOKEN", help="Bearer token for authentication."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    plain_output: bool = typer.Option(False, "--plain", help="Emit compact plain-text output."),
) -> None:
    """Search the community pack registry."""
    import httpx

    mode = resolve_output_mode(json_output=json_output, plain_output=plain_output)
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params: dict[str, str] = {"q": query}
    if tags:
        params["tags"] = tags
    if limit != 10:
        params["limit"] = str(limit)

    try:
        resp = httpx.get(
            f"{api_url}/v1/packs/hub/search",
            headers=headers,
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        typer.echo(f"Error {exc.response.status_code}: {exc.response.text}", err=True)
        raise typer.Exit(1) from exc
    except httpx.ConnectError as exc:
        typer.echo(f"Cannot connect to {api_url}: {exc}", err=True)
        raise typer.Exit(1) from exc

    results: list[dict[str, Any]] = data.get("results", [])
    rows = [
        (
            entry.get("name", "?"),
            entry.get("version", "?"),
            entry.get("description", ""),
            ",".join(entry.get("tags", [])),
        )
        for entry in results
    ]
    if _emit_list_output(data, rows, mode):
        return
    if not results:
        typer.echo(f"No packs found for '{query}'.")
        return

    typer.echo(f"Registry results ({len(results)}):")
    for entry in results:
        name = entry.get("name", "?")
        version = entry.get("version", "?")
        description = entry.get("description", "")
        entry_tags = entry.get("tags", [])
        tag_str = f"  [{', '.join(entry_tags)}]" if entry_tags else ""
        typer.echo(f"  {name} v{version} -- {description}{tag_str}")


@packs_app.command("install")
def install_from_registry(
    name: str = typer.Argument(..., help="Pack name to install from the registry."),
    api_url: str = typer.Option(
        "http://localhost:8000", envvar="AGENT33_API_URL", help="API base URL."
    ),
    token: str = typer.Option("", envvar="TOKEN", help="Bearer token for authentication."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    plain_output: bool = typer.Option(False, "--plain", help="Emit compact plain-text output."),
) -> None:
    """Download a pack from the community registry and install it locally."""
    import httpx

    mode = resolve_output_mode(json_output=json_output, plain_output=plain_output)
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Step 1: Look up the pack in the hub
    try:
        resp = httpx.get(
            f"{api_url}/v1/packs/hub/entry/{name}",
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        entry_data = resp.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            typer.echo(f"Pack '{name}' not found in the registry.", err=True)
        else:
            typer.echo(f"Error {exc.response.status_code}: {exc.response.text}", err=True)
        raise typer.Exit(1) from exc
    except httpx.ConnectError as exc:
        typer.echo(f"Cannot connect to {api_url}: {exc}", err=True)
        raise typer.Exit(1) from exc

    entry = entry_data.get("entry")
    if entry is None:
        typer.echo(f"Pack '{name}' not found in the registry.", err=True)
        raise typer.Exit(1)

    version = entry.get("version", "?")
    if mode == OutputMode.HUMAN:
        typer.echo(f"Found: {name} v{version}")
        typer.echo(f"Description: {entry.get('description', '')}")
        typer.echo(f"Author: {entry.get('author', '')}")

    # Step 2: Install via the install endpoint (the server handles download)
    try:
        resp = httpx.post(
            f"{api_url}/v1/packs/install",
            headers=headers,
            json={
                "source_type": "local",
                "name": name,
                "version": version,
            },
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        if mode == OutputMode.JSON:
            emit_json({"entry": entry, "result": result})
            return
        if mode == OutputMode.PLAIN:
            emit_plain_mapping(
                {
                    "name": result.get("pack_name", name),
                    "version": result.get("version", version),
                    "skills_loaded": result.get("skills_loaded", 0),
                    "status": "installed",
                }
            )
            return
        typer.echo(
            f"Installed: {result.get('pack_name', name)} v{result.get('version', version)} "
            f"({result.get('skills_loaded', 0)} skills loaded)"
        )
    except httpx.HTTPStatusError as exc:
        typer.echo(f"Install failed: {exc.response.text}", err=True)
        raise typer.Exit(1) from exc
    except httpx.ConnectError as exc:
        typer.echo(f"Cannot connect to {api_url}: {exc}", err=True)
        raise typer.Exit(1) from exc


@packs_app.command("update")
def update_packs(
    name: str = typer.Argument(default="", help="Pack name to update (empty = check all)."),
    check_only: bool = typer.Option(False, "--check", help="Only check for updates, don't apply."),
    api_url: str = typer.Option(
        "http://localhost:8000", envvar="AGENT33_API_URL", help="API base URL."
    ),
    token: str = typer.Option("", envvar="TOKEN", help="Bearer token for authentication."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    plain_output: bool = typer.Option(False, "--plain", help="Emit compact plain-text output."),
) -> None:
    """Check for and apply pack updates from the registry."""
    import httpx

    mode = resolve_output_mode(json_output=json_output, plain_output=plain_output)
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # List installed packs
    try:
        resp = httpx.get(f"{api_url}/v1/packs", headers=headers, timeout=10)
        resp.raise_for_status()
        installed = resp.json().get("packs", [])
    except httpx.HTTPStatusError as exc:
        typer.echo(f"Error {exc.response.status_code}: {exc.response.text}", err=True)
        raise typer.Exit(1) from exc
    except httpx.ConnectError as exc:
        typer.echo(f"Cannot connect to {api_url}: {exc}", err=True)
        raise typer.Exit(1) from exc

    if name:
        installed = [p for p in installed if p.get("name") == name]
        if not installed:
            typer.echo(f"Pack '{name}' is not installed.", err=True)
            raise typer.Exit(1)

    # Check each pack against the registry
    updates_found = 0
    updates: list[dict[str, str]] = []
    for pack_info in installed:
        pack_name = pack_info.get("name", "?")
        installed_version = pack_info.get("version", "?")

        try:
            resp = httpx.get(
                f"{api_url}/v1/packs/hub/entry/{pack_name}",
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            entry = resp.json().get("entry")
            if entry is None:
                continue
        except Exception:
            continue

        hub_version = entry.get("version", "")
        if hub_version and hub_version != installed_version:
            updates.append(
                {
                    "name": pack_name,
                    "installed_version": installed_version,
                    "latest_version": hub_version,
                }
            )
            if mode == OutputMode.HUMAN:
                typer.echo(
                    f"  {pack_name}: {installed_version} -> {hub_version} (update available)"
                )
            updates_found += 1

    payload = {"updates": updates, "count": updates_found, "check_only": check_only}
    rows = [(item["name"], item["installed_version"], item["latest_version"]) for item in updates]
    if _emit_list_output(payload, rows, mode):
        return

    if updates_found == 0:
        typer.echo("All packs are up to date.")
    elif check_only:
        typer.echo(f"\n{updates_found} update(s) available. Run without --check to apply.")
    else:
        typer.echo(f"\n{updates_found} update(s) found. Use 'agent33 packs update' to apply.")


@packs_app.command("publish")
def publish_pack(
    path: Path = typer.Argument(  # noqa: B008
        ..., help="Path to pack directory or PACK.yaml file."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    plain_output: bool = typer.Option(False, "--plain", help="Emit compact plain-text output."),
) -> None:
    """Validate a pack and print instructions for submitting to the registry.

    In v1 this cannot actually publish -- it validates the pack locally and
    prints a GitHub PR URL template for manual submission.
    """
    pack_yaml = path / "PACK.yaml" if path.is_dir() else path
    if not pack_yaml.exists():
        if path.is_dir():
            pack_yaml = path / "pack.yaml"
        if not pack_yaml.exists():
            typer.echo(f"Error: {pack_yaml} not found", err=True)
            raise typer.Exit(1)

    try:
        data = _load_pack_yaml(pack_yaml)
    except Exception as exc:
        typer.echo(f"Error parsing PACK.yaml: {exc}", err=True)
        raise typer.Exit(1) from exc

    mode = resolve_output_mode(json_output=json_output, plain_output=plain_output)
    pack_name = data.get("name", "?")
    version = data.get("version", "?")
    description = data.get("description", "")
    registry_entry = {
        "name": pack_name,
        "version": version,
        "description": description,
        "author": data.get("author", ""),
        "tags": data.get("tags", []),
        "download_url": "<your-pack-yaml-raw-url>",
        "sha256": "<sha256-of-pack-yaml>",
    }
    payload = {
        "pack": {"name": pack_name, "version": version, "description": description},
        "registry_compare_url": "https://github.com/mattmre/agent33-pack-registry/compare/main...your-branch",
        "registry_entry_template": registry_entry,
    }

    # Run full validation
    try:
        from agent33.packs.manifest import PackManifest

        PackManifest.model_validate(data)
    except Exception as exc:
        typer.echo(f"Validation failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    if mode == OutputMode.JSON:
        emit_json(payload)
        return
    if mode == OutputMode.PLAIN:
        emit_plain_mapping(
            {
                "name": pack_name,
                "version": version,
                "validated": True,
                "registry_compare_url": payload["registry_compare_url"],
            }
        )
        return

    typer.echo(f"Pack '{pack_name}' v{version} validated successfully.")
    typer.echo(f"Description: {description}")
    typer.echo("")
    typer.echo("To publish, submit a PR to the pack registry:")
    typer.echo("  https://github.com/mattmre/agent33-pack-registry/compare/main...your-branch")
    typer.echo("")
    typer.echo("Your PR should add an entry to registry.json with:")
    typer.echo(json.dumps(registry_entry, indent=2))


@packs_app.command("revocation-status")
def revocation_status(
    name: str = typer.Argument(..., help="Pack name to check for revocation."),
    version: str = typer.Option("", "--version", help="Pack version to check (empty = any)."),
    api_url: str = typer.Option(
        "http://localhost:8000", envvar="AGENT33_API_URL", help="API base URL."
    ),
    token: str = typer.Option("", envvar="TOKEN", help="Bearer token for authentication."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    plain_output: bool = typer.Option(False, "--plain", help="Emit compact plain-text output."),
) -> None:
    """Check whether a pack is revoked in the community registry.

    Exits with code 1 if the pack is revoked so this can be used in scripts
    and CI pipelines as a pre-install gate.
    """
    import httpx

    mode = resolve_output_mode(json_output=json_output, plain_output=plain_output)
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params: dict[str, str] = {}
    if version:
        params["version"] = version

    try:
        resp = httpx.get(
            f"{api_url}/v1/packs/hub/revocation/{name}",
            headers=headers,
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        status = resp.json()
    except httpx.HTTPStatusError as exc:
        typer.echo(f"Error {exc.response.status_code}: {exc.response.text}", err=True)
        raise typer.Exit(1) from exc
    except httpx.ConnectError as exc:
        typer.echo(f"Cannot connect to {api_url}: {exc}", err=True)
        raise typer.Exit(1) from exc

    if status.get("revoked"):
        reason = status.get("reason", "no reason provided")
        if mode == OutputMode.JSON:
            emit_json(status)
        elif mode == OutputMode.PLAIN:
            emit_plain_mapping(status)
        else:
            typer.echo(f"REVOKED: {name} -- {reason}", err=True)
        raise typer.Exit(1)

    if mode == OutputMode.JSON:
        emit_json(status)
    elif mode == OutputMode.PLAIN:
        emit_plain_mapping(status)
    else:
        typer.echo(f"OK: {name} is not revoked.")
