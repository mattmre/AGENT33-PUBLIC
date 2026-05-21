"""Tests for WorkflowGraphGenerator (engine/src/agent33/services/graph_generator.py).

Covers:
- Linear, branching, and diamond DAG topologies
- Node positioning / layout coordinate calculations
- Edge generation from step dependencies
- Execution-status overlay mapping
- Edge cases: single step, disconnected (parallel-only) roots
- Output schema: top-level keys, edge IDs, layout dimensions, metadata
"""

from __future__ import annotations

from typing import Any

from agent33.services.graph_generator import (
    GraphEdge,
    GraphNode,
    generate_workflow_graph,
)
from agent33.workflows.definition import (
    ExecutionMode,
    StepAction,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowStep,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LAYER_SPACING = 200
NODE_SPACING = 150
BASE_OFFSET = 80


def _step(
    step_id: str,
    action: StepAction = StepAction.RUN_COMMAND,
    depends_on: list[str] | None = None,
    name: str | None = None,
    agent: str | None = None,
    command: str | None = None,
    timeout_seconds: int | None = None,
    retry_max: int = 1,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
) -> WorkflowStep:
    kwargs: dict[str, Any] = {
        "id": step_id,
        "action": action,
        "depends_on": depends_on or [],
    }
    if name is not None:
        kwargs["name"] = name
    if agent is not None:
        kwargs["agent"] = agent
    if command is not None:
        kwargs["command"] = command
    if timeout_seconds is not None:
        kwargs["timeout_seconds"] = timeout_seconds
    if inputs is not None:
        kwargs["inputs"] = inputs
    if outputs is not None:
        kwargs["outputs"] = outputs
    if retry_max > 1:
        kwargs["retry"] = {"max_attempts": retry_max}
    return WorkflowStep(**kwargs)


def _workflow(
    steps: list[WorkflowStep],
    name: str = "test-wf",
    version: str = "1.0.0",
    mode: ExecutionMode = ExecutionMode.SEQUENTIAL,
) -> WorkflowDefinition:
    return WorkflowDefinition(
        name=name,
        version=version,
        steps=steps,
        execution=WorkflowExecution(mode=mode),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLinearDAG:
    """Three-step linear chain: a -> b -> c."""

    def test_nodes_placed_in_successive_layers(self) -> None:
        """Each step in a linear chain must land on a different x-layer
        separated by LAYER_SPACING, confirming the topological sort
        assigns one step per parallel group."""
        defn = _workflow(
            [
                _step("a"),
                _step("b", depends_on=["a"]),
                _step("c", depends_on=["b"]),
            ]
        )
        result = generate_workflow_graph(defn)

        nodes = {n["id"]: n for n in result["nodes"]}
        assert len(nodes) == 3

        # Each step occupies a distinct x layer
        assert nodes["a"]["x"] == BASE_OFFSET + 0 * LAYER_SPACING
        assert nodes["b"]["x"] == BASE_OFFSET + 1 * LAYER_SPACING
        assert nodes["c"]["x"] == BASE_OFFSET + 2 * LAYER_SPACING

        # All on the first row within their layer (y == BASE_OFFSET)
        for step_id in ("a", "b", "c"):
            assert nodes[step_id]["y"] == BASE_OFFSET

    def test_edges_chain_correctly(self) -> None:
        """Linear DAG must produce exactly two edges: a->b and b->c."""
        defn = _workflow(
            [
                _step("a"),
                _step("b", depends_on=["a"]),
                _step("c", depends_on=["b"]),
            ]
        )
        result = generate_workflow_graph(defn)

        edge_pairs = {(e["source"], e["target"]) for e in result["edges"]}
        assert edge_pairs == {("a", "b"), ("b", "c")}

    def test_edge_ids_encode_source_and_target(self) -> None:
        """Edge IDs must follow the 'edge-{source}-{target}' convention."""
        defn = _workflow(
            [
                _step("a"),
                _step("b", depends_on=["a"]),
            ]
        )
        result = generate_workflow_graph(defn)

        assert len(result["edges"]) == 1
        edge = result["edges"][0]
        assert edge["id"] == "edge-a-b"


class TestDiamondDAG:
    """Diamond DAG: start -> (left, right) -> end."""

    def _make_diamond(self) -> WorkflowDefinition:
        return _workflow(
            [
                _step("start"),
                _step("left", depends_on=["start"]),
                _step("right", depends_on=["start"]),
                _step("end", depends_on=["left", "right"]),
            ]
        )

    def test_parallel_nodes_share_x_differ_in_y(self) -> None:
        """left and right share the same x-layer but occupy distinct y slots."""
        result = generate_workflow_graph(self._make_diamond())
        nodes = {n["id"]: n for n in result["nodes"]}

        # left and right are in layer 1
        assert nodes["left"]["x"] == nodes["right"]["x"]
        assert nodes["left"]["x"] == BASE_OFFSET + 1 * LAYER_SPACING

        # They must have different y positions
        assert nodes["left"]["y"] != nodes["right"]["y"]

        # One at row 0, the other at row 1
        ys = sorted([nodes["left"]["y"], nodes["right"]["y"]])
        assert ys == [BASE_OFFSET, BASE_OFFSET + NODE_SPACING]

    def test_diamond_produces_four_edges(self) -> None:
        """Diamond has 4 dependency edges: start->left, start->right,
        left->end, right->end."""
        result = generate_workflow_graph(self._make_diamond())
        edge_pairs = {(e["source"], e["target"]) for e in result["edges"]}
        assert edge_pairs == {
            ("start", "left"),
            ("start", "right"),
            ("left", "end"),
            ("right", "end"),
        }

    def test_merge_node_is_in_last_layer(self) -> None:
        """The merge node 'end' should be in layer 2."""
        result = generate_workflow_graph(self._make_diamond())
        nodes = {n["id"]: n for n in result["nodes"]}
        assert nodes["end"]["x"] == BASE_OFFSET + 2 * LAYER_SPACING


class TestSingleStep:
    """Workflow with only one step."""

    def test_single_step_produces_one_node_no_edges(self) -> None:
        defn = _workflow([_step("only")])
        result = generate_workflow_graph(defn)

        assert len(result["nodes"]) == 1
        assert len(result["edges"]) == 0
        assert result["nodes"][0]["id"] == "only"
        assert result["nodes"][0]["x"] == BASE_OFFSET
        assert result["nodes"][0]["y"] == BASE_OFFSET


class TestDisconnectedRoots:
    """Multiple independent steps with no dependencies."""

    def test_independent_steps_land_on_same_x_layer(self) -> None:
        """All zero-dependency steps share x-layer 0, but vary in y."""
        defn = _workflow(
            [
                _step("alpha"),
                _step("bravo"),
                _step("charlie"),
            ]
        )
        result = generate_workflow_graph(defn)
        nodes = {n["id"]: n for n in result["nodes"]}

        # All share the same x-layer
        xs = {nodes[sid]["x"] for sid in ("alpha", "bravo", "charlie")}
        assert xs == {BASE_OFFSET}

        # All have distinct y values
        ys = sorted(nodes[sid]["y"] for sid in ("alpha", "bravo", "charlie"))
        assert ys == [
            BASE_OFFSET,
            BASE_OFFSET + NODE_SPACING,
            BASE_OFFSET + 2 * NODE_SPACING,
        ]

    def test_no_edges_for_independent_steps(self) -> None:
        defn = _workflow([_step("a"), _step("b")])
        result = generate_workflow_graph(defn)
        assert result["edges"] == []


class TestExecutionStatusOverlay:
    """Execution status mapping from workflow run state."""

    def test_status_overlaid_on_matching_nodes(self) -> None:
        defn = _workflow(
            [
                _step("build"),
                _step("test", depends_on=["build"]),
                _step("deploy", depends_on=["test"]),
            ]
        )
        status = {"build": "success", "test": "running", "deploy": "pending"}
        result = generate_workflow_graph(defn, execution_status=status)

        nodes = {n["id"]: n for n in result["nodes"]}
        assert nodes["build"]["status"] == "success"
        assert nodes["test"]["status"] == "running"
        assert nodes["deploy"]["status"] == "pending"

    def test_missing_status_yields_none(self) -> None:
        """Steps not mentioned in execution_status should have status=None."""
        defn = _workflow([_step("a"), _step("b", depends_on=["a"])])
        status = {"a": "success"}
        result = generate_workflow_graph(defn, execution_status=status)

        nodes = {n["id"]: n for n in result["nodes"]}
        assert nodes["a"]["status"] == "success"
        assert nodes["b"]["status"] is None

    def test_no_status_dict_yields_all_none(self) -> None:
        defn = _workflow([_step("x")])
        result = generate_workflow_graph(defn)
        assert result["nodes"][0]["status"] is None


class TestNodeMetadata:
    """Metadata extraction from step fields."""

    def test_agent_and_command_captured(self) -> None:
        defn = _workflow(
            [
                _step("s", agent="code-worker", command="echo ok"),
            ]
        )
        result = generate_workflow_graph(defn)
        meta = result["nodes"][0]["metadata"]
        assert meta["agent"] == "code-worker"
        assert meta["command"] == "echo ok"

    def test_timeout_and_retry_captured(self) -> None:
        defn = _workflow(
            [
                _step("s", timeout_seconds=120, retry_max=3),
            ]
        )
        result = generate_workflow_graph(defn)
        meta = result["nodes"][0]["metadata"]
        assert meta["timeout_seconds"] == 120
        assert meta["retry_attempts"] == 3

    def test_inputs_outputs_captured(self) -> None:
        defn = _workflow(
            [
                _step("s", inputs={"src": "repo"}, outputs={"artifact": "build.zip"}),
            ]
        )
        result = generate_workflow_graph(defn)
        meta = result["nodes"][0]["metadata"]
        assert meta["inputs"] == {"src": "repo"}
        assert meta["outputs"] == {"artifact": "build.zip"}

    def test_depends_on_captured_in_metadata(self) -> None:
        defn = _workflow(
            [
                _step("a"),
                _step("b", depends_on=["a"]),
            ]
        )
        result = generate_workflow_graph(defn)
        nodes = {n["id"]: n for n in result["nodes"]}
        assert nodes["b"]["metadata"]["depends_on"] == ["a"]
        # Root node should have no depends_on in metadata
        assert "depends_on" not in nodes["a"]["metadata"]

    def test_default_retry_not_in_metadata(self) -> None:
        """Steps with the default retry (max_attempts=1) should not add
        retry_attempts to metadata, avoiding noise."""
        defn = _workflow([_step("s")])
        result = generate_workflow_graph(defn)
        assert "retry_attempts" not in result["nodes"][0]["metadata"]

    def test_name_falls_back_to_id(self) -> None:
        """When step.name is None, the output name field should equal the step id."""
        defn = _workflow([_step("my-step")])
        result = generate_workflow_graph(defn)
        assert result["nodes"][0]["name"] == "my-step"

    def test_name_used_when_provided(self) -> None:
        defn = _workflow([_step("s", name="Build Step")])
        result = generate_workflow_graph(defn)
        assert result["nodes"][0]["name"] == "Build Step"


class TestOutputSchema:
    """Validate the top-level structure of the generated graph dict."""

    def test_top_level_keys(self) -> None:
        defn = _workflow([_step("a")])
        result = generate_workflow_graph(defn)
        assert set(result.keys()) == {
            "workflow_id",
            "workflow_version",
            "nodes",
            "edges",
            "layout",
            "metadata",
        }

    def test_workflow_identity(self) -> None:
        defn = _workflow([_step("a")], name="my-pipeline", version="2.3.1")
        result = generate_workflow_graph(defn)
        assert result["workflow_id"] == "my-pipeline"
        assert result["workflow_version"] == "2.3.1"

    def test_layout_dimensions_cover_all_nodes(self) -> None:
        """Layout width/height must be >= max node position + 200."""
        defn = _workflow(
            [
                _step("a"),
                _step("b"),
                _step("c", depends_on=["a", "b"]),
            ]
        )
        result = generate_workflow_graph(defn)

        max_x = max(n["x"] for n in result["nodes"])
        max_y = max(n["y"] for n in result["nodes"])
        assert result["layout"]["width"] == max_x + 200
        assert result["layout"]["height"] == max_y + 200

    def test_layout_type_and_spacing(self) -> None:
        defn = _workflow([_step("a")])
        result = generate_workflow_graph(defn)
        assert result["layout"]["type"] == "layered"
        assert result["layout"]["layer_spacing"] == LAYER_SPACING
        assert result["layout"]["node_spacing"] == NODE_SPACING

    def test_metadata_step_count_and_execution_mode(self) -> None:
        defn = _workflow(
            [_step("a"), _step("b", depends_on=["a"])],
            mode=ExecutionMode.DEPENDENCY_AWARE,
        )
        result = generate_workflow_graph(defn)
        assert result["metadata"]["step_count"] == 2
        assert result["metadata"]["execution_mode"] == "dependency-aware"

    def test_metadata_generated_at_is_iso_utc(self) -> None:
        defn = _workflow([_step("a")])
        result = generate_workflow_graph(defn)
        ts = result["metadata"]["generated_at"]
        assert ts.endswith("Z")
        assert "T" in ts

    def test_node_position_subfield(self) -> None:
        """Each node must have a nested 'position' dict with x/y matching
        the top-level x/y fields."""
        defn = _workflow([_step("a")])
        result = generate_workflow_graph(defn)
        node = result["nodes"][0]
        assert node["position"] == {"x": node["x"], "y": node["y"]}

    def test_action_is_step_action_value(self) -> None:
        """Action field should be the string value of StepAction enum."""
        defn = _workflow([_step("a", action=StepAction.INVOKE_AGENT)])
        result = generate_workflow_graph(defn)
        assert result["nodes"][0]["action"] == "invoke-agent"


class TestGraphNodeAndEdgeModels:
    """Direct unit tests on the GraphNode and GraphEdge data classes."""

    def test_graph_node_stores_all_fields(self) -> None:
        node = GraphNode(
            node_id="n1",
            name="Node 1",
            action="run-command",
            x=100.0,
            y=200.0,
            metadata={"agent": "qa"},
            status="success",
        )
        assert node.id == "n1"
        assert node.name == "Node 1"
        assert node.action == "run-command"
        assert node.x == 100.0
        assert node.y == 200.0
        assert node.metadata == {"agent": "qa"}
        assert node.status == "success"

    def test_graph_node_defaults(self) -> None:
        node = GraphNode(node_id="n2", name=None, action="validate", x=0.0, y=0.0)
        assert node.metadata == {}
        assert node.status is None

    def test_graph_edge_stores_source_target(self) -> None:
        edge = GraphEdge(source="a", target="b")
        assert edge.source == "a"
        assert edge.target == "b"
