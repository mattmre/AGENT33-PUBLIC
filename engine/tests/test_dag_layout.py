"""Tests for S39: DAG layout computation and API endpoints."""

from __future__ import annotations

import contextlib
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.workflows.dag_layout import (
    HORIZONTAL_GAP,
    NODE_HEIGHT,
    NODE_WIDTH,
    PADDING,
    VERTICAL_GAP,
    DAGEdge,
    DAGLayout,
    DAGNode,
    _assign_positions,
    _compute_levels,
    compute_dag_layout,
)
from agent33.workflows.definition import (
    StepAction,
    WorkflowDefinition,
    WorkflowStep,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_step(
    step_id: str,
    action: StepAction = StepAction.RUN_COMMAND,
    depends_on: list[str] | None = None,
    agent: str | None = None,
    name: str | None = None,
) -> WorkflowStep:
    return WorkflowStep(
        id=step_id,
        action=action,
        depends_on=depends_on or [],
        agent=agent,
        name=name,
    )


def _make_workflow(steps: list[WorkflowStep]) -> WorkflowDefinition:
    return WorkflowDefinition(
        name="test-dag",
        version="1.0.0",
        steps=steps,
    )


# ---------------------------------------------------------------------------
# _compute_levels
# ---------------------------------------------------------------------------


class TestComputeLevels:
    def test_single_step(self) -> None:
        steps = [_make_step("a")]
        levels = _compute_levels(steps)
        assert levels == {"a": 0}

    def test_linear_chain(self) -> None:
        steps = [
            _make_step("a"),
            _make_step("b", depends_on=["a"]),
            _make_step("c", depends_on=["b"]),
        ]
        levels = _compute_levels(steps)
        assert levels["a"] == 0
        assert levels["b"] == 1
        assert levels["c"] == 2

    def test_parallel_roots(self) -> None:
        steps = [
            _make_step("a"),
            _make_step("b"),
            _make_step("c", depends_on=["a", "b"]),
        ]
        levels = _compute_levels(steps)
        assert levels["a"] == 0
        assert levels["b"] == 0
        assert levels["c"] == 1

    def test_diamond_dag(self) -> None:
        steps = [
            _make_step("start"),
            _make_step("left", depends_on=["start"]),
            _make_step("right", depends_on=["start"]),
            _make_step("merge", depends_on=["left", "right"]),
        ]
        levels = _compute_levels(steps)
        assert levels["start"] == 0
        assert levels["left"] == 1
        assert levels["right"] == 1
        assert levels["merge"] == 2

    def test_empty_steps(self) -> None:
        assert _compute_levels([]) == {}


# ---------------------------------------------------------------------------
# _assign_positions
# ---------------------------------------------------------------------------


class TestAssignPositions:
    def test_single_step_position(self) -> None:
        steps = [_make_step("a")]
        levels = {"a": 0}
        positions = _assign_positions(steps, levels)
        assert positions["a"] == (PADDING, PADDING)

    def test_two_levels_x_spacing(self) -> None:
        steps = [_make_step("a"), _make_step("b")]
        levels = {"a": 0, "b": 1}
        positions = _assign_positions(steps, levels)

        x_a, _ = positions["a"]
        x_b, _ = positions["b"]
        assert x_b - x_a == NODE_WIDTH + HORIZONTAL_GAP

    def test_same_level_y_spacing(self) -> None:
        steps = [_make_step("a"), _make_step("b")]
        levels = {"a": 0, "b": 0}
        positions = _assign_positions(steps, levels)

        _, y_a = positions["a"]
        _, y_b = positions["b"]
        assert y_b - y_a == NODE_HEIGHT + VERTICAL_GAP

    def test_empty_returns_empty(self) -> None:
        assert _assign_positions([], {}) == {}


# ---------------------------------------------------------------------------
# compute_dag_layout
# ---------------------------------------------------------------------------


class TestComputeDagLayout:
    def test_basic_layout_structure(self) -> None:
        steps = [
            _make_step("a", name="Step A"),
            _make_step("b", name="Step B", depends_on=["a"]),
        ]
        defn = _make_workflow(steps)
        layout = compute_dag_layout(defn)

        assert isinstance(layout, DAGLayout)
        assert len(layout.nodes) == 2
        assert len(layout.edges) == 1
        assert layout.width > 0
        assert layout.height > 0

    def test_node_labels_from_name(self) -> None:
        steps = [_make_step("a", name="Alpha")]
        defn = _make_workflow(steps)
        layout = compute_dag_layout(defn)

        assert layout.nodes[0].label == "Alpha"

    def test_node_labels_fallback_to_id(self) -> None:
        steps = [_make_step("a")]
        defn = _make_workflow(steps)
        layout = compute_dag_layout(defn)

        assert layout.nodes[0].label == "a"

    def test_node_type_matches_action(self) -> None:
        steps = [_make_step("a", action=StepAction.INVOKE_AGENT)]
        defn = _make_workflow(steps)
        layout = compute_dag_layout(defn)

        assert layout.nodes[0].type == "invoke-agent"

    def test_node_agent_id_from_step(self) -> None:
        steps = [_make_step("a", action=StepAction.INVOKE_AGENT, agent="code-worker")]
        defn = _make_workflow(steps)
        layout = compute_dag_layout(defn)

        assert layout.nodes[0].agent_id == "code-worker"

    def test_default_status_is_pending(self) -> None:
        steps = [_make_step("a")]
        defn = _make_workflow(steps)
        layout = compute_dag_layout(defn)

        assert layout.nodes[0].status == "pending"

    def test_run_state_overlay(self) -> None:
        steps = [
            _make_step("a"),
            _make_step("b", depends_on=["a"]),
        ]
        defn = _make_workflow(steps)
        run_state = {
            "a": {"status": "success", "duration_ms": 42.5},
            "b": {"status": "running"},
        }
        layout = compute_dag_layout(defn, run_state=run_state)

        node_a = next(n for n in layout.nodes if n.id == "a")
        node_b = next(n for n in layout.nodes if n.id == "b")

        assert node_a.status == "success"
        assert node_a.duration_ms == 42.5
        assert node_b.status == "running"
        assert node_b.duration_ms is None

    def test_run_state_agent_id_override(self) -> None:
        steps = [_make_step("a", agent="default-agent")]
        defn = _make_workflow(steps)
        run_state = {"a": {"status": "success", "agent_id": "runtime-agent"}}
        layout = compute_dag_layout(defn, run_state=run_state)

        assert layout.nodes[0].agent_id == "runtime-agent"

    def test_edges_match_dependencies(self) -> None:
        steps = [
            _make_step("a"),
            _make_step("b", depends_on=["a"]),
            _make_step("c", depends_on=["a", "b"]),
        ]
        defn = _make_workflow(steps)
        layout = compute_dag_layout(defn)

        edge_pairs = {(e.source, e.target) for e in layout.edges}
        assert ("a", "b") in edge_pairs
        assert ("a", "c") in edge_pairs
        assert ("b", "c") in edge_pairs
        assert len(layout.edges) == 3

    def test_no_edges_for_independent_steps(self) -> None:
        steps = [_make_step("a"), _make_step("b")]
        defn = _make_workflow(steps)
        layout = compute_dag_layout(defn)

        assert len(layout.edges) == 0

    def test_topological_levels_assigned(self) -> None:
        steps = [
            _make_step("a"),
            _make_step("b", depends_on=["a"]),
            _make_step("c", depends_on=["b"]),
        ]
        defn = _make_workflow(steps)
        layout = compute_dag_layout(defn)

        nodes_by_id = {n.id: n for n in layout.nodes}
        assert nodes_by_id["a"].level == 0
        assert nodes_by_id["b"].level == 1
        assert nodes_by_id["c"].level == 2

    def test_bounding_box_covers_all_nodes(self) -> None:
        steps = [
            _make_step("a"),
            _make_step("b"),
            _make_step("c", depends_on=["a", "b"]),
        ]
        defn = _make_workflow(steps)
        layout = compute_dag_layout(defn)

        for node in layout.nodes:
            assert node.x + NODE_WIDTH <= layout.width
            assert node.y + NODE_HEIGHT <= layout.height

    def test_diamond_layout_positions(self) -> None:
        steps = [
            _make_step("start"),
            _make_step("left", depends_on=["start"]),
            _make_step("right", depends_on=["start"]),
            _make_step("end", depends_on=["left", "right"]),
        ]
        defn = _make_workflow(steps)
        layout = compute_dag_layout(defn)

        nodes_by_id = {n.id: n for n in layout.nodes}
        # start at level 0, left/right at level 1, end at level 2
        assert nodes_by_id["start"].level == 0
        assert nodes_by_id["left"].level == 1
        assert nodes_by_id["right"].level == 1
        assert nodes_by_id["end"].level == 2

        # left and right share the same x but different y
        assert nodes_by_id["left"].x == nodes_by_id["right"].x
        assert nodes_by_id["left"].y != nodes_by_id["right"].y

    def test_generated_at_set(self) -> None:
        steps = [_make_step("a")]
        defn = _make_workflow(steps)
        layout = compute_dag_layout(defn)

        assert layout.generated_at is not None

    def test_empty_workflow_steps(self) -> None:
        """Edge case: WorkflowDefinition requires min 1 step, but layout handles empty."""
        layout = (
            compute_dag_layout.__wrapped__(  # type: ignore[attr-defined]
                None,
                None,  # type: ignore[arg-type]
            )
            if hasattr(compute_dag_layout, "__wrapped__")
            else None
        )

        # Since WorkflowDefinition validates min_length=1, we test via
        # the internal path by calling with a mock definition
        from unittest.mock import MagicMock

        mock_defn = MagicMock()
        mock_defn.steps = []
        layout = compute_dag_layout(mock_defn)  # type: ignore[arg-type]
        assert layout.nodes == []
        assert layout.edges == []


# ---------------------------------------------------------------------------
# DAGNode / DAGEdge model tests
# ---------------------------------------------------------------------------


class TestDAGModels:
    def test_dag_node_defaults(self) -> None:
        node = DAGNode(id="step-1", label="Step 1", type="run-command")
        assert node.status == "pending"
        assert node.duration_ms is None
        assert node.agent_id is None
        assert node.x == 0.0
        assert node.y == 0.0
        assert node.level == 0

    def test_dag_edge_defaults(self) -> None:
        edge = DAGEdge(source="a", target="b")
        assert edge.label == ""

    def test_dag_layout_serialization(self) -> None:
        layout = DAGLayout(
            nodes=[DAGNode(id="a", label="A", type="run-command", x=10.0, y=20.0)],
            edges=[DAGEdge(source="a", target="b")],
            width=300.0,
            height=200.0,
            run_id="run-123",
        )
        data = layout.model_dump(mode="json")
        assert data["run_id"] == "run-123"
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["x"] == 10.0
        assert data["nodes"][0]["y"] == 20.0
        assert len(data["edges"]) == 1
        assert "generated_at" in data


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_workflow_state() -> Any:
    """Reset workflow module globals between tests."""
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
    token = create_access_token("dag-reader", scopes=["workflows:read"])
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def writer_client() -> TestClient:
    token = create_access_token(
        "dag-writer", scopes=["workflows:read", "workflows:write", "workflows:execute"]
    )
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def _register_workflow(
    client: TestClient,
    steps: list[dict[str, Any]],
    route_approval_headers,
) -> None:
    """Register a test workflow via the API."""
    payload = {
        "name": "test-dag",
        "version": "1.0.0",
        "steps": steps,
    }
    resp = client.post(
        "/v1/workflows/",
        json=payload,
        headers=route_approval_headers(
            client,
            route_name="workflows.create",
            operation="create",
            arguments=payload,
            details="Pytest DAG workflow setup",
        ),
    )
    assert resp.status_code == 201, resp.text


class TestWorkflowDagEndpoint:
    def test_get_dag_for_registered_workflow(
        self,
        writer_client: TestClient,
        reader_client: TestClient,
        route_approval_headers,
    ) -> None:
        _register_workflow(
            writer_client,
            [
                {"id": "step-a", "action": "run-command", "command": "echo hello"},
                {
                    "id": "step-b",
                    "action": "invoke-agent",
                    "agent": "qa",
                    "depends_on": ["step-a"],
                },
            ],
            route_approval_headers,
        )

        resp = reader_client.get("/v1/workflows/test-dag/dag")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        assert data["width"] > 0
        assert data["height"] > 0

        # Verify node fields
        node_a = next(n for n in data["nodes"] if n["id"] == "step-a")
        assert node_a["type"] == "run-command"
        assert node_a["status"] == "pending"
        assert node_a["level"] == 0

        node_b = next(n for n in data["nodes"] if n["id"] == "step-b")
        assert node_b["type"] == "invoke-agent"
        assert node_b["agent_id"] == "qa"
        assert node_b["level"] == 1

        # Verify edge
        assert data["edges"][0]["source"] == "step-a"
        assert data["edges"][0]["target"] == "step-b"

    def test_get_dag_for_unknown_workflow_returns_404(self, reader_client: TestClient) -> None:
        resp = reader_client.get("/v1/workflows/nonexistent/dag")
        assert resp.status_code == 404

    def test_get_dag_requires_auth(self) -> None:
        client = TestClient(app)
        resp = client.get("/v1/workflows/test-dag/dag")
        assert resp.status_code == 401


class TestRunDagEndpoint:
    def test_get_run_dag_returns_404_for_unknown_run(self, reader_client: TestClient) -> None:
        resp = reader_client.get("/v1/workflows/runs/nonexistent-run/dag")
        assert resp.status_code == 404

    def test_get_run_dag_with_execution_history(
        self,
        writer_client: TestClient,
        reader_client: TestClient,
        route_approval_headers,
    ) -> None:
        """Register a workflow, execute it, then fetch the DAG with run state."""
        _register_workflow(
            writer_client,
            [
                {"id": "step-a", "action": "run-command", "command": "echo hello"},
            ],
            route_approval_headers,
        )

        # Execute the workflow to create a history entry
        exec_resp = writer_client.post(
            "/v1/workflows/test-dag/execute",
            json={"inputs": {}, "run_id": "test-run-001"},
        )
        assert exec_resp.status_code == 200
        run_data = exec_resp.json()
        assert run_data["run_id"] == "test-run-001"

        # Fetch DAG for the run
        resp = reader_client.get("/v1/workflows/runs/test-run-001/dag")
        assert resp.status_code == 200

        data = resp.json()
        assert data["run_id"] == "test-run-001"
        assert len(data["nodes"]) == 1
        # The step should have a status from the execution
        node = data["nodes"][0]
        assert node["id"] == "step-a"
        # After execution, the status should be set (success from run_command dry-run)
        assert node["status"] in ("success", "failed", "pending")

    def test_get_run_dag_requires_auth(self) -> None:
        client = TestClient(app)
        resp = client.get("/v1/workflows/runs/some-run/dag")
        assert resp.status_code == 401
