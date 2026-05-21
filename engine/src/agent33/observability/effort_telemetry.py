"""Effort-routing telemetry exporters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


class EffortTelemetryExportError(RuntimeError):
    """Raised when effort telemetry export fails."""


class EffortTelemetryExporter(Protocol):
    """Exporter interface for effort-routing telemetry events."""

    def export(self, event: dict[str, Any]) -> None:
        """Export a single effort-routing event."""


class NoopEffortTelemetryExporter:
    """Exporter implementation that drops all events."""

    def export(self, event: dict[str, Any]) -> None:
        _ = event


class FileEffortTelemetryExporter:
    """Append effort-routing events to a JSONL file."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def export(self, event: dict[str, Any]) -> None:
        try:
            payload = json.dumps(event, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise EffortTelemetryExportError("Failed to serialize effort telemetry event") from exc

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(payload)
                handle.write("\n")
        except OSError as exc:
            raise EffortTelemetryExportError("Failed to write effort telemetry event") from exc
