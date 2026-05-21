"""Graph generation service for workflow visualization."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from agent33.workflows.dag import DAGBuilder

if TYPE_CHECKING:
    from agent33.workflows.definition import WorkflowDefinition


class GraphNode:
    """Node in the workflow graph."""

    def __init__(
        self,
        node_id: str,
        name: str | None,
        action: str,
        x: float,
        y: float,
        metadata: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> None:
        self.id = node_id
        self.name = name
        self.action = action
        self.x = x
        self.y = y
        self.metadata = metadata or {}
        self.status = status


class GraphEdge:
    """Edge connecting two nodes in the workflow graph."""

    def __init__(self, source: str, target: str) -> None:
        self.source = source
        self.target = target


class WorkflowGraphGenerator:
    """Generate visual graph representation from workflow definition.

    Uses DAG-based layer layout for deterministic positioning without
    requiring external graph layout libraries.
    """

    def __init__(
        self,
        definition: WorkflowDefinition,
        execution_status: dict[str, str] | None = None,
    ) -> None:
        """Initialize graph generator.

        Args:
            definition: The workflow definition to visualize.
            execution_status: Optional mapping of step_id -> status for overlay.
        """
        self._definition = definition
        self._execution_status = execution_status or {}
        self._nodes: list[GraphNode] = []
        self._edges: list[GraphEdge] = []

    def generate(self) -> dict[str, Any]:
        """Generate the complete graph structure with nodes, edges, and layout.

        Returns:
            Dictionary containing nodes, edges, and layout metadata.

        Raises:
            CycleDetectedError: If the workflow contains cycles.
        """
        # Build DAG to get topological layers.
        dag = DAGBuilder(self._definition.steps).build()
        groups = dag.parallel_groups()

        # Generate nodes with layered layout
        self._generate_nodes(groups)

        # Generate edges from dependencies
        self._generate_edges()

        # Calculate dimensions
        max_x = max((node.x for node in self._nodes), default=0.0)
        max_y = max((node.y for node in self._nodes), default=0.0)

        return {
            "workflow_id": self._definition.name,
            "workflow_version": self._definition.version,
            "nodes": [
                {
                    "id": node.id,
                    "name": node.name or node.id,
                    "action": node.action,
                    "x": node.x,
                    "y": node.y,
                    "position": {"x": node.x, "y": node.y},
                    "metadata": node.metadata,
                    "status": node.status,
                }
                for node in self._nodes
            ],
            "edges": [
                {
                    "id": f"edge-{edge.source}-{edge.target}",
                    "source": edge.source,
                    "target": edge.target,
                }
                for edge in self._edges
            ],
            "layout": {
                "type": "layered",
                "width": max_x + 200,
                "height": max_y + 200,
                "layer_spacing": 200,
                "node_spacing": 150,
            },
            "metadata": {
                "step_count": len(self._definition.steps),
                "execution_mode": self._definition.execution.mode.value,
                "generated_at": datetime.utcnow().isoformat() + "Z",
            },
        }

    def _generate_nodes(self, groups: list[list[str]]) -> None:
        """Generate nodes with layered layout coordinates.

        Args:
            groups: Parallel execution groups from DAG (each group is one layer).
        """
        layer_spacing = 200  # Horizontal spacing between layers
        node_spacing = 150  # Vertical spacing between nodes in same layer

        step_map = {step.id: step for step in self._definition.steps}

        for layer_idx, group in enumerate(groups):
            x = 80 + (layer_idx * layer_spacing)

            for node_idx, step_id in enumerate(group):
                step = step_map[step_id]
                y = 80 + (node_idx * node_spacing)

                # Extract useful metadata
                metadata: dict[str, Any] = {}
                if step.agent:
                    metadata["agent"] = step.agent
                if step.command:
                    metadata["command"] = step.command
                if step.depends_on:
                    metadata["depends_on"] = step.depends_on
                if step.inputs:
                    metadata["inputs"] = step.inputs
                if step.outputs:
                    metadata["outputs"] = step.outputs
                if step.timeout_seconds:
                    metadata["timeout_seconds"] = step.timeout_seconds
                if step.retry.max_attempts > 1:
                    metadata["retry_attempts"] = step.retry.max_attempts

                # Overlay execution status if available
                status = self._execution_status.get(step_id)

                self._nodes.append(
                    GraphNode(
                        node_id=step.id,
                        name=step.name,
                        action=step.action.value,
                        x=x,
                        y=y,
                        metadata=metadata,
                        status=status,
                    )
                )

    def _generate_edges(self) -> None:
        """Generate edges based on step dependencies."""
        for step in self._definition.steps:
            for dep in step.depends_on:
                self._edges.append(GraphEdge(source=dep, target=step.id))


def generate_workflow_graph(
    definition: WorkflowDefinition,
    execution_status: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Generate visual graph representation of a workflow.

    Args:
        definition: Workflow definition to visualize.
        execution_status: Optional step status overlay from execution history.

    Returns:
        Dictionary with nodes, edges, and layout information.
    """
    generator = WorkflowGraphGenerator(definition, execution_status)
    return generator.generate()
