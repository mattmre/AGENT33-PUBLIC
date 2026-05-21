"""Shared output helpers for CLI commands."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

import typer


class OutputMode(StrEnum):
    """Supported CLI output styles."""

    HUMAN = "human"
    JSON = "json"
    PLAIN = "plain"


def resolve_output_mode(*, json_output: bool = False, plain_output: bool = False) -> OutputMode:
    """Resolve mutually-exclusive CLI output flags."""
    if json_output and plain_output:
        typer.echo("Error: Use only one of --json or --plain.", err=True)
        raise typer.Exit(code=2)
    if json_output:
        return OutputMode.JSON
    if plain_output:
        return OutputMode.PLAIN
    return OutputMode.HUMAN


def emit_json(data: Any) -> None:
    """Render structured CLI output as indented JSON."""
    typer.echo(json.dumps(data, indent=2))


def emit_plain_mapping(data: Mapping[str, Any]) -> None:
    """Render a mapping as key=value lines."""
    for key, value in data.items():
        typer.echo(f"{key}={_plain_value(value)}")


def emit_plain_rows(rows: Iterable[Sequence[Any]]) -> None:
    """Render row-oriented plain output as tab-separated values."""
    for row in rows:
        typer.echo("\t".join(_plain_value(value) for value in row))


def _plain_value(value: Any) -> str:
    """Serialize nested values compactly for plain output."""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, separators=(",", ":"))
    if value is None:
        return ""
    return str(value)
