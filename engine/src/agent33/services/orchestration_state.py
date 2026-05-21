"""Shared durable state store for orchestration services."""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any, cast


def _deep_copy(value: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-compatible deep copy of *value*."""
    return cast("dict[str, Any]", json.loads(json.dumps(value)))


class OrchestrationStateStore:
    """JSON file-backed key/value store for service namespace snapshots."""

    def __init__(self, path: str, *, on_corruption: str = "reset") -> None:
        self._path = Path(path)
        self._on_corruption = on_corruption.strip().lower()
        self._lock = RLock()
        self._state: dict[str, dict[str, Any]] = self._load()

    def read_namespace(self, namespace: str) -> dict[str, Any]:
        """Return a deep copy of the namespace payload or an empty dict."""
        with self._lock:
            raw = self._state.get(namespace, {})
            if not isinstance(raw, dict):
                return {}
            return _deep_copy(raw)

    def write_namespace(self, namespace: str, payload: dict[str, Any]) -> None:
        """Persist a namespace payload atomically."""
        with self._lock:
            self._state[namespace] = _deep_copy(payload)
            self._persist()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            raw = self._path.read_text(encoding="utf-8")
            if not raw.strip():
                return {}
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                return self._handle_corruption()
            valid: dict[str, dict[str, Any]] = {}
            for key, value in parsed.items():
                if isinstance(key, str) and isinstance(value, dict):
                    valid[key] = value
            return valid
        except (OSError, json.JSONDecodeError):
            return self._handle_corruption()

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(self._state, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self._path)

    def _handle_corruption(self) -> dict[str, dict[str, Any]]:
        if self._on_corruption == "raise":
            raise ValueError(f"Corrupted orchestration state store: {self._path}")
        if self._path.exists():
            candidate = Path(f"{self._path}.corrupt")
            suffix = 1
            while candidate.exists():
                candidate = Path(f"{self._path}.corrupt.{suffix}")
                suffix += 1
            self._path.replace(candidate)
        return {}
