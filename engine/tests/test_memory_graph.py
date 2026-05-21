from __future__ import annotations

from agent33.memory.graph import (
    MemoryEdgeType,
    MemoryGraph,
    MemoryGraphEdge,
    MemoryGraphNode,
    MemoryNodeType,
)


def test_memory_graph_stores_typed_nodes_and_edges() -> None:
    graph = MemoryGraph()
    graph.add_node(MemoryGraphNode(node_id="task-1", node_type=MemoryNodeType.TASK))
    graph.add_node(MemoryGraphNode(node_id="evidence-1", node_type=MemoryNodeType.EVIDENCE))
    graph.add_edge(
        MemoryGraphEdge(
            source_id="task-1",
            target_id="evidence-1",
            edge_type=MemoryEdgeType.VERIFIED_BY,
        )
    )

    assert graph.neighbors("task-1", edge_type=MemoryEdgeType.VERIFIED_BY) == ["evidence-1"]
    assert graph.neighbors("task-1", edge_type=MemoryEdgeType.CONTRADICTS) == []
