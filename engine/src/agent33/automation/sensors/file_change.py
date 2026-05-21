"""File-change sensor using polling (os.stat mtime checks)."""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import logging
import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class ChangeType(StrEnum):
    """Type of file system change detected."""

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class FileChangeEvent:
    """A detected file system change."""

    path: str
    change_type: ChangeType


@dataclass
class _WatchEntry:
    """Internal state for a single watch configuration."""

    path: str
    patterns: list[str]
    callback: Callable[[list[FileChangeEvent]], Awaitable[Any]]
    snapshot: dict[str, float] = field(default_factory=dict)


class FileChangeSensor:
    """Polls directories for file changes at a configurable interval.

    Detects new, modified, and deleted files matching glob patterns.
    """

    def __init__(self, poll_interval_seconds: float = 5.0) -> None:
        self._poll_interval = poll_interval_seconds
        self._watches: list[_WatchEntry] = []
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def watch(
        self,
        path: str | Path,
        patterns: list[str],
        callback: Callable[[list[FileChangeEvent]], Awaitable[Any]],
    ) -> None:
        """Register a directory to watch for file changes.

        Parameters
        ----------
        path:
            Directory path to monitor.
        patterns:
            List of glob patterns to match (e.g. ``["*.py", "*.json"]``).
        callback:
            Async callable invoked with a list of change events when
            changes are detected.
        """
        resolved = str(Path(path).resolve())
        entry = _WatchEntry(path=resolved, patterns=patterns, callback=callback)
        # Take initial snapshot so first poll only reports new changes.
        entry.snapshot = self._scan(resolved, patterns)
        self._watches.append(entry)
        logger.info("Watching %s for patterns %s", resolved, patterns)

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        """Start the background polling loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._poll_loop())
        logger.info("FileChangeSensor started (interval=%.1fs)", self._poll_interval)

    def stop(self) -> None:
        """Stop the background polling loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None
        logger.info("FileChangeSensor stopped")

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _scan(directory: str, patterns: list[str]) -> dict[str, float]:
        """Return ``{filepath: mtime}`` for all files matching patterns."""
        result: dict[str, float] = {}
        try:
            entries = os.scandir(directory)
        except OSError:
            return result

        for entry in entries:
            if not entry.is_file():
                continue
            if any(fnmatch.fnmatch(entry.name, p) for p in patterns):
                with contextlib.suppress(OSError):
                    result[entry.path] = entry.stat().st_mtime
        return result

    async def _poll_loop(self) -> None:
        """Continuously poll watched directories."""
        while self._running:
            for watch in self._watches:
                events = self._diff(watch)
                if events:
                    try:
                        await watch.callback(events)
                    except Exception:
                        logger.exception("Error in file-change callback for %s", watch.path)
            await asyncio.sleep(self._poll_interval)

    def _diff(self, watch: _WatchEntry) -> list[FileChangeEvent]:
        """Compare current state to snapshot and update snapshot in-place."""
        current = self._scan(watch.path, watch.patterns)
        events: list[FileChangeEvent] = []

        # Check for new and modified files.
        for fpath, mtime in current.items():
            old_mtime = watch.snapshot.get(fpath)
            if old_mtime is None:
                events.append(FileChangeEvent(path=fpath, change_type=ChangeType.CREATED))
            elif mtime != old_mtime:
                events.append(FileChangeEvent(path=fpath, change_type=ChangeType.MODIFIED))

        # Check for deleted files.
        for fpath in watch.snapshot:
            if fpath not in current:
                events.append(FileChangeEvent(path=fpath, change_type=ChangeType.DELETED))

        watch.snapshot = current
        return events


# ---------------------------------------------------------------------------
# CA-007: Artifact-Graph Diffing
# ---------------------------------------------------------------------------


class ArtifactGraph:
    """DAG of artifact dependencies with incremental diff computation.

    Maintains a directed acyclic graph where each node is an artifact
    identified by a string ID, and edges represent dependency relationships.
    Tracks content hashes to detect changes and propagate downstream impact.
    """

    def __init__(self) -> None:
        self._deps: dict[str, list[str]] = {}  # artifact -> list of dependencies
        self._dependents: dict[str, list[str]] = {}  # artifact -> list of dependents
        self._states: dict[str, str] = {}  # artifact -> content hash
        self._previous_states: dict[str, str] = {}

    def add_artifact(self, artifact_id: str, deps: list[str] | None = None) -> None:
        """Register an artifact with its dependencies.

        Parameters
        ----------
        artifact_id:
            Unique identifier for the artifact.
        deps:
            List of artifact IDs this artifact depends on.
        """
        deps = deps or []
        self._deps[artifact_id] = deps
        if artifact_id not in self._dependents:
            self._dependents[artifact_id] = []
        for dep in deps:
            if dep not in self._dependents:
                self._dependents[dep] = []
            self._dependents[dep].append(artifact_id)

    def record_state(self, artifact_id: str, content_hash: str) -> None:
        """Record the current content hash of an artifact.

        Parameters
        ----------
        artifact_id:
            The artifact whose state is being recorded.
        content_hash:
            A hash representing the current content.
        """
        if artifact_id in self._states:
            self._previous_states[artifact_id] = self._states[artifact_id]
        self._states[artifact_id] = content_hash

    def compute_diff(self) -> set[str]:
        """Compute the set of artifact IDs affected by recent state changes.

        An artifact is affected if its own hash changed or if any of its
        transitive dependencies changed.

        Returns
        -------
        set[str]
            IDs of all affected artifacts (changed + downstream).
        """
        changed: set[str] = set()
        for aid, current_hash in self._states.items():
            prev = self._previous_states.get(aid)
            if prev is not None and prev != current_hash:
                changed.add(aid)

        # Also include artifacts that have a state but no previous state
        # (newly recorded) -- only if they were previously tracked
        affected: set[str] = set(changed)
        queue = list(changed)
        while queue:
            node = queue.pop()
            for dependent in self._dependents.get(node, []):
                if dependent not in affected:
                    affected.add(dependent)
                    queue.append(dependent)

        return affected
