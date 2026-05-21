from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent33.main import app
from agent33.ops.run_ledger import RunLedgerRepository
from agent33.security.auth import create_access_token


def test_run_ledger_records_task_run_events_and_evidence() -> None:
    repository = RunLedgerRepository()

    task = repository.create_task("tenant-a", "Build result page")
    run = repository.create_run("tenant-a", task.id, status="running", source_id="spawner-1")
    event = repository.add_event("tenant-a", run.id, "status", "Run started")
    evidence = repository.add_evidence(
        "tenant-a", run.id, "artifact", "Plan artifact", "artifact://plan"
    )

    records = repository.list_records("tenant-a")

    assert len(records) == 1
    assert records[0].task == task
    assert records[0].run == run
    assert records[0].events == (event,)
    assert records[0].evidence == (evidence,)


def test_run_ledger_is_tenant_scoped() -> None:
    repository = RunLedgerRepository()

    task = repository.create_task("tenant-a", "Tenant A task")
    run = repository.create_run("tenant-a", task.id)
    repository.add_event("tenant-a", run.id, "log", "Only tenant A can see this")

    assert repository.list_records("tenant-b") == []
    with pytest.raises(KeyError):
        repository.add_evidence("tenant-b", run.id, "log", "Wrong tenant")


def test_run_ledger_persists_records_across_repository_instances(tmp_path) -> None:
    storage_path = tmp_path / "run-ledger.json"
    repository = RunLedgerRepository(storage_path)

    task = repository.create_task("tenant-a", "Durable task")
    run = repository.create_run("tenant-a", task.id, status="succeeded", source_id="workflow-1")
    repository.add_event("tenant-a", run.id, "status", "Run finished")
    repository.add_evidence("tenant-a", run.id, "test", "Pytest result", "artifact://pytest")

    reloaded = RunLedgerRepository(storage_path)
    records = reloaded.list_records("tenant-a")

    assert len(records) == 1
    assert records[0].task.id == task.id
    assert records[0].run.id == run.id
    assert records[0].run.status == "succeeded"
    assert records[0].events[0].message == "Run finished"
    assert records[0].evidence[0].uri == "artifact://pytest"


def test_run_ledger_returns_evidence_and_replay_timeline() -> None:
    repository = RunLedgerRepository()

    task = repository.create_task("tenant-a", "Replay task")
    run = repository.create_run("tenant-a", task.id, status="running")
    event = repository.add_event("tenant-a", run.id, "status", "Run started")
    evidence = repository.add_evidence(
        "tenant-a",
        run.id,
        "artifact",
        "Review artifact",
        "artifact://review",
    )

    assert repository.get_evidence("tenant-a", evidence.id) == evidence

    timeline = repository.replay_timeline("tenant-a", run.id)

    assert [item.id for item in timeline] == [event.id, evidence.id]
    assert timeline[0].kind == "event:status"
    assert timeline[1].kind == "evidence:artifact"
    assert timeline[1].uri == "artifact://review"


def test_run_ledger_evidence_lookup_is_tenant_scoped() -> None:
    repository = RunLedgerRepository()

    task = repository.create_task("tenant-a", "Private task")
    run = repository.create_run("tenant-a", task.id)
    evidence = repository.add_evidence("tenant-a", run.id, "artifact", "Private")

    with pytest.raises(KeyError):
        repository.get_evidence("tenant-b", evidence.id)


def test_run_ledger_persists_replay_checkpoint_and_resume_plan(tmp_path) -> None:
    storage_path = tmp_path / "run-ledger.json"
    repository = RunLedgerRepository(storage_path)
    task = repository.create_task("tenant-a", "Replay resume task")
    run = repository.create_run("tenant-a", task.id, status="running")
    first = repository.add_event("tenant-a", run.id, "status", "Run started")
    repository.add_evidence("tenant-a", run.id, "artifact", "First artifact")
    checkpoint = repository.create_replay_checkpoint(
        "tenant-a",
        run.id,
        event_id=first.id,
        label="After start",
    )
    repository.add_event("tenant-a", run.id, "log", "Post-checkpoint work")

    reloaded = RunLedgerRepository(storage_path)
    plan = reloaded.build_resume_plan("tenant-a", run.id)

    assert plan.checkpoint.id == checkpoint.id
    assert plan.resume_status == "ready"
    assert plan.resume_from_event_id == first.id
    assert [item.label for item in plan.pending_timeline] == [
        "First artifact",
        "Post-checkpoint work",
    ]


def test_run_ledger_rejects_checkpoint_not_in_replay_timeline() -> None:
    repository = RunLedgerRepository()
    task = repository.create_task("tenant-a", "Replay resume task")
    run = repository.create_run("tenant-a", task.id, status="running")
    repository.add_event("tenant-a", run.id, "status", "Run started")

    with pytest.raises(ValueError, match="not present"):
        repository.create_replay_checkpoint("tenant-a", run.id, event_id="event-missing")


def test_run_ledger_checkpoint_api_returns_resume_plan() -> None:
    from agent33.api.routes import run_ledger as route_mod

    repository = RunLedgerRepository()
    route_mod._repository = repository
    task = repository.create_task("tenant-a", "API replay resume")
    run = repository.create_run("tenant-a", task.id, status="running")
    event = repository.add_event("tenant-a", run.id, "status", "Run started")
    repository.add_event("tenant-a", run.id, "log", "Post-checkpoint work")
    token = create_access_token(
        "run-ledger-user",
        scopes=["workflows:read", "workflows:write"],
        tenant_id="tenant-a",
    )
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

    checkpoint_response = client.post(
        f"/v1/run-ledger/{run.id}/checkpoints",
        json={"event_id": event.id, "label": "API checkpoint"},
    )
    resume_response = client.get(f"/v1/run-ledger/{run.id}/resume-plan")

    assert checkpoint_response.status_code == 200
    assert checkpoint_response.json()["checkpoint"]["event_id"] == event.id
    assert resume_response.status_code == 200
    body = resume_response.json()
    assert body["resume_status"] == "ready"
    assert body["resume_from_event_id"] == event.id
    assert [item["label"] for item in body["pending_timeline"]] == ["Post-checkpoint work"]
