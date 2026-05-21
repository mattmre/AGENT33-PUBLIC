# Lineage & Visualization Specification

**Status**: Specification
**Sources**: Dagster (CA-119 to CA-130), Spinnaker Orca (CA-107 to CA-118)

## Overview

This document specifies the lineage tracking system for AGENT-33. It records the provenance of every artifact through the orchestration pipeline, supports impact analysis when artifacts change, and exports visualization-ready graph data in multiple formats.

Lineage tracking answers three fundamental questions:
1. **Where did this artifact come from?** (provenance)
2. **What was done to produce it?** (transformation history)
3. **What breaks if it changes?** (impact analysis)

## Lineage Record Schema

```yaml
lineage_record:
  artifact_id: string
  version: string
  created_by:
    agent: agent_id
    workflow: workflow_id
    stage: stage_id
    timestamp: ISO-8601
  inputs: [artifact_ref]
  transformation: string (description of how this was produced)
  metadata:
    quality_score: number (0-1)
    freshness: duration (age since creation)
    partition: string (optional)
  visualization:
    node_label: string
    node_color: string (based on type/status)
    group: string (visual grouping)
```

## Data Model

### Lineage Node

```python
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
from datetime import datetime, timedelta


class ArtifactStatus(Enum):
    FRESH = "fresh"           # Recently created or validated
    STALE = "stale"           # Inputs have changed since last build
    FAILED = "failed"         # Last build attempt failed
    IN_PROGRESS = "in_progress"  # Currently being produced
    UNKNOWN = "unknown"       # Status cannot be determined


@dataclass
class ProvenanceRecord:
    """Records who created an artifact, when, and from what."""
    agent: str                    # Agent that produced this artifact
    workflow: str                 # Workflow context
    stage: str                    # Stage within workflow
    timestamp: str                # ISO-8601
    tool: Optional[str] = None   # Tool or command used
    environment: Optional[str] = None  # Execution environment


@dataclass
class LineageNode:
    """A single artifact in the lineage graph."""
    artifact_id: str
    version: str
    provenance: ProvenanceRecord
    inputs: List[str]             # artifact_ids of inputs
    transformation: str           # Human-readable description
    status: ArtifactStatus = ArtifactStatus.UNKNOWN
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def quality_score(self) -> Optional[float]:
        return self.metadata.get("quality_score")

    @property
    def freshness(self) -> Optional[timedelta]:
        if self.provenance.timestamp:
            created = datetime.fromisoformat(self.provenance.timestamp)
            return datetime.utcnow() - created
        return None

    @property
    def partition(self) -> Optional[str]:
        return self.metadata.get("partition")
```

### Lineage Edge

```python
class TransformationType(Enum):
    GENERATED = "generated"      # Agent produced artifact from scratch
    REFINED = "refined"          # Agent improved an existing artifact
    MERGED = "merged"            # Multiple artifacts combined
    DERIVED = "derived"          # Extracted or computed from inputs
    COPIED = "copied"            # Direct copy with no transformation
    VALIDATED = "validated"      # Input verified, output is attestation


@dataclass
class LineageEdge:
    """A transformation link between artifacts."""
    source: str                  # Input artifact_id
    target: str                  # Output artifact_id
    transformation_type: TransformationType
    description: str             # What the transformation did
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### Lineage Graph Container

```python
@dataclass
class LineageGraph:
    """Full lineage graph with query capabilities."""
    nodes: Dict[str, LineageNode] = field(default_factory=dict)
    edges: List[LineageEdge] = field(default_factory=list)
    version: str = "1.0"
    built_at: str = ""

    def add_record(self, node: LineageNode) -> None:
        """Add or update a lineage node."""
        self.nodes[node.artifact_id] = node

    def add_edge(self, edge: LineageEdge) -> None:
        """Add a transformation edge."""
        self.edges.append(edge)

    def get_inputs(self, artifact_id: str) -> List[str]:
        """Get direct input artifact IDs."""
        return [e.source for e in self.edges if e.target == artifact_id]

    def get_outputs(self, artifact_id: str) -> List[str]:
        """Get direct output artifact IDs."""
        return [e.target for e in self.edges if e.source == artifact_id]
```

## Lineage Queries

### Ancestors and Descendants

```python
def ancestors(graph: LineageGraph, artifact_id: str) -> set[str]:
    """
    Find all upstream artifacts that contributed to this artifact.

    Walks the graph backwards through all input edges transitively.

    Returns:
        Set of ancestor artifact IDs (excludes the starting artifact).
    """
    visited = set()
    queue = [artifact_id]

    while queue:
        current = queue.pop(0)
        for input_id in graph.get_inputs(current):
            if input_id not in visited:
                visited.add(input_id)
                queue.append(input_id)

    return visited


def descendants(graph: LineageGraph, artifact_id: str) -> set[str]:
    """
    Find all downstream artifacts derived from this artifact.

    Walks the graph forward through all output edges transitively.

    Returns:
        Set of descendant artifact IDs (excludes the starting artifact).
    """
    visited = set()
    queue = [artifact_id]

    while queue:
        current = queue.pop(0)
        for output_id in graph.get_outputs(current):
            if output_id not in visited:
                visited.add(output_id)
                queue.append(output_id)

    return visited
```

### Shortest Path

```python
from collections import deque


def shortest_path(
    graph: LineageGraph,
    from_id: str,
    to_id: str
) -> Optional[List[str]]:
    """
    Find the shortest path between two artifacts.

    Uses BFS over both input and output edges (undirected traversal).

    Returns:
        Ordered list of artifact IDs forming the path, or None if unreachable.
    """
    if from_id == to_id:
        return [from_id]

    # Build adjacency list (undirected)
    adjacency: Dict[str, set] = {}
    for edge in graph.edges:
        adjacency.setdefault(edge.source, set()).add(edge.target)
        adjacency.setdefault(edge.target, set()).add(edge.source)

    visited = {from_id}
    queue = deque([(from_id, [from_id])])

    while queue:
        current, path = queue.popleft()
        for neighbor in adjacency.get(current, []):
            if neighbor == to_id:
                return path + [neighbor]
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))

    return None
```

### Common Ancestors

```python
def common_ancestors(
    graph: LineageGraph,
    artifact_a: str,
    artifact_b: str
) -> set[str]:
    """
    Find all common ancestors of two artifacts.

    Returns:
        Set of artifact IDs that are ancestors of both inputs.
    """
    ancestors_a = ancestors(graph, artifact_a)
    ancestors_b = ancestors(graph, artifact_b)
    return ancestors_a & ancestors_b
```

## Impact Analysis

```python
@dataclass
class ImpactReport:
    """Report of downstream impact from an artifact change."""
    changed_artifact: str
    affected_artifacts: List[str]         # All downstream artifacts
    affected_workflows: List[str]         # Workflows that use affected artifacts
    affected_agents: List[str]            # Agents that produced affected artifacts
    stale_count: int                      # Number of artifacts now stale
    critical_paths: List[List[str]]       # Paths through critical artifacts


def analyze_impact(
    graph: LineageGraph,
    changed_artifact_id: str,
    critical_artifacts: Optional[set[str]] = None
) -> ImpactReport:
    """
    Analyze the downstream impact of an artifact change.

    Args:
        graph: The lineage graph.
        changed_artifact_id: ID of the artifact that changed.
        critical_artifacts: Optional set of artifact IDs considered critical.

    Returns:
        ImpactReport with all affected artifacts and metadata.
    """
    affected = descendants(graph, changed_artifact_id)

    affected_workflows = set()
    affected_agents = set()
    for aid in affected:
        node = graph.nodes.get(aid)
        if node:
            affected_workflows.add(node.provenance.workflow)
            affected_agents.add(node.provenance.agent)

    critical_paths = []
    if critical_artifacts:
        hit = affected & critical_artifacts
        for crit_id in hit:
            path = shortest_path(graph, changed_artifact_id, crit_id)
            if path:
                critical_paths.append(path)

    return ImpactReport(
        changed_artifact=changed_artifact_id,
        affected_artifacts=sorted(affected),
        affected_workflows=sorted(affected_workflows),
        affected_agents=sorted(affected_agents),
        stale_count=len(affected),
        critical_paths=critical_paths,
    )
```

## Cross-Workflow Lineage

Artifacts produced by one workflow may be consumed by another. The lineage graph tracks these cross-workflow relationships explicitly.

```python
@dataclass
class CrossWorkflowLink:
    """Tracks an artifact that crosses workflow boundaries."""
    artifact_id: str
    producer_workflow: str
    consumer_workflows: List[str]
    shared_since: str              # ISO-8601


def find_cross_workflow_artifacts(graph: LineageGraph) -> List[CrossWorkflowLink]:
    """
    Identify artifacts that are shared across workflow boundaries.

    An artifact is cross-workflow if its producer workflow differs from
    the workflow of any artifact that consumes it.

    Returns:
        List of CrossWorkflowLink records.
    """
    links = []

    for artifact_id, node in graph.nodes.items():
        producer_wf = node.provenance.workflow
        consumer_wfs = set()

        for output_id in graph.get_outputs(artifact_id):
            output_node = graph.nodes.get(output_id)
            if output_node and output_node.provenance.workflow != producer_wf:
                consumer_wfs.add(output_node.provenance.workflow)

        if consumer_wfs:
            links.append(CrossWorkflowLink(
                artifact_id=artifact_id,
                producer_workflow=producer_wf,
                consumer_workflows=sorted(consumer_wfs),
                shared_since=node.provenance.timestamp,
            ))

    return links
```

## Time-Travel

Lineage snapshots enable querying the graph at any historical point in time.

```python
@dataclass
class LineageSnapshot:
    """A point-in-time snapshot of the lineage graph."""
    timestamp: str                # ISO-8601
    graph: LineageGraph
    event: str                    # What triggered this snapshot


class LineageTimeline:
    """Ordered collection of lineage snapshots for time-travel queries."""

    def __init__(self):
        self.snapshots: List[LineageSnapshot] = []

    def record(self, graph: LineageGraph, event: str) -> None:
        """Record a new snapshot."""
        snapshot = LineageSnapshot(
            timestamp=datetime.utcnow().isoformat() + "Z",
            graph=graph,
            event=event,
        )
        self.snapshots.append(snapshot)

    def at(self, timestamp: str) -> Optional[LineageGraph]:
        """
        Return the lineage graph as it existed at the given timestamp.

        Finds the most recent snapshot at or before the requested time.

        Args:
            timestamp: ISO-8601 timestamp.

        Returns:
            LineageGraph at that point, or None if no snapshot exists.
        """
        target = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        best = None

        for snapshot in self.snapshots:
            snap_time = datetime.fromisoformat(
                snapshot.timestamp.replace("Z", "+00:00")
            )
            if snap_time <= target:
                best = snapshot

        return best.graph if best else None

    def diff(self, t1: str, t2: str) -> Dict[str, Any]:
        """
        Compare lineage between two points in time.

        Returns:
            Dictionary with added, removed, and modified artifacts.
        """
        graph1 = self.at(t1)
        graph2 = self.at(t2)

        if not graph1 or not graph2:
            return {"error": "One or both timestamps have no snapshot"}

        ids1 = set(graph1.nodes.keys())
        ids2 = set(graph2.nodes.keys())

        return {
            "added": sorted(ids2 - ids1),
            "removed": sorted(ids1 - ids2),
            "modified": sorted(
                aid for aid in ids1 & ids2
                if graph1.nodes[aid].version != graph2.nodes[aid].version
            ),
        }
```

## Visualization Export

### Mermaid Export

```python
def export_mermaid(graph: LineageGraph) -> str:
    """
    Export lineage graph as a Mermaid diagram.

    Groups nodes by workflow and colors by status.
    """
    lines = ["graph TD"]

    # Group nodes by workflow
    workflows: Dict[str, List[str]] = {}
    for aid, node in graph.nodes.items():
        wf = node.provenance.workflow
        workflows.setdefault(wf, []).append(aid)

    for wf, artifact_ids in workflows.items():
        lines.append(f"    subgraph {wf}")
        for aid in artifact_ids:
            node = graph.nodes[aid]
            label = node.metadata.get("visualization", {}).get(
                "node_label", aid
            )
            lines.append(f"        {_safe_id(aid)}[\"{label}\"]")
        lines.append("    end")

    for edge in graph.edges:
        src = _safe_id(edge.source)
        tgt = _safe_id(edge.target)
        lines.append(
            f"    {src} -->|\"{edge.transformation_type.value}\"| {tgt}"
        )

    return "\n".join(lines)


def _safe_id(artifact_id: str) -> str:
    """Convert artifact ID to a Mermaid-safe identifier."""
    return artifact_id.replace(":", "_").replace("-", "_").replace("/", "_")
```

### DOT/Graphviz Export

```python
STATUS_COLORS = {
    ArtifactStatus.FRESH: "#4CAF50",
    ArtifactStatus.STALE: "#FF9800",
    ArtifactStatus.FAILED: "#F44336",
    ArtifactStatus.IN_PROGRESS: "#2196F3",
    ArtifactStatus.UNKNOWN: "#9E9E9E",
}


def export_dot(graph: LineageGraph) -> str:
    """Export lineage graph as DOT format for Graphviz."""
    lines = [
        "digraph lineage {",
        "    rankdir=LR;",
        "    node [shape=box, style=filled, fontname=\"Helvetica\"];",
    ]

    for aid, node in graph.nodes.items():
        color = STATUS_COLORS.get(node.status, "#9E9E9E")
        label = node.metadata.get("visualization", {}).get(
            "node_label", aid
        )
        group = node.metadata.get("visualization", {}).get("group", "")
        lines.append(
            f"    \"{aid}\" ["
            f"label=\"{label}\", "
            f"fillcolor=\"{color}\", "
            f"tooltip=\"{group}\""
            f"];"
        )

    for edge in graph.edges:
        lines.append(
            f"    \"{edge.source}\" -> \"{edge.target}\" "
            f"[label=\"{edge.transformation_type.value}\"];"
        )

    lines.append("}")
    return "\n".join(lines)
```

### JSON Export

```python
import json


def export_json(graph: LineageGraph) -> str:
    """Export lineage graph as JSON for custom renderers."""
    data = {
        "$schema": "../schemas/lineage-graph.schema.json",
        "version": graph.version,
        "built_at": graph.built_at,
        "nodes": {},
        "edges": [],
    }

    for aid, node in graph.nodes.items():
        data["nodes"][aid] = {
            "version": node.version,
            "status": node.status.value,
            "provenance": {
                "agent": node.provenance.agent,
                "workflow": node.provenance.workflow,
                "stage": node.provenance.stage,
                "timestamp": node.provenance.timestamp,
            },
            "inputs": node.inputs,
            "transformation": node.transformation,
            "metadata": node.metadata,
        }

    for edge in graph.edges:
        data["edges"].append({
            "source": edge.source,
            "target": edge.target,
            "type": edge.transformation_type.value,
            "description": edge.description,
        })

    return json.dumps(data, indent=2)
```

## CLI Commands

```bash
# Build lineage from current state
agent-33 lineage build [--output lineage.json]

# Query provenance
agent-33 lineage provenance <artifact-id>
agent-33 lineage ancestors <artifact-id>
agent-33 lineage descendants <artifact-id>
agent-33 lineage path <from-id> <to-id>
agent-33 lineage common-ancestors <id-a> <id-b>

# Impact analysis
agent-33 lineage impact <artifact-id> [--critical critical-ids.txt]
agent-33 lineage cross-workflow

# Time-travel
agent-33 lineage at <ISO-8601-timestamp>
agent-33 lineage diff <timestamp-a> <timestamp-b>

# Visualization
agent-33 lineage export --format mermaid
agent-33 lineage export --format dot
agent-33 lineage export --format json
agent-33 lineage export --format dot | dot -Tpng -o lineage.png
```

## Integration Points

### Asset-First Schema

The lineage graph extends the asset-first schema by adding provenance metadata to each asset definition. Every asset declared in the asset schema can be looked up in the lineage graph to determine its full history.

### Dependency Graph

The lineage graph complements the dependency graph (see `DEPENDENCY_GRAPH_SPEC.md`). While the dependency graph captures structural relationships (what depends on what), the lineage graph captures runtime relationships (what produced what, and when).

| Aspect | Dependency Graph | Lineage Graph |
|--------|-----------------|---------------|
| Focus | Structure | History |
| Edges | Static declarations | Runtime transformations |
| Time | Current state | Full history with snapshots |
| Use case | Build ordering | Debugging, auditing, impact |

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| extends | `../dependencies/DEPENDENCY_GRAPH_SPEC.md` | Adds provenance to dependency structure |
| integrates | `../incremental/ARTIFACT_GRAPH.md` | Asset-first schema integration |
| used-by | `../sensors/ARTIFACT_SENSOR_SPEC.md` | Sensors trigger on lineage events |
| used-by | `../decision/DECISION_ROUTING_SPEC.md` | Decisions logged in lineage |
| sources | Dagster CA-119 to CA-130 | Asset lineage and materialization patterns |
| sources | Spinnaker Orca CA-107 to CA-118 | Pipeline execution provenance |
