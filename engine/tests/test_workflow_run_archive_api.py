"""API tests for durable workflow run archives and replay fallbacks."""

from __future__ import annotations

import contextlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes import workflows
from agent33.api.routes.workflow_sse import stream_workflow_events
from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.workflows.executor import StepResult, WorkflowResult, WorkflowStatus
from agent33.workflows.run_archive import WorkflowRunArchiveService
from agent33.workflows.ws_manager import WorkflowWSManager


@pytest.fixture(autouse=True)
def clear_workflow_archive_state() -> None:
    """Reset workflow state, live transport, and archive wiring between tests."""
    from agent33.security import auth

    def _reset() -> None:
        workflows.reset_workflow_state()
        if workflows._scheduler is not None:
            with contextlib.suppress(RuntimeError):
                workflows._scheduler.stop()
            workflows._scheduler = None
        workflows.set_ws_manager(None)
        workflows.set_workflow_run_archive_service(None)
        auth._api_keys.clear()
        app.state.ws_manager = None
        app.state.workflow_run_archive_service = None

    _reset()
    yield
    _reset()


def _client(scopes: list[str], *, tenant_id: str = "") -> TestClient:
    token = create_access_token("workflow-archive-user", scopes=scopes, tenant_id=tenant_id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def _install_archive(tmp_path) -> tuple[WorkflowRunArchiveService, WorkflowWSManager]:
    archive = WorkflowRunArchiveService(tmp_path / "workflow-runs")
    manager = WorkflowWSManager(heartbeat_interval_seconds=60, archive_service=archive)
    app.state.workflow_run_archive_service = archive
    app.state.ws_manager = manager
    workflows.set_workflow_run_archive_service(archive)
    workflows.set_ws_manager(manager)
    return archive, manager


def _seed_workflow(
    client: TestClient,
    workflow_name: str,
    route_approval_headers,
) -> None:
    payload = {
        "name": workflow_name,
        "version": "1.0.0",
        "description": "Workflow archive test",
        "steps": [
            {
                "id": "step-a",
                "action": "transform",
                "transform": "inputs",
            }
        ],
        "execution": {"mode": "sequential"},
    }
    response = client.post(
        "/v1/workflows/",
        json=payload,
        headers=route_approval_headers(
            client,
            route_name="workflows.create",
            operation="create",
            arguments=payload,
            details="Pytest workflow archive setup",
        ),
    )
    assert response.status_code == 201


async def _read_all_sse_chunks(response) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    async for raw_chunk in response.body_iterator:
        chunk = raw_chunk.decode() if isinstance(raw_chunk, bytes) else raw_chunk
        chunks.append(json.loads(chunk.split("data: ", maxsplit=1)[1].strip()))
    return chunks


def _archived_request(headers: dict[str, str] | None = None) -> SimpleNamespace:
    state = SimpleNamespace(
        ws_manager=None,
        user=SimpleNamespace(
            sub="workflow-archive-user",
            scopes=["workflows:read"],
            tenant_id="",
        ),
    )
    return SimpleNamespace(
        app=SimpleNamespace(state=state),
        state=state,
        headers=headers or {},
        is_disconnected=AsyncMock(return_value=False),
    )


def test_archived_run_detail_and_events_survive_live_state_reset(
    tmp_path,
    route_approval_headers,
) -> None:
    _install_archive(tmp_path)
    client = _client(["workflows:read", "workflows:write", "workflows:execute"])
    workflow_name = "archive-detail-workflow"
    run_id = "archive-detail-run"
    _seed_workflow(client, workflow_name, route_approval_headers)

    execute_response = client.post(
        f"/v1/workflows/{workflow_name}/execute",
        json={"inputs": {"value": 42}, "run_id": run_id},
    )
    assert execute_response.status_code == 200

    detail_response = client.get(f"/v1/workflows/runs/{run_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["run"]["run_id"] == run_id
    assert detail["history"]["run_id"] == run_id
    assert detail["result"]["workflow_name"] == workflow_name
    assert [event["type"] for event in detail["events"]] == [
        "workflow_started",
        "step_started",
        "step_completed",
        "workflow_completed",
    ]

    workflows.set_ws_manager(None)
    app.state.ws_manager = None

    events_response = client.get(f"/v1/workflows/runs/{run_id}/events")
    assert events_response.status_code == 200
    assert [event["type"] for event in events_response.json()] == [
        "workflow_started",
        "step_started",
        "step_completed",
        "workflow_completed",
    ]


@pytest.mark.asyncio
async def test_archived_sse_falls_back_when_live_manager_is_gone(
    tmp_path,
    route_approval_headers,
) -> None:
    _install_archive(tmp_path)
    client = _client(["workflows:read", "workflows:write", "workflows:execute"])
    workflow_name = "archive-sse-workflow"
    run_id = "archive-sse-run"
    _seed_workflow(client, workflow_name, route_approval_headers)

    execute_response = client.post(
        f"/v1/workflows/{workflow_name}/execute",
        json={"inputs": {"value": 7}, "run_id": run_id},
    )
    assert execute_response.status_code == 200

    workflows.set_ws_manager(None)
    app.state.ws_manager = None

    request = _archived_request()
    response = await stream_workflow_events(run_id, request)
    chunks = await _read_all_sse_chunks(response)

    assert chunks[0]["type"] == "sync"
    assert chunks[0]["data"]["terminal"] is True
    assert chunks[0]["data"]["last_event_type"] == "workflow_completed"
    assert [chunk["type"] for chunk in chunks[1:]] == [
        "workflow_started",
        "step_started",
        "step_completed",
        "workflow_completed",
    ]


def test_archived_artifact_routes_return_manifest_and_content(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    route_approval_headers,
) -> None:
    _install_archive(tmp_path)
    client = _client(["workflows:read", "workflows:write", "workflows:execute"])
    workflow_name = "archive-artifact-workflow"
    run_id = "archive-artifact-run"
    _seed_workflow(client, workflow_name, route_approval_headers)

    async def _fake_execute(self, inputs):  # noqa: ANN001, ARG001
        return WorkflowResult(
            outputs={"summary": "done"},
            steps_executed=["step-a"],
            step_results=[
                StepResult(
                    step_id="step-a",
                    status="success",
                    outputs={
                        "artifacts": [
                            {
                                "mime_type": "text/html",
                                "data": "<div>ok</div>",
                                "metadata": {"filename": "report.html"},
                            }
                        ]
                    },
                    duration_ms=4.2,
                )
            ],
            duration_ms=4.2,
            status=WorkflowStatus.SUCCESS,
        )

    monkeypatch.setattr("agent33.workflows.executor.WorkflowExecutor.execute", _fake_execute)

    execute_response = client.post(
        f"/v1/workflows/{workflow_name}/execute",
        json={"inputs": {"value": 11}, "run_id": run_id},
    )
    assert execute_response.status_code == 200

    artifacts_response = client.get(f"/v1/workflows/runs/{run_id}/artifacts")
    assert artifacts_response.status_code == 200
    artifacts = artifacts_response.json()
    assert len(artifacts) == 1
    assert artifacts[0]["name"] == "report.html"

    artifact_response = client.get(
        f"/v1/workflows/runs/{run_id}/artifacts/{artifacts[0]['relative_path']}"
    )
    assert artifact_response.status_code == 200
    assert artifact_response.json()["content"] == "<div>ok</div>"


def test_visualization_uses_archived_run_when_history_is_cleared(
    tmp_path,
    route_approval_headers,
) -> None:
    _install_archive(tmp_path)
    client = _client(["workflows:read", "workflows:write", "workflows:execute"])
    workflow_name = "archive-viz-workflow"
    run_id = "archive-viz-run"
    _seed_workflow(client, workflow_name, route_approval_headers)

    execute_response = client.post(
        f"/v1/workflows/{workflow_name}/execute",
        json={"inputs": {"value": 3}, "run_id": run_id},
    )
    assert execute_response.status_code == 200

    workflows.get_execution_history().clear()
    workflows.set_ws_manager(None)
    app.state.ws_manager = None

    response = client.get(f"/v1/visualizations/workflows/{workflow_name}/graph?run_id={run_id}")
    assert response.status_code == 200
    payload = response.json()
    node_statuses = {node["id"]: node.get("status") for node in payload["nodes"]}
    assert node_statuses["step-a"] == "success"


def test_operations_hub_workflow_detail_uses_archived_actions(
    tmp_path,
    route_approval_headers,
) -> None:
    _install_archive(tmp_path)
    client = _client(["workflows:read", "workflows:write", "workflows:execute"])
    workflow_name = "archive-ops-workflow"
    run_id = "archive-ops-run"
    _seed_workflow(client, workflow_name, route_approval_headers)

    execute_response = client.post(
        f"/v1/workflows/{workflow_name}/execute",
        json={"inputs": {"value": 5}, "run_id": run_id},
    )
    assert execute_response.status_code == 200

    workflows.set_ws_manager(None)
    app.state.ws_manager = None

    response = client.get(f"/v1/operations/processes/workflow:{run_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["event_count"] == 4
    assert payload["actions"] == [
        {
            "step_id": "step-a",
            "action_count": 2,
            "completed_at": payload["actions"][0]["completed_at"],
        }
    ]
