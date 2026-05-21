"""Tests for workflow visualization API."""

from __future__ import annotations

import asyncio
import contextlib
import uuid

import pytest
from fastapi.testclient import TestClient

from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.workflows.ws_manager import WorkflowWSManager


@pytest.fixture(autouse=True)
def clear_workflow_state():
    """Clear workflow registry, history, and scheduler between tests."""
    from agent33.api.routes import workflows

    def _reset() -> None:
        workflows.reset_workflow_state()
        if workflows._scheduler is not None:
            with contextlib.suppress(RuntimeError):
                workflows._scheduler.stop()
            workflows._scheduler = None
        workflows.set_ws_manager(None)
        app.state.ws_manager = None

    _reset()
    yield
    _reset()


@pytest.fixture
def reader_client() -> TestClient:
    """Client with only read scope."""
    token = create_access_token("reader-user", scopes=["workflows:read"])
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def tenant_a_reader_client() -> TestClient:
    token = create_access_token(
        "tenant-a-reader",
        scopes=["workflows:read"],
        tenant_id="tenant-a",
    )
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def tenant_b_reader_client() -> TestClient:
    token = create_access_token(
        "tenant-b-reader",
        scopes=["workflows:read"],
        tenant_id="tenant-b",
    )
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def writer_client() -> TestClient:
    """Client with write scope."""
    token = create_access_token(
        "writer-user",
        scopes=["workflows:read", "workflows:write", "workflows:execute"],
    )
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def no_scope_client() -> TestClient:
    """Client with no scopes."""
    token = create_access_token("no-scope-user", scopes=[])
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def simple_workflow(writer_client: TestClient, route_approval_headers) -> str:
    """Create a simple linear workflow and return its name."""
    workflow_name = f"test-viz-{uuid.uuid4().hex[:8]}"
    payload = {
        "name": workflow_name,
        "version": "1.0.0",
        "description": "Simple workflow for viz testing",
        "steps": [
            {
                "id": "step-1",
                "name": "First Step",
                "action": "transform",
                "transform": "inputs",
            },
            {
                "id": "step-2",
                "name": "Second Step",
                "action": "transform",
                "transform": "step-1",
                "depends_on": ["step-1"],
            },
        ],
        "execution": {"mode": "dependency-aware"},
    }
    resp = writer_client.post(
        "/v1/workflows/",
        json=payload,
        headers=route_approval_headers(
            writer_client,
            route_name="workflows.create",
            operation="create",
            arguments=payload,
            details="Pytest visualization workflow setup",
        ),
    )
    assert resp.status_code == 201
    return workflow_name


@pytest.fixture
def dag_workflow(writer_client: TestClient, route_approval_headers) -> str:
    """Create a DAG workflow with parallel branches and return its name."""
    workflow_name = f"dag-viz-{uuid.uuid4().hex[:8]}"
    payload = {
        "name": workflow_name,
        "version": "1.0.0",
        "description": "DAG workflow with parallel branches",
        "steps": [
            {
                "id": "start",
                "name": "Start",
                "action": "transform",
                "transform": "inputs",
            },
            {
                "id": "branch-a",
                "name": "Branch A",
                "action": "transform",
                "transform": "start",
                "depends_on": ["start"],
            },
            {
                "id": "branch-b",
                "name": "Branch B",
                "action": "transform",
                "transform": "start",
                "depends_on": ["start"],
            },
            {
                "id": "merge",
                "name": "Merge",
                "action": "transform",
                "transform": "branch-a",
                "depends_on": ["branch-a", "branch-b"],
            },
        ],
        "execution": {"mode": "dependency-aware"},
    }
    resp = writer_client.post(
        "/v1/workflows/",
        json=payload,
        headers=route_approval_headers(
            writer_client,
            route_name="workflows.create",
            operation="create",
            arguments=payload,
            details="Pytest visualization workflow setup",
        ),
    )
    assert resp.status_code == 201
    return workflow_name


@pytest.fixture
def cyclic_workflow(writer_client: TestClient, route_approval_headers) -> str:
    """Create a workflow with a cycle (for testing cycle detection)."""
    workflow_name = f"cyclic-viz-{uuid.uuid4().hex[:8]}"
    payload = {
        "name": workflow_name,
        "version": "1.0.0",
        "description": "Workflow with cycle",
        "steps": [
            {
                "id": "step-a",
                "action": "transform",
                "transform": "inputs",
                "depends_on": ["step-c"],
            },
            {
                "id": "step-b",
                "action": "transform",
                "transform": "step-a",
                "depends_on": ["step-a"],
            },
            {
                "id": "step-c",
                "action": "transform",
                "transform": "step-b",
                "depends_on": ["step-b"],
            },
        ],
        "execution": {"mode": "dependency-aware"},
    }
    resp = writer_client.post(
        "/v1/workflows/",
        json=payload,
        headers=route_approval_headers(
            writer_client,
            route_name="workflows.create",
            operation="create",
            arguments=payload,
            details="Pytest visualization workflow setup",
        ),
    )
    assert resp.status_code == 201
    return workflow_name


# -- Happy path tests --------------------------------------------------------


class TestWorkflowGraphGeneration:
    """Tests for successful graph generation."""

    def test_get_simple_workflow_graph(
        self, reader_client: TestClient, simple_workflow: str
    ) -> None:
        """Simple workflow should return graph with correct structure."""
        resp = reader_client.get(f"/v1/visualizations/workflows/{simple_workflow}/graph")
        assert resp.status_code == 200

        data = resp.json()
        assert data["workflow_id"] == simple_workflow
        assert data["workflow_version"] == "1.0.0"
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1

        # Verify node structure
        node_ids = {node["id"] for node in data["nodes"]}
        assert node_ids == {"step-1", "step-2"}

        # Verify edge structure
        edge = data["edges"][0]
        assert edge["source"] == "step-1"
        assert edge["target"] == "step-2"

        # Verify layout metadata
        assert data["layout"]["type"] == "layered"
        assert data["layout"]["width"] > 0
        assert data["layout"]["height"] > 0

    def test_get_dag_workflow_graph(self, reader_client: TestClient, dag_workflow: str) -> None:
        """DAG workflow should have correct parallel structure."""
        resp = reader_client.get(f"/v1/visualizations/workflows/{dag_workflow}/graph")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data["nodes"]) == 4
        assert len(data["edges"]) == 4

        # Verify all nodes present
        node_ids = {node["id"] for node in data["nodes"]}
        assert node_ids == {"start", "branch-a", "branch-b", "merge"}

        # Verify edges
        edges = {(e["source"], e["target"]) for e in data["edges"]}
        expected_edges = {
            ("start", "branch-a"),
            ("start", "branch-b"),
            ("branch-a", "merge"),
            ("branch-b", "merge"),
        }
        assert edges == expected_edges

        # Verify layout has proper layers
        nodes_by_id = {n["id"]: n for n in data["nodes"]}

        # start should be in an earlier layer than the branches.
        assert nodes_by_id["start"]["x"] < nodes_by_id["branch-a"]["x"]

        # branch-a and branch-b should be at same x (layer 1)
        assert nodes_by_id["branch-a"]["x"] == nodes_by_id["branch-b"]["x"]

        # merge should be at later x (layer 2)
        assert nodes_by_id["merge"]["x"] > nodes_by_id["branch-a"]["x"]

    def test_graph_with_execution_status_overlay(
        self, writer_client: TestClient, simple_workflow: str
    ) -> None:
        """Graph should overlay status from latest execution."""
        # Execute workflow first
        exec_resp = writer_client.post(
            f"/v1/workflows/{simple_workflow}/execute",
            json={"inputs": {"value": 42}},
        )
        assert exec_resp.status_code == 200

        # Get graph with status overlay
        resp = writer_client.get(f"/v1/visualizations/workflows/{simple_workflow}/graph")
        assert resp.status_code == 200

        data = resp.json()
        nodes = data["nodes"]

        # All steps should have success status
        for node in nodes:
            assert node["status"] == "success"

    def test_graph_node_metadata(self, reader_client: TestClient, dag_workflow: str) -> None:
        """Nodes should include useful metadata."""
        resp = reader_client.get(f"/v1/visualizations/workflows/{dag_workflow}/graph")
        assert resp.status_code == 200

        data = resp.json()
        merge_node = next(n for n in data["nodes"] if n["id"] == "merge")

        # Should have depends_on in metadata
        assert "depends_on" in merge_node["metadata"]
        assert set(merge_node["metadata"]["depends_on"]) == {"branch-a", "branch-b"}


# -- Error handling tests ----------------------------------------------------


class TestWorkflowGraphErrors:
    """Tests for error conditions."""

    def test_invalid_workflow_id_format_returns_400(self, reader_client: TestClient) -> None:
        """Invalid workflow ID format should return 400."""
        resp = reader_client.get("/v1/visualizations/workflows/INVALID_ID/graph")
        assert resp.status_code == 400
        assert "invalid workflow identifier format" in resp.json()["detail"].lower()

    def test_404_for_nonexistent_workflow(self, reader_client: TestClient) -> None:
        """Should return 404 for workflow that doesn't exist."""
        resp = reader_client.get("/v1/visualizations/workflows/nonexistent/graph")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_cyclic_workflow_returns_422(
        self, reader_client: TestClient, cyclic_workflow: str
    ) -> None:
        """Cyclic workflow should surface explicit validation error."""
        resp = reader_client.get(f"/v1/visualizations/workflows/{cyclic_workflow}/graph")
        assert resp.status_code == 422
        assert "cycle detected" in resp.json()["detail"].lower()


# -- Authorization tests -----------------------------------------------------


class TestWorkflowGraphAuthorization:
    """Tests for scope enforcement."""

    def test_requires_workflows_read_scope(
        self, no_scope_client: TestClient, simple_workflow: str
    ) -> None:
        """Endpoint should require workflows:read scope."""
        resp = no_scope_client.get(f"/v1/visualizations/workflows/{simple_workflow}/graph")
        assert resp.status_code == 403
        assert "workflows:read" in resp.json()["detail"]

    def test_read_scope_sufficient(self, reader_client: TestClient, simple_workflow: str) -> None:
        """workflows:read scope should be sufficient."""
        resp = reader_client.get(f"/v1/visualizations/workflows/{simple_workflow}/graph")
        assert resp.status_code == 200

    def test_run_overlay_hides_other_tenant_live_runs(
        self,
        writer_client: TestClient,
        route_approval_headers,
    ) -> None:
        workflow_name = f"tenant-viz-{uuid.uuid4().hex[:8]}"
        payload = {
            "name": workflow_name,
            "version": "1.0.0",
            "steps": [{"id": "step-1", "action": "transform", "transform": "inputs"}],
            "execution": {"mode": "sequential"},
        }
        resp = writer_client.post(
            "/v1/workflows/",
            json=payload,
            headers=route_approval_headers(
                writer_client,
                route_name="workflows.create",
                operation="create",
                arguments=payload,
                details="Pytest tenant visualization setup",
            ),
        )
        assert resp.status_code == 201

        manager = WorkflowWSManager()
        asyncio.run(
            manager.register_run(
                "tenant-live-run",
                workflow_name,
                owner_subject="tenant-owner",
                tenant_id="tenant-a",
            )
        )

        from agent33.api.routes import workflows

        app.state.ws_manager = manager
        workflows.set_ws_manager(manager)

        other_tenant_token = create_access_token(
            "tenant-owner",
            scopes=["workflows:read"],
            tenant_id="tenant-b",
        )
        other_tenant_client = TestClient(
            app,
            headers={"Authorization": f"Bearer {other_tenant_token}"},
        )

        overlay_resp = other_tenant_client.get(
            f"/v1/visualizations/workflows/{workflow_name}/graph",
            params={"run_id": "tenant-live-run"},
        )

        assert overlay_resp.status_code == 404


# -- Deterministic layout tests ----------------------------------------------


class TestDeterministicLayout:
    """Tests for layout determinism and correctness."""

    def test_layout_is_deterministic(self, reader_client: TestClient, dag_workflow: str) -> None:
        """Multiple calls should return identical layout."""
        resp1 = reader_client.get(f"/v1/visualizations/workflows/{dag_workflow}/graph")
        resp2 = reader_client.get(f"/v1/visualizations/workflows/{dag_workflow}/graph")

        data1 = resp1.json()
        data2 = resp2.json()

        # Node positions should be identical
        nodes1 = {n["id"]: (n["x"], n["y"]) for n in data1["nodes"]}
        nodes2 = {n["id"]: (n["x"], n["y"]) for n in data2["nodes"]}

        assert nodes1 == nodes2

    def test_parallel_nodes_same_layer(self, reader_client: TestClient, dag_workflow: str) -> None:
        """Parallel nodes should be at same x coordinate (layer)."""
        resp = reader_client.get(f"/v1/visualizations/workflows/{dag_workflow}/graph")
        data = resp.json()

        nodes_by_id = {n["id"]: n for n in data["nodes"]}

        # branch-a and branch-b are parallel, should be at same x
        assert nodes_by_id["branch-a"]["x"] == nodes_by_id["branch-b"]["x"]

        # But different y coordinates
        assert nodes_by_id["branch-a"]["y"] != nodes_by_id["branch-b"]["y"]


# -- Integration with workflow execution -------------------------------------


class TestWorkflowExecutionIntegration:
    """Tests for integration with workflow execution system."""

    def test_no_status_overlay_before_execution(
        self, reader_client: TestClient, simple_workflow: str
    ) -> None:
        """Graph should have no status overlay if never executed."""
        resp = reader_client.get(f"/v1/visualizations/workflows/{simple_workflow}/graph")
        data = resp.json()

        # Nodes should have no status
        for node in data["nodes"]:
            assert node["status"] is None

    def test_status_overlay_updates_after_execution(
        self, writer_client: TestClient, simple_workflow: str
    ) -> None:
        """Status overlay should update after execution."""
        # Get initial graph - no status
        resp1 = writer_client.get(f"/v1/visualizations/workflows/{simple_workflow}/graph")
        data1 = resp1.json()
        assert all(n["status"] is None for n in data1["nodes"])

        # Execute workflow
        writer_client.post(
            f"/v1/workflows/{simple_workflow}/execute",
            json={"inputs": {"value": 42}},
        )

        # Get graph again - should have status
        resp2 = writer_client.get(f"/v1/visualizations/workflows/{simple_workflow}/graph")
        data2 = resp2.json()
        assert all(n["status"] == "success" for n in data2["nodes"])

    def test_status_overlay_is_filtered_by_tenant(
        self,
        simple_workflow: str,
        tenant_a_reader_client: TestClient,
        tenant_b_reader_client: TestClient,
    ) -> None:
        writer_token = create_access_token(
            "tenant-a-writer",
            scopes=["workflows:read", "workflows:write", "workflows:execute"],
            tenant_id="tenant-a",
        )
        tenant_a_writer = TestClient(
            app,
            headers={"Authorization": f"Bearer {writer_token}"},
        )

        exec_resp = tenant_a_writer.post(
            f"/v1/workflows/{simple_workflow}/execute",
            json={"inputs": {"value": 42}},
        )
        assert exec_resp.status_code == 200

        tenant_a_graph = tenant_a_reader_client.get(
            f"/v1/visualizations/workflows/{simple_workflow}/graph"
        )
        assert tenant_a_graph.status_code == 200
        assert all(node["status"] == "success" for node in tenant_a_graph.json()["nodes"])

        tenant_b_graph = tenant_b_reader_client.get(
            f"/v1/visualizations/workflows/{simple_workflow}/graph"
        )
        assert tenant_b_graph.status_code == 200
        assert all(node["status"] is None for node in tenant_b_graph.json()["nodes"])
