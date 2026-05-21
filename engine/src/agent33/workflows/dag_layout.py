"""DAG layout computation for workflow visualization.

Transforms a WorkflowDefinition into a positioned graph layout suitable
for SVG rendering. Uses the existing DAGBuilder to compute topological
levels, then assigns grid-based x/y coordinates.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from agent33.workflows.dag import DAGBuilder

if TYPE_CHECKING:
    from agent33.workflows.definition import WorkflowDefinition, WorkflowStep

# Layout constants
NODE_WIDTH = 180.0
NODE_HEIGHT = 60.0
HORIZONTAL_GAP = 100.0
VERTICAL_GAP = 80.0
PADDING = 40.0


class DAGNode(BaseModel):
    """A positioned node in the DAG visualization."""

    id: str
    label: str
    type: str  # action type: invoke-agent, run-command, etc.
    status: str = "pending"
    duration_ms: float | None = None
    agent_id: str | None = None
    x: float = 0.0
    y: float = 0.0
    level: int = 0


class DAGEdge(BaseModel):
    """A directed edge between two DAG nodes."""

    source: str
    target: str
    label: str = ""


class DAGLayout(BaseModel):
    """Complete positioned DAG layout for visualization."""

    nodes: list[DAGNode] = Field(default_factory=list)
    edges: list[DAGEdge] = Field(default_factory=list)
    width: float = 0.0
    height: float = 0.0
    run_id: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def _compute_levels(steps: list[WorkflowStep]) -> dict[str, int]:
    """Compute topological depth level for each step using DAGBuilder.

    Level 0 contains steps with no dependencies. Level N contains steps
    whose longest dependency chain has length N.
    """
    if not steps:
        return {}

    dag = DAGBuilder(steps).build()
    groups = dag.parallel_groups()

    levels: dict[str, int] = {}
    for level_idx, group in enumerate(groups):
        for step_id in group:
            levels[step_id] = level_idx

    return levels


def _assign_positions(
    steps: list[WorkflowStep],
    levels: dict[str, int],
) -> dict[str, tuple[float, float]]:
    """Assign x/y positions to steps based on their topological levels.

    X axis represents the level (left to right), Y axis separates
    nodes within the same level (top to bottom).
    """
    if not levels:
        return {}

    # Group steps by level
    level_groups: dict[int, list[str]] = defaultdict(list)
    for step_id, level in levels.items():
        level_groups[level].append(step_id)

    # Sort within each level for deterministic output
    for level in level_groups:
        level_groups[level].sort()

    positions: dict[str, tuple[float, float]] = {}
    for level, step_ids in level_groups.items():
        x = PADDING + level * (NODE_WIDTH + HORIZONTAL_GAP)
        for idx, step_id in enumerate(step_ids):
            y = PADDING + idx * (NODE_HEIGHT + VERTICAL_GAP)
            positions[step_id] = (x, y)

    return positions


def compute_dag_layout(
    definition: WorkflowDefinition,
    run_state: dict[str, Any] | None = None,
) -> DAGLayout:
    """Compute a positioned DAG layout from a workflow definition.

    Args:
        definition: The workflow definition to lay out.
        run_state: Optional mapping of step_id to run-time state dict.
            Each entry may contain ``status`` (str), ``duration_ms`` (float),
            and ``agent_id`` (str) keys to overlay live execution state.

    Returns:
        A DAGLayout with positioned nodes and edges.
    """
    steps = definition.steps
    if not steps:
        return DAGLayout()

    step_map = {s.id: s for s in steps}
    levels = _compute_levels(steps)
    positions = _assign_positions(steps, levels)
    run_state = run_state or {}

    nodes: list[DAGNode] = []
    for step in steps:
        x, y = positions.get(step.id, (0.0, 0.0))
        step_run = run_state.get(step.id, {})

        node = DAGNode(
            id=step.id,
            label=step.name or step.id,
            type=step.action.value,
            status=step_run.get("status", "pending"),
            duration_ms=step_run.get("duration_ms"),
            agent_id=step_run.get("agent_id") or step.agent,
            x=x,
            y=y,
            level=levels.get(step.id, 0),
        )
        nodes.append(node)

    edges: list[DAGEdge] = []
    for step in steps:
        for dep in step.depends_on:
            if dep in step_map:
                edges.append(DAGEdge(source=dep, target=step.id))

    # Compute bounding box
    if nodes:
        max_x = max(n.x for n in nodes) + NODE_WIDTH + PADDING
        max_y = max(n.y for n in nodes) + NODE_HEIGHT + PADDING
    else:
        max_x = 0.0
        max_y = 0.0

    return DAGLayout(
        nodes=nodes,
        edges=edges,
        width=max_x,
        height=max_y,
    )
