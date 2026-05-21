"""CA-025: IO Manager Abstraction for workflow step inputs/outputs."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class IOContext:
    """Context passed to IO manager operations."""

    step_id: str
    run_id: str = ""
    key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class IOManager(ABC):
    """Abstract base for loading inputs and handling outputs of workflow steps."""

    @abstractmethod
    def load_input(self, context: IOContext) -> Any:
        """Load input data for a workflow step."""

    @abstractmethod
    def handle_output(self, context: IOContext, result: Any) -> None:
        """Persist or forward the output of a workflow step."""


class MemoryIOManager(IOManager):
    """In-memory IO manager -- useful for testing and ephemeral runs."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def load_input(self, context: IOContext) -> Any:
        key = f"{context.run_id}/{context.step_id}/{context.key}"
        return self._store.get(key)

    def handle_output(self, context: IOContext, result: Any) -> None:
        key = f"{context.run_id}/{context.step_id}/{context.key}"
        self._store[key] = result

    @property
    def store(self) -> dict[str, Any]:
        """Expose internal store for inspection."""
        return dict(self._store)


class FileIOManager(IOManager):
    """File-system IO manager -- reads and writes JSON files."""

    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _path_for(self, context: IOContext) -> Path:
        base_resolved = self._base.resolve()
        target_path = (
            base_resolved / context.run_id / f"{context.step_id}_{context.key}.json"
        ).resolve()
        try:
            target_path.relative_to(base_resolved)
        except ValueError:
            raise ValueError("Access denied: Path is outside the base directory") from None
        return target_path

    def load_input(self, context: IOContext) -> Any:
        p = self._path_for(context)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def handle_output(self, context: IOContext, result: Any) -> None:
        p = self._path_for(context)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result, default=str), encoding="utf-8")


class DatabaseIOManager(IOManager):
    """Database IO manager -- stores data in a dict simulating a DB table.

    In production this would be backed by SQLAlchemy or similar.
    """

    def __init__(self) -> None:
        self._table: dict[str, Any] = {}

    def load_input(self, context: IOContext) -> Any:
        key = f"{context.run_id}/{context.step_id}/{context.key}"
        return self._table.get(key)

    def handle_output(self, context: IOContext, result: Any) -> None:
        key = f"{context.run_id}/{context.step_id}/{context.key}"
        self._table[key] = result

    @property
    def table(self) -> dict[str, Any]:
        """Expose internal table for inspection."""
        return dict(self._table)
