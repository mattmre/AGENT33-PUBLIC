"""Typed graph memory primitives."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MemoryNodeType(StrEnum):
    TASK = "task"
    FILE = "file"
    TOOL = "tool"
    DECISION = "decision"
    EVIDENCE = "evidence"
    RESOURCE = "resource"
    MODEL = "model"
    USER = "user"
    SESSION = "session"


class MemoryEdgeType(StrEnum):
    REFERENCES = "references"
    CAUSED_BY = "caused_by"
    CO_ACCESSED = "co_accessed"
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"
    DEPENDS_ON = "depends_on"
    VERIFIED_BY = "verified_by"


class MemoryGraphNode(BaseModel):
    node_id: str
    node_type: MemoryNodeType
    label: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryGraphEdge(BaseModel):
    source_id: str
    target_id: str
    edge_type: MemoryEdgeType
    evidence_uri: str = ""


class MemoryGraph:
    def __init__(self) -> None:
        self._nodes: dict[str, MemoryGraphNode] = {}
        self._edges: list[MemoryGraphEdge] = []

    def add_node(self, node: MemoryGraphNode) -> MemoryGraphNode:
        self._nodes[node.node_id] = node
        return node

    def add_edge(self, edge: MemoryGraphEdge) -> MemoryGraphEdge:
        self._edges.append(edge)
        return edge

    def neighbors(self, node_id: str, *, edge_type: MemoryEdgeType | None = None) -> list[str]:
        return [
            edge.target_id
            for edge in self._edges
            if edge.source_id == node_id and (edge_type is None or edge.edge_type == edge_type)
        ]
