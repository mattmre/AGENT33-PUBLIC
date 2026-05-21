"""File-backed archive helpers for durable workflow run inspection."""

from __future__ import annotations

import json
import mimetypes
import re
import shutil
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TypeGuard

from agent33.workflows.events import WorkflowEvent
from agent33.workflows.executor import WorkflowResult
from agent33.workflows.history import WorkflowExecutionRecord, normalize_execution_record

_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


class WorkflowRunArchiveService:
    """Persist per-run workflow metadata, events, results, and artifacts."""

    def __init__(self, base_path: str | Path, *, preview_chars: int = 400) -> None:
        self._base_path = Path(base_path)
        self._preview_chars = max(0, preview_chars)
        self._base_path.mkdir(parents=True, exist_ok=True)

    @property
    def base_path(self) -> Path:
        """Return the archive storage root."""
        return self._base_path

    def initialize_run(
        self,
        run_id: str,
        workflow_name: str,
        *,
        trigger_type: str = "manual",
        started_at: float | None = None,
        metadata: Mapping[str, Any] | None = None,
        owner_subject: str | None = None,
        tenant_id: str = "",
    ) -> dict[str, Any]:
        """Compatibility alias for starting a new archived run."""
        return self.start_run(
            run_id,
            workflow_name,
            trigger_type=trigger_type,
            started_at=started_at,
            metadata=metadata,
            owner_subject=owner_subject,
            tenant_id=tenant_id,
        )

    def start_run(
        self,
        run_id: str,
        workflow_name: str,
        *,
        trigger_type: str = "manual",
        started_at: float | None = None,
        metadata: Mapping[str, Any] | None = None,
        owner_subject: str | None = None,
        tenant_id: str = "",
    ) -> dict[str, Any]:
        """Create or replace the persisted metadata record for one run."""
        safe_run_id = self._validate_run_id(run_id)
        run_dir = self._run_dir(safe_run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)

        now = float(started_at if started_at is not None else time.time())
        payload = {
            "run_id": safe_run_id,
            "workflow_name": str(workflow_name).strip(),
            "trigger_type": str(trigger_type).strip() or "manual",
            "status": "running",
            "started_at": now,
            "updated_at": now,
            "completed_at": None,
            "owner_subject": owner_subject,
            "tenant_id": str(tenant_id),
            "metadata": self._coerce_mapping(metadata),
            "event_count": 0,
            "artifact_count": 0,
        }
        self._write_json_atomic(self._run_path(safe_run_id), payload)
        self._events_path(safe_run_id).touch(exist_ok=True)
        self._write_json_atomic(self._artifacts_manifest_path(safe_run_id), [])
        return dict(payload)

    def has_run(self, run_id: str) -> bool:
        """Return ``True`` when archive metadata exists for ``run_id``."""
        return self._run_path(run_id).is_file()

    def append_event(
        self,
        run_id: str,
        event: WorkflowEvent | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Append one serialized event to the run event log."""
        run_payload = self._load_required_run(run_id)
        event_payload = self._normalize_event(
            run_id,
            event,
            workflow_name=str(run_payload.get("workflow_name", "")),
        )

        with self._events_path(run_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event_payload, sort_keys=True))
            handle.write("\n")

        run_payload["event_count"] = int(run_payload.get("event_count", 0)) + 1
        run_payload["updated_at"] = time.time()
        self._write_json_atomic(self._run_path(run_id), run_payload)
        return event_payload

    def record_result(
        self,
        run_id: str,
        result: WorkflowResult | Mapping[str, Any],
        *,
        history_record: WorkflowExecutionRecord | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist the final workflow result, history record, and artifacts."""
        run_payload = self._load_required_run(run_id)
        result_payload = self._normalize_result(result)
        self._write_json_atomic(self._result_path(run_id), result_payload)

        normalized_history: dict[str, Any] | None = None
        if history_record is not None:
            normalized_history = normalize_execution_record(history_record).model_dump(mode="json")
            self._write_json_atomic(self._history_path(run_id), normalized_history)
        elif self._history_path(run_id).is_file():
            loaded_history = self._load_json_file(self._history_path(run_id))
            if isinstance(loaded_history, Mapping):
                normalized_history = dict(loaded_history)

        manifest = self._extract_artifacts(run_id, result_payload)
        completed_at = self._resolve_completed_at(result_payload, normalized_history)
        run_payload.update(
            {
                "status": self._resolve_status(result_payload, normalized_history),
                "completed_at": completed_at,
                "updated_at": time.time(),
                "artifact_count": len(manifest),
            }
        )
        if normalized_history is not None:
            run_payload["duration_ms"] = normalized_history.get("duration_ms", 0.0)
            run_payload["error"] = normalized_history.get("error")
            run_payload["timestamp"] = normalized_history.get("timestamp")
        elif "duration_ms" in result_payload:
            run_payload["duration_ms"] = result_payload.get("duration_ms", 0.0)
            run_payload["error"] = self._extract_result_error(result_payload)

        self._write_json_atomic(self._run_path(run_id), run_payload)
        return dict(result_payload)

    def load_summary(self, run_id: str) -> dict[str, Any] | None:
        """Load the persisted run summary if it exists."""
        path = self._run_path(run_id)
        if not path.is_file():
            return None
        payload = self._load_json_file(path)
        return dict(payload) if isinstance(payload, Mapping) else None

    def load_detail(self, run_id: str) -> dict[str, Any] | None:
        """Load a full run record with summary, result, events, and artifacts."""
        summary = self.load_summary(run_id)
        if summary is None:
            return None
        return {
            "run": summary,
            "history": self._load_json_optional(self._history_path(run_id)),
            "result": self._load_json_optional(self._result_path(run_id)),
            "events": self.list_events(run_id),
            "artifacts": self.list_artifacts(run_id),
        }

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Return the archived run detail payload for one run."""
        return self.load_detail(run_id)

    def list_events(
        self,
        run_id: str,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return archived events for one run with optional pagination."""
        path = self._events_path(run_id)
        if not path.is_file():
            return []
        events: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for index, raw_line in enumerate(handle):
                if index < max(0, offset):
                    continue
                line = raw_line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if isinstance(payload, Mapping):
                    events.append(dict(payload))
                if limit is not None and limit >= 0 and len(events) >= limit:
                    break
        return events

    def read_events(
        self,
        run_id: str,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Compatibility alias for returning archived run events."""
        return self.list_events(run_id, offset=offset, limit=limit)

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        """Return the persisted artifact manifest for one run."""
        payload = self._load_json_optional(self._artifacts_manifest_path(run_id))
        if not isinstance(payload, list):
            return []
        return [dict(item) for item in payload if isinstance(item, Mapping)]

    def read_artifact(self, run_id: str, relative_path: str) -> str | None:
        """Read a text artifact if it remains within the run directory."""
        run_dir = self._run_dir(run_id).resolve()
        target = (run_dir / relative_path).resolve()
        try:
            target.relative_to(run_dir)
        except ValueError:
            return None
        if not target.is_file():
            return None
        return target.read_text(encoding="utf-8", errors="replace")

    def get_artifact(self, run_id: str, relative_path: str) -> str | None:
        """Compatibility alias for reading one archived artifact."""
        return self.read_artifact(run_id, relative_path)

    def _extract_artifacts(
        self,
        run_id: str,
        result_payload: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        run_dir = self._run_dir(run_id)
        artifacts_dir = run_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        manifest: list[dict[str, Any]] = self.list_artifacts(run_id)
        used_names: set[str] = {
            Path(str(item.get("relative_path", item.get("name", "")))).name
            for item in manifest
            if item.get("relative_path") or item.get("name")
        }

        for artifact in self._iter_inline_artifacts(result_payload):
            filename = self._make_unique_filename(
                artifact["filename_hint"],
                mime_type=artifact["mime_type"],
                used_names=used_names,
            )
            target = artifacts_dir / filename
            content = artifact["content"]
            target.write_text(content, encoding="utf-8")
            manifest.append(
                self._artifact_manifest_entry(
                    run_dir=run_dir,
                    target=target,
                    source=artifact["source"],
                    step_id=artifact["step_id"],
                    mime_type=artifact["mime_type"],
                    metadata=artifact["metadata"],
                    preview=content[: self._preview_chars],
                )
            )

        for artifact in self._iter_output_files(result_payload):
            source_path = Path(artifact["source_path"])
            if not source_path.is_file():
                continue
            filename = self._make_unique_filename(
                source_path.name,
                mime_type=artifact["mime_type"],
                used_names=used_names,
            )
            target = artifacts_dir / filename
            shutil.copyfile(source_path, target)
            preview = ""
            if self._preview_chars > 0:
                try:
                    preview = target.read_text(encoding="utf-8")[: self._preview_chars]
                except OSError:
                    preview = ""
            manifest.append(
                self._artifact_manifest_entry(
                    run_dir=run_dir,
                    target=target,
                    source=artifact["source"],
                    step_id=artifact["step_id"],
                    mime_type=artifact["mime_type"],
                    metadata={},
                    preview=preview,
                )
            )

        self._write_json_atomic(self._artifacts_manifest_path(run_id), manifest)
        return manifest

    def _artifact_manifest_entry(
        self,
        *,
        run_dir: Path,
        target: Path,
        source: str,
        step_id: str | None,
        mime_type: str,
        metadata: Mapping[str, Any],
        preview: str,
    ) -> dict[str, Any]:
        return {
            "name": target.name,
            "relative_path": target.relative_to(run_dir).as_posix(),
            "size_bytes": target.stat().st_size,
            "mime_type": mime_type,
            "source": source,
            "step_id": step_id,
            "metadata": dict(metadata),
            "preview": preview,
        }

    def _iter_inline_artifacts(self, result_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        extracted: list[dict[str, Any]] = []
        for source, step_id, container in self._artifact_containers(result_payload):
            raw_artifacts = container.get("artifacts")
            if not self._is_sequence(raw_artifacts):
                continue
            for index, raw_artifact in enumerate(raw_artifacts, start=1):
                if not isinstance(raw_artifact, Mapping):
                    continue
                artifact_payload = self._json_safe(raw_artifact)
                data = artifact_payload.get("data")
                if data is None:
                    continue
                content = (
                    data if isinstance(data, str) else json.dumps(data, indent=2, sort_keys=True)
                )
                metadata = self._coerce_mapping(artifact_payload.get("metadata"))
                mime_type = str(artifact_payload.get("mime_type", "text/plain")) or "text/plain"
                step_label = step_id or "result"
                filename_hint = str(
                    metadata.get("filename")
                    or metadata.get("name")
                    or f"{step_label}-artifact-{index}{self._guess_suffix(mime_type)}"
                )
                extracted.append(
                    {
                        "source": f"{source}.artifacts[{index - 1}]",
                        "step_id": step_id,
                        "mime_type": mime_type,
                        "metadata": metadata,
                        "filename_hint": filename_hint,
                        "content": content,
                    }
                )
        return extracted

    def _iter_output_files(self, result_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        extracted: list[dict[str, Any]] = []
        for source, step_id, container in self._artifact_containers(result_payload):
            raw_output_files = container.get("output_files")
            if not self._is_sequence(raw_output_files):
                continue
            for index, raw_path in enumerate(raw_output_files, start=1):
                source_path = str(raw_path).strip()
                if not source_path:
                    continue
                extracted.append(
                    {
                        "source": f"{source}.output_files[{index - 1}]",
                        "step_id": step_id,
                        "mime_type": (
                            mimetypes.guess_type(source_path)[0] or "application/octet-stream"
                        ),
                        "source_path": source_path,
                    }
                )
        return extracted

    def _artifact_containers(
        self,
        result_payload: Mapping[str, Any],
    ) -> list[tuple[str, str | None, Mapping[str, Any]]]:
        containers: list[tuple[str, str | None, Mapping[str, Any]]] = []
        containers.append(("result", None, result_payload))
        raw_step_results = result_payload.get("step_results")
        if not self._is_sequence(raw_step_results):
            return containers
        for index, raw_step_result in enumerate(raw_step_results, start=1):
            if not isinstance(raw_step_result, Mapping):
                continue
            outputs = raw_step_result.get("outputs")
            if not isinstance(outputs, Mapping):
                continue
            raw_step_id = str(raw_step_result.get("step_id", "")).strip()
            step_id = raw_step_id or f"step-{index}"
            containers.append((f"step_results[{index - 1}].outputs", step_id, outputs))
        return containers

    def _normalize_event(
        self,
        run_id: str,
        event: WorkflowEvent | Mapping[str, Any],
        *,
        workflow_name: str,
    ) -> dict[str, Any]:
        payload = event.to_dict() if isinstance(event, WorkflowEvent) else self._json_safe(event)
        if isinstance(event, WorkflowEvent) and event.event_id is not None:
            payload["event_id"] = event.event_id
        event_run_id = str(payload.get("run_id", "")).strip()
        if event_run_id and event_run_id != run_id:
            raise ValueError(
                f"Workflow event run_id mismatch: expected {run_id!r}, got {event_run_id!r}",
            )
        payload["run_id"] = run_id
        payload["workflow_name"] = str(payload.get("workflow_name", workflow_name)).strip()
        payload["timestamp"] = float(payload.get("timestamp", time.time()))
        if "type" not in payload and "event_type" in payload:
            payload["type"] = str(payload["event_type"])
        return payload

    def _normalize_result(
        self,
        result: WorkflowResult | Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = (
            result.model_dump(mode="json")
            if isinstance(result, WorkflowResult)
            else self._json_safe(result)
        )
        if not isinstance(payload, Mapping):
            raise TypeError("workflow result must serialize to a mapping")
        return dict(payload)

    def _resolve_status(
        self,
        result_payload: Mapping[str, Any],
        history_payload: Mapping[str, Any] | None,
    ) -> str:
        if history_payload is not None:
            return str(history_payload.get("status", "completed")) or "completed"
        status = result_payload.get("status", "completed")
        return str(status) or "completed"

    def _resolve_completed_at(
        self,
        result_payload: Mapping[str, Any],
        history_payload: Mapping[str, Any] | None,
    ) -> float:
        if history_payload is not None:
            return float(history_payload.get("timestamp", time.time()))
        return time.time()

    def _extract_result_error(self, result_payload: Mapping[str, Any]) -> str | None:
        raw_step_results = result_payload.get("step_results")
        if not self._is_sequence(raw_step_results):
            return None
        for raw_step_result in reversed(raw_step_results):
            if not isinstance(raw_step_result, Mapping):
                continue
            error = raw_step_result.get("error")
            if error is not None:
                text = str(error).strip()
                if text:
                    return text
        return None

    def _make_unique_filename(
        self,
        name_hint: str,
        *,
        mime_type: str | None,
        used_names: set[str],
    ) -> str:
        raw_name = Path(str(name_hint).strip() or "artifact").name
        stem = raw_name.rsplit(".", 1)[0] if "." in raw_name else raw_name
        suffix = ""
        if "." in raw_name:
            suffix = "." + raw_name.rsplit(".", 1)[1]
        if not suffix:
            suffix = self._guess_suffix(mime_type or "text/plain")
        safe_stem = _SAFE_FILENAME_CHARS.sub("-", stem).strip("-.") or "artifact"
        safe_suffix = _SAFE_FILENAME_CHARS.sub("", suffix) or self._guess_suffix(
            mime_type or "text/plain",
        )
        candidate = f"{safe_stem}{safe_suffix}"
        counter = 2
        while candidate in used_names:
            candidate = f"{safe_stem}-{counter}{safe_suffix}"
            counter += 1
        used_names.add(candidate)
        return candidate

    def _guess_suffix(self, mime_type: str) -> str:
        if mime_type == "text/plain":
            return ".txt"
        if mime_type == "text/markdown":
            return ".md"
        if mime_type == "text/html":
            return ".html"
        if mime_type == "image/svg+xml":
            return ".svg"
        guessed = mimetypes.guess_extension(mime_type, strict=False)
        return guessed or ".txt"

    def _run_dir(self, run_id: str) -> Path:
        return self._base_path / self._validate_run_id(run_id)

    def _run_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "run.json"

    def _history_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "history.json"

    def _result_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "result.json"

    def _events_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "events.jsonl"

    def _artifacts_manifest_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "artifacts.json"

    def _validate_run_id(self, run_id: str) -> str:
        safe_run_id = str(run_id).strip()
        if not _RUN_ID_PATTERN.fullmatch(safe_run_id):
            raise ValueError(f"Invalid workflow run_id: {run_id!r}")
        return safe_run_id

    def _load_required_run(self, run_id: str) -> dict[str, Any]:
        payload = self.load_summary(run_id)
        if payload is None:
            raise FileNotFoundError(f"Workflow archive not found for run_id={run_id!r}")
        return payload

    def _load_json_optional(self, path: Path) -> Any | None:
        if not path.is_file():
            return None
        return self._load_json_file(path)

    def _load_json_file(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json_atomic(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(path)

    def _coerce_mapping(self, value: Any) -> dict[str, Any]:
        normalized = self._json_safe(value)
        return dict(normalized) if isinstance(normalized, Mapping) else {}

    def _json_safe(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Path):
            return str(value)
        if hasattr(value, "model_dump"):
            return self._json_safe(value.model_dump(mode="json"))
        if isinstance(value, Mapping):
            return {str(key): self._json_safe(item) for key, item in value.items()}
        if self._is_sequence(value):
            return [self._json_safe(item) for item in value]
        return str(value)

    def _is_sequence(self, value: object) -> TypeGuard[Sequence[Any]]:
        return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
