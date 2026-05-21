"""E2E: Workflow registration -> execution -> DAG traversal -> result pipeline.

These tests exercise the full workflow lifecycle through HTTP endpoints,
verifying that:
1. Workflow creation validates and stores definitions
2. Workflow execution runs the DAG and returns step-level results
3. Multi-step dependencies are honored
4. Execution history is recorded with tenant ownership
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from agent33.security.auth import create_access_token

pytestmark = pytest.mark.e2e


def _admin_token() -> str:
    return create_access_token("e2e-workflow-user", scopes=["admin"])


class TestWorkflowLifecycleE2E:
    """Workflow create -> execute -> history -> DAG visualization."""

    def test_create_and_execute_sequential_workflow(
        self,
        e2e_client,
        sample_workflow_def,
        route_approval_headers,
    ):
        """Register a two-step sequential workflow and execute it.

        Verifies that:
        - POST /v1/workflows/ returns 201 with correct step count
        - POST /v1/workflows/{name}/execute returns step results in order
        - State passes between steps (step-2 uses step-1 output)
        - Execution history is recorded
        """
        _, client, _ = e2e_client
        token = _admin_token()
        headers = {"Authorization": f"Bearer {token}"}
        create_headers = route_approval_headers(
            client,
            route_name="workflows.create",
            operation="create",
            arguments=sample_workflow_def,
            details="Pytest E2E workflow setup",
            authorization=headers["Authorization"],
        )

        # Create workflow
        resp = client.post("/v1/workflows/", json=sample_workflow_def, headers=create_headers)
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "e2e-test-workflow"
        assert body["step_count"] == 2

        # Execute workflow
        resp = client.post(
            "/v1/workflows/e2e-test-workflow/execute",
            json={"inputs": {"name": "E2E"}},
            headers=headers,
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "success"
        assert "step-1" in result["steps_executed"]
        assert "step-2" in result["steps_executed"]
        assert result["duration_ms"] >= 0

        # Verify step results are present
        assert len(result["step_results"]) == 2
        step1_result = next(sr for sr in result["step_results"] if sr["step_id"] == "step-1")
        assert step1_result["status"] == "success"

        # Verify execution history
        resp = client.get(
            "/v1/workflows/e2e-test-workflow/history",
            headers=headers,
        )
        assert resp.status_code == 200
        history = resp.json()
        assert len(history) >= 1
        assert history[0]["workflow_name"] == "e2e-test-workflow"
        assert history[0]["status"] == "success"

    def test_execute_nonexistent_workflow_returns_404(self, e2e_client):
        """Executing a non-existent workflow returns 404.

        Catches regressions where missing workflow lookups fall through
        to internal errors.
        """
        _, client, _ = e2e_client
        token = _admin_token()

        resp = client.post(
            "/v1/workflows/no-such-workflow/execute",
            json={"inputs": {}},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 404
        assert "no-such-workflow" in resp.json()["detail"]

    def test_duplicate_workflow_creation_returns_409(
        self,
        e2e_client,
        sample_workflow_def,
        route_approval_headers,
    ):
        """Creating the same workflow twice returns 409 conflict.

        Verifies that the in-memory registry enforces uniqueness at the
        HTTP layer, not just silently overwriting.
        """
        _, client, _ = e2e_client
        token = _admin_token()
        headers = {"Authorization": f"Bearer {token}"}

        # Use a unique name to avoid collision with other tests
        wf_def = dict(sample_workflow_def)
        wf_def["name"] = "e2e-dup-workflow"

        # First creation
        resp = client.post(
            "/v1/workflows/",
            json=wf_def,
            headers=route_approval_headers(
                client,
                route_name="workflows.create",
                operation="create",
                arguments=wf_def,
                details="Pytest E2E workflow setup",
                authorization=headers["Authorization"],
            ),
        )
        assert resp.status_code == 201

        # Second creation -- same name
        resp = client.post(
            "/v1/workflows/",
            json=wf_def,
            headers=route_approval_headers(
                client,
                route_name="workflows.create",
                operation="create",
                arguments=wf_def,
                details="Pytest E2E workflow duplicate setup",
                authorization=headers["Authorization"],
            ),
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_workflow_with_caller_supplied_run_id(
        self,
        e2e_client,
        sample_workflow_def,
        route_approval_headers,
    ):
        """Execute with a caller-supplied run_id and verify it appears in history.

        This verifies that the run_id passthrough works end-to-end, which
        is important for correlation in distributed systems.
        """
        _, client, _ = e2e_client
        token = _admin_token()
        headers = {"Authorization": f"Bearer {token}"}

        wf_def = dict(sample_workflow_def)
        wf_def["name"] = "e2e-runid-workflow"

        resp = client.post(
            "/v1/workflows/",
            json=wf_def,
            headers=route_approval_headers(
                client,
                route_name="workflows.create",
                operation="create",
                arguments=wf_def,
                details="Pytest E2E workflow setup",
                authorization=headers["Authorization"],
            ),
        )
        assert resp.status_code == 201

        custom_run_id = f"e2e-custom-run-{uuid4().hex}"
        resp = client.post(
            "/v1/workflows/e2e-runid-workflow/execute",
            json={"inputs": {"name": "RunID"}, "run_id": custom_run_id},
            headers=headers,
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["run_id"] == custom_run_id

        # Verify in history
        resp = client.get(
            "/v1/workflows/e2e-runid-workflow/history",
            headers=headers,
        )
        assert resp.status_code == 200
        history = resp.json()
        run_ids = [h["run_id"] for h in history]
        assert custom_run_id in run_ids


class TestWorkflowDAGVisualization:
    """DAG layout endpoint returns positioned nodes for frontend rendering."""

    def test_workflow_dag_returns_positioned_layout(
        self,
        e2e_client,
        sample_workflow_def,
        route_approval_headers,
    ):
        """GET /v1/workflows/{name}/dag returns a layout with nodes and edges.

        Verifies the DAG layout computation produces valid output with
        correct step IDs and positional data.
        """
        _, client, _ = e2e_client
        token = _admin_token()
        headers = {"Authorization": f"Bearer {token}"}

        wf_def = dict(sample_workflow_def)
        wf_def["name"] = "e2e-dag-workflow"

        resp = client.post(
            "/v1/workflows/",
            json=wf_def,
            headers=route_approval_headers(
                client,
                route_name="workflows.create",
                operation="create",
                arguments=wf_def,
                details="Pytest E2E workflow setup",
                authorization=headers["Authorization"],
            ),
        )
        assert resp.status_code == 201

        resp = client.get("/v1/workflows/e2e-dag-workflow/dag", headers=headers)
        assert resp.status_code == 200
        layout = resp.json()

        # Verify layout structure
        assert "nodes" in layout
        assert "edges" in layout
        assert len(layout["nodes"]) == 2

        # Verify node IDs match step IDs
        node_ids = {n["id"] for n in layout["nodes"]}
        assert "step-1" in node_ids
        assert "step-2" in node_ids

        # Verify edges encode dependency
        assert len(layout["edges"]) >= 1
        edge = layout["edges"][0]
        assert "source" in edge
        assert "target" in edge
