"""Rollback support for installed packs."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ArchivedPackRevision(BaseModel):
    """Archived pack revision available for rollback."""

    pack_name: str
    version: str
    archive_path: str
    archived_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PackRollbackManager:
    """Archive and restore installed pack revisions."""

    def __init__(
        self,
        pack_registry: Any,
        *,
        archive_dir: Path,
        state_store: Any | None = None,
        namespace: str = "pack_rollback_history",
    ) -> None:
        self._pack_registry = pack_registry
        self._archive_dir = archive_dir
        self._state_store = state_store
        self._namespace = namespace
        self._history: dict[str, list[ArchivedPackRevision]] = {}
        self._load()

    def archive_current(self, pack_name: str) -> ArchivedPackRevision:
        pack = self._pack_registry.get(pack_name)
        if pack is None:
            raise ValueError(f"Pack '{pack_name}' is not installed")

        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        destination = self._archive_dir / pack_name / f"{pack.version}-{timestamp}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(pack.pack_dir, destination)

        revision = ArchivedPackRevision(
            pack_name=pack_name,
            version=pack.version,
            archive_path=str(destination),
        )
        self._history.setdefault(pack_name, []).append(revision)
        self._persist()
        return revision

    def list_archived_versions(self, pack_name: str) -> list[ArchivedPackRevision]:
        return list(reversed(self._history.get(pack_name, [])))

    def rollback(self, pack_name: str, *, version: str = "") -> tuple[Any, ArchivedPackRevision]:
        pack = self._pack_registry.get(pack_name)
        if pack is None:
            raise ValueError(f"Pack '{pack_name}' is not installed")

        current_version = pack.version
        candidates = self.list_archived_versions(pack_name)
        target = next(
            (
                revision
                for revision in candidates
                if revision.version != current_version
                and (not version or revision.version == version)
            ),
            None,
        )
        if target is None:
            raise ValueError(
                f"No archived rollback revision available for pack '{pack_name}'"
                + (f" at version '{version}'" if version else "")
            )

        self.archive_current(pack_name)
        result = self._pack_registry.upgrade(pack_name, Path(target.archive_path), target.version)
        return result, target

    def _load(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace(self._namespace)
        raw_history = payload.get("history", {})
        if not isinstance(raw_history, dict):
            return
        self._history = {}
        for pack_name, entries in raw_history.items():
            if not isinstance(pack_name, str) or not isinstance(entries, list):
                continue
            parsed: list[ArchivedPackRevision] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                try:
                    parsed.append(ArchivedPackRevision.model_validate(entry))
                except Exception:
                    continue
            self._history[pack_name] = parsed

    def _persist(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            self._namespace,
            {
                "history": {
                    pack_name: [entry.model_dump(mode="json") for entry in entries]
                    for pack_name, entries in self._history.items()
                }
            },
        )
