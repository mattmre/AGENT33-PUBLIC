"""Tenant-scoped task/run/evidence ledger foundation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

TaskStatus = Literal["planned", "running", "blocked", "complete"]
RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
EventKind = Literal["status", "log", "approval", "artifact", "error"]
EvidenceKind = Literal["summary", "log", "artifact", "diff", "test", "approval"]
ResumeStatus = Literal["ready", "blocked"]


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class LedgerTask:
    id: str
    tenant_id: str
    title: str
    status: TaskStatus = "planned"
    created_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class LedgerRun:
    id: str
    tenant_id: str
    task_id: str
    status: RunStatus = "queued"
    source_id: str = ""
    created_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class LedgerRunEvent:
    id: str
    tenant_id: str
    run_id: str
    kind: EventKind
    message: str
    created_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class LedgerEvidence:
    id: str
    tenant_id: str
    run_id: str
    kind: EvidenceKind
    title: str
    uri: str = ""
    created_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class LedgerRunRecord:
    task: LedgerTask
    run: LedgerRun
    events: tuple[LedgerRunEvent, ...]
    evidence: tuple[LedgerEvidence, ...]


@dataclass(frozen=True)
class LedgerTimelineItem:
    id: str
    run_id: str
    kind: str
    label: str
    uri: str = ""
    created_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class LedgerReplayCheckpoint:
    id: str
    tenant_id: str
    run_id: str
    event_id: str
    label: str
    created_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class LedgerResumePlan:
    checkpoint: LedgerReplayCheckpoint
    run: LedgerRun
    resume_status: ResumeStatus
    resume_from_event_id: str
    pending_timeline: tuple[LedgerTimelineItem, ...]
    blockers: tuple[str, ...] = ()


def _dt_to_json(value: datetime) -> str:
    return value.isoformat()


def _dt_from_json(value: str) -> datetime:
    return datetime.fromisoformat(value)


class RunLedgerRepository:
    """Tenant-scoped run ledger with optional JSON persistence."""

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self._storage_path = Path(storage_path) if storage_path is not None else None
        self._tasks: dict[str, LedgerTask] = {}
        self._runs: dict[str, LedgerRun] = {}
        self._events: list[LedgerRunEvent] = []
        self._evidence: list[LedgerEvidence] = []
        self._checkpoints: list[LedgerReplayCheckpoint] = []
        self._load()

    def create_task(
        self,
        tenant_id: str,
        title: str,
        status: TaskStatus = "planned",
    ) -> LedgerTask:
        task = LedgerTask(
            id=f"task-{uuid4().hex[:12]}",
            tenant_id=tenant_id,
            title=title,
            status=status,
            created_at=self._next_timestamp(),
        )
        self._tasks[task.id] = task
        self._save()
        return task

    def create_run(
        self,
        tenant_id: str,
        task_id: str,
        status: RunStatus = "queued",
        source_id: str = "",
    ) -> LedgerRun:
        task = self._tasks.get(task_id)
        if task is None or task.tenant_id != tenant_id:
            raise KeyError("Task is unavailable for tenant.")
        run = LedgerRun(
            id=f"run-{uuid4().hex[:12]}",
            tenant_id=tenant_id,
            task_id=task_id,
            status=status,
            source_id=source_id,
            created_at=self._next_timestamp(),
        )
        self._runs[run.id] = run
        self._save()
        return run

    def add_event(
        self,
        tenant_id: str,
        run_id: str,
        kind: EventKind,
        message: str,
    ) -> LedgerRunEvent:
        self._require_run(tenant_id, run_id)
        event = LedgerRunEvent(
            id=f"event-{uuid4().hex[:12]}",
            tenant_id=tenant_id,
            run_id=run_id,
            kind=kind,
            message=message,
            created_at=self._next_timestamp(),
        )
        self._events.append(event)
        self._save()
        return event

    def add_evidence(
        self,
        tenant_id: str,
        run_id: str,
        kind: EvidenceKind,
        title: str,
        uri: str = "",
    ) -> LedgerEvidence:
        self._require_run(tenant_id, run_id)
        evidence = LedgerEvidence(
            id=f"evidence-{uuid4().hex[:12]}",
            tenant_id=tenant_id,
            run_id=run_id,
            kind=kind,
            title=title,
            uri=uri,
            created_at=self._next_timestamp(),
        )
        self._evidence.append(evidence)
        self._save()
        return evidence

    def list_records(self, tenant_id: str) -> list[LedgerRunRecord]:
        records: list[LedgerRunRecord] = []
        for run in self._runs.values():
            if run.tenant_id != tenant_id:
                continue
            task = self._tasks[run.task_id]
            records.append(
                LedgerRunRecord(
                    task=task,
                    run=run,
                    events=tuple(event for event in self._events if event.run_id == run.id),
                    evidence=tuple(item for item in self._evidence if item.run_id == run.id),
                )
            )
        return sorted(records, key=lambda record: record.run.created_at, reverse=True)

    def get_record(self, tenant_id: str, run_id: str) -> LedgerRunRecord:
        run = self._require_run(tenant_id, run_id)
        task = self._tasks[run.task_id]
        return LedgerRunRecord(
            task=task,
            run=run,
            events=tuple(event for event in self._events if event.run_id == run.id),
            evidence=tuple(item for item in self._evidence if item.run_id == run.id),
        )

    def get_evidence(self, tenant_id: str, evidence_id: str) -> LedgerEvidence:
        for evidence in self._evidence:
            if evidence.id == evidence_id and evidence.tenant_id == tenant_id:
                return evidence
        raise KeyError("Evidence is unavailable for tenant.")

    def replay_timeline(self, tenant_id: str, run_id: str) -> list[LedgerTimelineItem]:
        self._require_run(tenant_id, run_id)
        items = [
            LedgerTimelineItem(
                id=event.id,
                run_id=event.run_id,
                kind=f"event:{event.kind}",
                label=event.message,
                created_at=event.created_at,
            )
            for event in self._events
            if event.tenant_id == tenant_id and event.run_id == run_id
        ]
        items.extend(
            LedgerTimelineItem(
                id=evidence.id,
                run_id=evidence.run_id,
                kind=f"evidence:{evidence.kind}",
                label=evidence.title,
                uri=evidence.uri,
                created_at=evidence.created_at,
            )
            for evidence in self._evidence
            if evidence.tenant_id == tenant_id and evidence.run_id == run_id
        )
        return sorted(items, key=lambda item: item.created_at)

    def create_replay_checkpoint(
        self,
        tenant_id: str,
        run_id: str,
        *,
        event_id: str = "",
        label: str = "",
    ) -> LedgerReplayCheckpoint:
        """Persist a checkpoint anchored to a real event/evidence item in the replay timeline."""
        self._require_run(tenant_id, run_id)
        timeline = self.replay_timeline(tenant_id, run_id)
        if not timeline:
            raise ValueError("Cannot checkpoint a run with no replay timeline.")
        anchor = event_id or timeline[-1].id
        if anchor not in {item.id for item in timeline}:
            raise ValueError("Checkpoint event is not present in the run replay timeline.")
        checkpoint = LedgerReplayCheckpoint(
            id=f"checkpoint-{uuid4().hex[:12]}",
            tenant_id=tenant_id,
            run_id=run_id,
            event_id=anchor,
            label=label or f"Replay checkpoint at {anchor}",
            created_at=self._next_timestamp(),
        )
        self._checkpoints.append(checkpoint)
        self._save()
        return checkpoint

    def latest_replay_checkpoint(
        self,
        tenant_id: str,
        run_id: str,
    ) -> LedgerReplayCheckpoint:
        self._require_run(tenant_id, run_id)
        checkpoints = [
            checkpoint
            for checkpoint in self._checkpoints
            if checkpoint.tenant_id == tenant_id and checkpoint.run_id == run_id
        ]
        if not checkpoints:
            raise KeyError("Replay checkpoint is unavailable for tenant.")
        return sorted(checkpoints, key=lambda checkpoint: checkpoint.created_at)[-1]

    def build_resume_plan(self, tenant_id: str, run_id: str) -> LedgerResumePlan:
        run = self._require_run(tenant_id, run_id)
        checkpoint = self.latest_replay_checkpoint(tenant_id, run_id)
        timeline = self.replay_timeline(tenant_id, run_id)
        anchor_index = next(
            (index for index, item in enumerate(timeline) if item.id == checkpoint.event_id),
            -1,
        )
        if anchor_index < 0:
            return LedgerResumePlan(
                checkpoint=checkpoint,
                run=run,
                resume_status="blocked",
                resume_from_event_id=checkpoint.event_id,
                pending_timeline=(),
                blockers=("checkpoint anchor missing from replay timeline",),
            )
        return LedgerResumePlan(
            checkpoint=checkpoint,
            run=run,
            resume_status="ready",
            resume_from_event_id=checkpoint.event_id,
            pending_timeline=tuple(timeline[anchor_index + 1 :]),
        )

    def _require_run(self, tenant_id: str, run_id: str) -> LedgerRun:
        run = self._runs.get(run_id)
        if run is None or run.tenant_id != tenant_id:
            raise KeyError("Run is unavailable for tenant.")
        return run

    def _next_timestamp(self) -> datetime:
        now = _now()
        prior_timestamps = (
            [task.created_at for task in self._tasks.values()]
            + [run.created_at for run in self._runs.values()]
            + [event.created_at for event in self._events]
            + [evidence.created_at for evidence in self._evidence]
            + [checkpoint.created_at for checkpoint in self._checkpoints]
        )
        if not prior_timestamps:
            return now
        latest = max(prior_timestamps)
        if now > latest:
            return now
        return latest + timedelta(microseconds=1)

    def _load(self) -> None:
        if self._storage_path is None or not self._storage_path.exists():
            return
        payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        self._tasks = {
            item["id"]: LedgerTask(
                id=item["id"],
                tenant_id=item["tenant_id"],
                title=item["title"],
                status=item["status"],
                created_at=_dt_from_json(item["created_at"]),
            )
            for item in payload.get("tasks", [])
        }
        self._runs = {
            item["id"]: LedgerRun(
                id=item["id"],
                tenant_id=item["tenant_id"],
                task_id=item["task_id"],
                status=item["status"],
                source_id=item.get("source_id", ""),
                created_at=_dt_from_json(item["created_at"]),
            )
            for item in payload.get("runs", [])
        }
        self._events = [
            LedgerRunEvent(
                id=item["id"],
                tenant_id=item["tenant_id"],
                run_id=item["run_id"],
                kind=item["kind"],
                message=item["message"],
                created_at=_dt_from_json(item["created_at"]),
            )
            for item in payload.get("events", [])
        ]
        self._evidence = [
            LedgerEvidence(
                id=item["id"],
                tenant_id=item["tenant_id"],
                run_id=item["run_id"],
                kind=item["kind"],
                title=item["title"],
                uri=item.get("uri", ""),
                created_at=_dt_from_json(item["created_at"]),
            )
            for item in payload.get("evidence", [])
        ]
        self._checkpoints = [
            LedgerReplayCheckpoint(
                id=item["id"],
                tenant_id=item["tenant_id"],
                run_id=item["run_id"],
                event_id=item["event_id"],
                label=item["label"],
                created_at=_dt_from_json(item["created_at"]),
            )
            for item in payload.get("checkpoints", [])
        ]

    def _save(self) -> None:
        if self._storage_path is None:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "tasks": [
                {
                    "id": task.id,
                    "tenant_id": task.tenant_id,
                    "title": task.title,
                    "status": task.status,
                    "created_at": _dt_to_json(task.created_at),
                }
                for task in self._tasks.values()
            ],
            "runs": [
                {
                    "id": run.id,
                    "tenant_id": run.tenant_id,
                    "task_id": run.task_id,
                    "status": run.status,
                    "source_id": run.source_id,
                    "created_at": _dt_to_json(run.created_at),
                }
                for run in self._runs.values()
            ],
            "events": [
                {
                    "id": event.id,
                    "tenant_id": event.tenant_id,
                    "run_id": event.run_id,
                    "kind": event.kind,
                    "message": event.message,
                    "created_at": _dt_to_json(event.created_at),
                }
                for event in self._events
            ],
            "evidence": [
                {
                    "id": evidence.id,
                    "tenant_id": evidence.tenant_id,
                    "run_id": evidence.run_id,
                    "kind": evidence.kind,
                    "title": evidence.title,
                    "uri": evidence.uri,
                    "created_at": _dt_to_json(evidence.created_at),
                }
                for evidence in self._evidence
            ],
            "checkpoints": [
                {
                    "id": checkpoint.id,
                    "tenant_id": checkpoint.tenant_id,
                    "run_id": checkpoint.run_id,
                    "event_id": checkpoint.event_id,
                    "label": checkpoint.label,
                    "created_at": _dt_to_json(checkpoint.created_at),
                }
                for checkpoint in self._checkpoints
            ],
        }
        self._storage_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
