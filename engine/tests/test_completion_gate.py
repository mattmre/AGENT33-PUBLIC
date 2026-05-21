from __future__ import annotations

from fastapi.testclient import TestClient

from agent33.api.routes.completion_gate import router
from agent33.main import app
from agent33.ops.completion_gate import (
    CompletionGateInput,
    CompletionGateMode,
    evaluate_completion_gate,
)
from agent33.security.auth import create_access_token


def test_completion_gate_advisory_reports_missing_without_blocking() -> None:
    result = evaluate_completion_gate(CompletionGateInput(run_id="run-a"))

    assert result.allowed is True
    assert result.missing_requirements == ["evidence", "verification"]
    assert result.mode == CompletionGateMode.ADVISORY


def test_completion_gate_fail_closed_blocks_missing_requirements() -> None:
    result = evaluate_completion_gate(
        CompletionGateInput(run_id="run-a", mode=CompletionGateMode.FAIL_CLOSED)
    )

    assert result.allowed is False
    assert result.missing_requirements == ["evidence", "verification"]


def test_completion_gate_blocks_unresolved_blockers() -> None:
    result = evaluate_completion_gate(
        CompletionGateInput(
            run_id="run-a",
            mode=CompletionGateMode.FAIL_CLOSED,
            evidence_count=1,
            verification_count=1,
            unresolved_blockers=["manual review required"],
        )
    )

    assert result.allowed is False
    assert result.missing_requirements == ["blockers"]


def test_completion_gate_passes_with_required_proof() -> None:
    result = evaluate_completion_gate(
        CompletionGateInput(
            run_id="run-a",
            mode=CompletionGateMode.FAIL_CLOSED,
            evidence_count=1,
            verification_count=1,
        )
    )

    assert result.allowed is True
    assert result.missing_requirements == []


def test_completion_gate_route_registered() -> None:
    paths = {route.path for route in router.routes}

    assert "/v1/completion-gates/preview" in paths or "/preview" in paths


def test_completion_gate_preview_endpoint() -> None:
    token = create_access_token("gate-user", scopes=["workflows:read"], tenant_id="tenant-a")
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

    response = client.post(
        "/v1/completion-gates/preview",
        json={
            "run_id": "run-a",
            "mode": "fail_closed",
            "evidence_count": 1,
            "verification_count": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["allowed"] is False
    assert body["missing_requirements"] == ["verification"]
