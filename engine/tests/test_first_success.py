from __future__ import annotations

from fastapi.testclient import TestClient

from agent33.api.routes.run_ledger import get_run_ledger_repository
from agent33.main import app
from agent33.ops.first_success import DEFAULT_FIRST_SUCCESS_PLAN, create_first_success_smoke_run
from agent33.ops.run_ledger import RunLedgerRepository
from agent33.security.auth import create_access_token


def test_first_success_smoke_run_creates_evidence_record() -> None:
    repository = RunLedgerRepository()

    record = create_first_success_smoke_run(repository, "tenant-a")

    assert record.task.title == DEFAULT_FIRST_SUCCESS_PLAN.title
    assert record.run.status == "succeeded"
    assert record.run.source_id == "doctor:first-success"
    assert record.events[0].message.startswith("First-success smoke completed")
    assert record.evidence[0].uri == "doctor:first-success"


def test_first_success_plan_route() -> None:
    token = create_access_token("doctor-user", scopes=["operator:read"], tenant_id="tenant-a")
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

    response = client.get("/v1/doctor/first-success")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "First-success setup smoke"
    assert len(body["steps"]) == 3


def test_first_success_run_route_records_run() -> None:
    token = create_access_token("doctor-user", scopes=["workflows:write"], tenant_id="tenant-a")
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

    response = client.post("/v1/doctor/first-success/run")

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["status"] == "succeeded"
    assert body["evidence"][0]["title"] == "First-success smoke proof"
    assert get_run_ledger_repository().list_records("tenant-a")
