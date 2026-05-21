"""Persistence helpers for SkillsBench benchmark runs and artifacts."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, cast

from agent33.benchmarks.skillsbench.models import BenchmarkRunResult, TrialArtifact

if TYPE_CHECKING:
    from pathlib import Path


_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class SkillsBenchArtifactStore:
    """File-backed persistence for benchmark runs and trial artifacts."""

    def __init__(self, base_path: Path, preview_chars: int = 400) -> None:
        self._base_path = base_path
        self._preview_chars = preview_chars

    @property
    def base_path(self) -> Path:
        """Return the storage root."""
        return self._base_path

    def persist_run(self, run: BenchmarkRunResult) -> Path:
        """Persist a benchmark run JSON snapshot."""
        run_dir = self._run_dir(run.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "run.json"
        path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_run(self, run_id: str) -> BenchmarkRunResult | None:
        """Load a persisted run if it exists."""
        path = self._run_dir(run_id) / "run.json"
        if not path.is_file():
            return None
        return BenchmarkRunResult.model_validate_json(path.read_text(encoding="utf-8"))

    def has_run(self, run_id: str) -> bool:
        """Return whether a persisted snapshot exists for the run."""
        return (self._run_dir(run_id) / "run.json").is_file()

    def list_runs(self, limit: int = 50) -> list[BenchmarkRunResult]:
        """List persisted runs, newest first."""
        if not self._base_path.exists():
            return []

        run_files = sorted(
            self._base_path.glob("*/run.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        runs: list[BenchmarkRunResult] = []
        for path in run_files[:limit]:
            payload = cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))
            runs.append(
                BenchmarkRunResult.model_validate(
                    {
                        "run_id": payload.get("run_id", ""),
                        "status": payload.get("status", ""),
                        "started_at": payload.get("started_at"),
                        "completed_at": payload.get("completed_at"),
                        "config_summary": payload.get("config_summary", {}),
                        "total_tasks": payload.get("total_tasks", 0),
                        "total_trials": payload.get("total_trials", 0),
                        "passed_trials": payload.get("passed_trials", 0),
                        "failed_trials": payload.get("failed_trials", 0),
                        "error_trials": payload.get("error_trials", 0),
                        "pass_rate": payload.get("pass_rate", 0.0),
                        "total_tokens_used": payload.get("total_tokens_used", 0),
                        "total_duration_ms": payload.get("total_duration_ms", 0.0),
                        "task_summaries": payload.get("task_summaries", []),
                        "artifact_root": payload.get("artifact_root", ""),
                        "ctrf_report_path": payload.get("ctrf_report_path", ""),
                    }
                )
            )
        return runs

    def persist_text_artifact(
        self,
        *,
        run_id: str,
        task_id: str,
        trial_number: int,
        kind: str,
        filename: str,
        content: str,
        content_type: str = "text/plain",
    ) -> TrialArtifact:
        """Persist a text artifact and return its metadata record."""
        trial_dir = self._trial_dir(run_id, task_id, trial_number)
        trial_dir.mkdir(parents=True, exist_ok=True)
        path = trial_dir / filename
        path.write_text(content, encoding="utf-8")
        relative_path = path.relative_to(self._run_dir(run_id)).as_posix()
        return TrialArtifact(
            name=filename,
            kind=kind,
            relative_path=relative_path,
            content_type=content_type,
            size_bytes=path.stat().st_size,
            preview=content[: self._preview_chars],
        )

    def read_artifact(self, run_id: str, relative_path: str) -> str | None:
        """Read a stored artifact if it remains within the run directory."""
        run_dir = self._run_dir(run_id).resolve()
        target = (run_dir / relative_path).resolve()
        try:
            target.relative_to(run_dir)
        except ValueError:
            return None
        if not target.is_file():
            return None
        return target.read_text(encoding="utf-8")

    def persist_ctrf_report(self, run_id: str, report: dict[str, Any]) -> Path:
        """Persist a CTRF report for a benchmark run."""
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "ctrf.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return path

    def load_ctrf_report(self, run_id: str) -> dict[str, Any] | None:
        """Load a persisted CTRF report if present."""
        path = self._run_dir(run_id) / "ctrf.json"
        if not path.is_file():
            return None
        return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))

    def _run_dir(self, run_id: str) -> Path:
        safe_run_id = run_id.strip()
        if not _RUN_ID_PATTERN.fullmatch(safe_run_id):
            raise ValueError(f"Invalid SkillsBench run_id: {run_id!r}")
        return self._base_path / safe_run_id

    def _trial_dir(self, run_id: str, task_id: str, trial_number: int) -> Path:
        safe_task_id = task_id.replace("/", "__")
        return self._run_dir(run_id) / "trials" / safe_task_id / f"trial-{trial_number:02d}"
