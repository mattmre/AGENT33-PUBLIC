# Asset-First Workflow Schema

**Status**: Specification
**Sources**: Dagster (CA-119), Conductor (CA-017)

## Related Documents

- [Dependency Graph Spec](../dependencies/DEPENDENCY_GRAPH_SPEC.md) - Graph structure this schema integrates with
- [Artifact Graph](../incremental/ARTIFACT_GRAPH.md) - Incremental artifact tracking
- [Change Detection](../incremental/CHANGE_DETECTION.md) - Staleness and refresh detection
- [Trigger Catalog](../triggers/TRIGGER_CATALOG.md) - Event-driven trigger definitions
- [DAG Execution Engine](./DAG_EXECUTION_ENGINE.md) - Stage execution for asset materialization
- [Expression Language Spec](./EXPRESSION_LANGUAGE_SPEC.md) - Dynamic expressions in asset definitions

## Overview

AGENT-33 treats assets (artifacts, deliverables, specifications) as first-class citizens rather than side effects of task execution. Workflows are defined in terms of the assets they produce, and the orchestrator derives the execution plan from asset dependencies. This inverts the traditional task-first model: instead of "run these tasks in order," the system asks "what assets need to be fresh, and what must execute to produce them?"

## Asset Definition Schema

### Core Schema

```yaml
asset:
  name: string                    # Unique identifier (e.g., "security_policy_v2")
  type: specification | schema | policy | template | research | workflow
  description: string             # Human-readable purpose
  dependencies: [asset_ref]       # Assets this asset depends on
  freshness_policy:
    max_staleness: duration        # e.g., "7d", "24h", "1h"
    auto_refresh: boolean          # Trigger rematerialization when stale
    cron_schedule: string          # Optional cron for scheduled refresh (e.g., "0 0 * * MON")
  materialization:
    strategy: eager | lazy | on_demand | scheduled
    timeout: duration              # Max time to produce this asset
    retries: number                # Retry count on failure
  partitions:
    type: time | key | dynamic
    definition: object             # Partition-specific configuration
  io_manager: string               # Reference to IO manager for read/write
  metadata:
    owner: string                  # Responsible agent or team
    tags: [string]                 # Classification tags
    quality_checks: [check_ref]    # Post-materialization validation
```

### Python Data Model

```python
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
from datetime import timedelta


class AssetType(Enum):
    SPECIFICATION = "specification"
    SCHEMA = "schema"
    POLICY = "policy"
    TEMPLATE = "template"
    RESEARCH = "research"
    WORKFLOW = "workflow"


class MaterializationStrategy(Enum):
    EAGER = "eager"        # Materialize as soon as dependencies are ready
    LAZY = "lazy"          # Materialize only when requested downstream
    ON_DEMAND = "on_demand"  # Materialize only on explicit request
    SCHEDULED = "scheduled"  # Materialize on a cron schedule


class PartitionType(Enum):
    TIME = "time"          # Time-windowed partitions (daily, weekly)
    KEY = "key"            # Named key partitions (region, category)
    DYNAMIC = "dynamic"    # Runtime-determined partitions


@dataclass
class FreshnessPolicy:
    """Defines when an asset is considered stale."""
    max_staleness: timedelta
    auto_refresh: bool = False
    cron_schedule: Optional[str] = None

    def is_stale(self, last_materialized: "datetime") -> bool:
        from datetime import datetime, timezone
        age = datetime.now(timezone.utc) - last_materialized
        return age > self.max_staleness


@dataclass
class MaterializationConfig:
    """Controls how and when an asset is produced."""
    strategy: MaterializationStrategy = MaterializationStrategy.LAZY
    timeout: timedelta = timedelta(minutes=30)
    retries: int = 1


@dataclass
class PartitionDefinition:
    """Defines how an asset is partitioned."""
    type: PartitionType
    definition: Dict[str, Any] = field(default_factory=dict)
    # For TIME: {"granularity": "daily", "start": "2025-01-01"}
    # For KEY: {"keys": ["us-east", "eu-west", "ap-south"]}
    # For DYNAMIC: {"source_asset": "region_list", "key_expr": "${item.id}"}


@dataclass
class AssetDefinition:
    """First-class asset in the AGENT-33 workflow system."""
    name: str
    type: AssetType
    description: str
    dependencies: List[str] = field(default_factory=list)
    freshness_policy: Optional[FreshnessPolicy] = None
    materialization: MaterializationConfig = field(
        default_factory=MaterializationConfig
    )
    partitions: Optional[PartitionDefinition] = None
    io_manager: str = "default"
    owner: str = ""
    tags: List[str] = field(default_factory=list)
    quality_checks: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

## Asset Lineage Graph

The lineage graph tracks how assets depend on and derive from each other. It is a directed acyclic graph (DAG) where edges represent data flow from upstream to downstream assets.

### Graph Construction

```python
@dataclass
class AssetLineageGraph:
    """DAG of asset dependencies."""
    assets: Dict[str, AssetDefinition] = field(default_factory=dict)
    edges: List["AssetEdge"] = field(default_factory=list)

    def register(self, asset: AssetDefinition) -> None:
        self.assets[asset.name] = asset
        for dep in asset.dependencies:
            self.edges.append(AssetEdge(source=dep, target=asset.name))

    def upstream(self, asset_name: str) -> List[str]:
        """All assets this asset depends on (transitive)."""
        visited = set()
        queue = [asset_name]
        while queue:
            current = queue.pop(0)
            for edge in self.edges:
                if edge.target == current and edge.source not in visited:
                    visited.add(edge.source)
                    queue.append(edge.source)
        return list(visited)

    def downstream(self, asset_name: str) -> List[str]:
        """All assets that depend on this asset (transitive)."""
        visited = set()
        queue = [asset_name]
        while queue:
            current = queue.pop(0)
            for edge in self.edges:
                if edge.source == current and edge.target not in visited:
                    visited.add(edge.target)
                    queue.append(edge.target)
        return list(visited)

    def topological_order(self) -> List[str]:
        """Return assets in dependency-safe execution order."""
        in_degree = {name: 0 for name in self.assets}
        for edge in self.edges:
            in_degree[edge.target] += 1
        queue = [n for n, d in in_degree.items() if d == 0]
        order = []
        while queue:
            node = queue.pop(0)
            order.append(node)
            for edge in self.edges:
                if edge.source == node:
                    in_degree[edge.target] -= 1
                    if in_degree[edge.target] == 0:
                        queue.append(edge.target)
        if len(order) != len(self.assets):
            raise ValueError("Cycle detected in asset lineage graph")
        return order


@dataclass
class AssetEdge:
    source: str  # Upstream asset name
    target: str  # Downstream asset name
```

### Lineage Visualization

```
research_data ──> competitive_analysis ──> gap_report
                                       ──> feature_matrix
                  framework_survey ─────> gap_report
                                       ──> architecture_spec ──> implementation_plan
```

## Freshness Policies

Freshness policies define when an asset is considered stale and whether it should be automatically refreshed.

### Policy Types

| Policy | `max_staleness` | `auto_refresh` | Use Case |
|--------|----------------|----------------|----------|
| Real-time | `1h` | `true` | Active development specs |
| Daily | `24h` | `true` | Metrics, dashboards |
| Weekly | `7d` | `true` | Reports, summaries |
| Manual | `365d` | `false` | Foundational specs |
| Never stale | (none) | `false` | Immutable artifacts |

### Staleness Propagation

When an upstream asset is rematerialized, all downstream assets with `auto_refresh: true` are evaluated for staleness. If a downstream asset was last materialized before its upstream dependency, it is marked stale regardless of its own `max_staleness` window.

```python
def propagate_staleness(
    graph: AssetLineageGraph,
    rematerialized_asset: str,
    rematerialized_at: "datetime"
) -> List[str]:
    """Return downstream assets that are now stale."""
    stale = []
    for name in graph.downstream(rematerialized_asset):
        asset = graph.assets[name]
        if asset.freshness_policy and asset.freshness_policy.auto_refresh:
            stale.append(name)
    return stale
```

## Materialization Strategies

### Eager

Materialize as soon as all upstream dependencies are fresh. Used for critical-path assets where latency matters.

### Lazy

Materialize only when a downstream asset requests this asset and it is stale. Saves compute for assets that may not be needed every cycle.

### On-Demand

Materialize only when an operator or agent explicitly requests it. No automatic triggering.

### Scheduled

Materialize on a cron schedule, regardless of upstream changes. Used for periodic reports and snapshots.

```python
async def resolve_materialization(
    asset: AssetDefinition,
    graph: AssetLineageGraph,
    state: "MaterializationState"
) -> bool:
    """Determine if an asset should be materialized now."""
    strategy = asset.materialization.strategy

    if strategy == MaterializationStrategy.EAGER:
        # Materialize if any upstream was refreshed since last materialization
        for dep in asset.dependencies:
            if state.last_materialized(dep) > state.last_materialized(asset.name):
                return True
        return False

    elif strategy == MaterializationStrategy.LAZY:
        # Materialize only if requested and stale
        if not state.is_requested(asset.name):
            return False
        return state.is_stale(asset.name)

    elif strategy == MaterializationStrategy.ON_DEMAND:
        return state.is_explicitly_requested(asset.name)

    elif strategy == MaterializationStrategy.SCHEDULED:
        return state.is_schedule_due(asset.name, asset.freshness_policy.cron_schedule)

    return False
```

## Asset Sensors

Sensors monitor upstream assets or external sources and trigger workflow execution when conditions are met.

```python
@dataclass
class AssetSensor:
    """Monitors conditions and triggers asset materialization."""
    name: str
    watched_assets: List[str]       # Assets to monitor
    target_assets: List[str]        # Assets to materialize when triggered
    condition: str                  # Expression (see Expression Language Spec)
    min_interval: timedelta = timedelta(minutes=5)
    enabled: bool = True
```

### Sensor Types

| Sensor | Trigger Condition |
|--------|------------------|
| Freshness sensor | Upstream asset exceeds `max_staleness` |
| Change sensor | Upstream asset content hash changed |
| Schedule sensor | Cron expression fires |
| External sensor | External system signals readiness |
| Multi-asset sensor | Multiple upstream assets all refreshed |

### Sensor YAML Example

```yaml
sensors:
  - name: gap_report_refresh
    watched_assets: [competitive_analysis, framework_survey]
    target_assets: [gap_report]
    condition: "${all(watched, asset -> asset.is_fresh)}"
    min_interval: "1h"
    enabled: true
```

## Partition Definitions

Partitions allow a single asset definition to represent multiple independent slices of data.

### Time-Based Partitions

```yaml
partitions:
  type: time
  definition:
    granularity: daily      # daily | weekly | monthly
    start: "2025-01-01"
    end: null               # null = ongoing
    timezone: "UTC"
```

Each partition key is a date string (e.g., `"2025-06-15"`). Materialization targets a specific partition without affecting others.

### Key-Based Partitions

```yaml
partitions:
  type: key
  definition:
    keys: [security, performance, usability, reliability]
```

Each key represents an independent slice. Useful for domain-partitioned specifications.

### Dynamic Partitions

```yaml
partitions:
  type: dynamic
  definition:
    source_asset: agent_registry
    key_expression: "${item.agent_id}"
```

Partition keys are derived at runtime from a source asset. New partitions are added automatically when the source changes.

## Asset Groups and Cross-Group Dependencies

Assets are organized into groups for management and visibility. Groups do not affect execution order; only explicit `dependencies` do.

```yaml
asset_groups:
  - name: competitive_intelligence
    assets: [research_data, competitive_analysis, framework_survey]
    description: "Raw research and analysis assets"

  - name: architecture
    assets: [gap_report, feature_matrix, architecture_spec]
    description: "Derived architecture artifacts"
    depends_on_groups: [competitive_intelligence]  # Advisory, not enforced
```

```python
@dataclass
class AssetGroup:
    name: str
    asset_names: List[str]
    description: str = ""
    tags: List[str] = field(default_factory=list)
```

## IO Manager Abstraction

IO Managers handle the reading and writing of asset data. Each asset references an IO Manager by name, decoupling the asset definition from storage concerns.

```python
from abc import ABC, abstractmethod


class IOManager(ABC):
    """Abstract interface for asset storage."""

    @abstractmethod
    async def load(self, asset_name: str, partition_key: Optional[str] = None) -> Any:
        """Read a materialized asset."""
        ...

    @abstractmethod
    async def save(
        self, asset_name: str, data: Any, partition_key: Optional[str] = None
    ) -> None:
        """Write a materialized asset."""
        ...

    @abstractmethod
    async def exists(self, asset_name: str, partition_key: Optional[str] = None) -> bool:
        """Check if a materialized asset exists."""
        ...


class FileSystemIOManager(IOManager):
    """Stores assets as files on disk."""
    def __init__(self, base_path: str):
        self.base_path = base_path

    async def load(self, asset_name: str, partition_key: Optional[str] = None) -> Any:
        path = self._resolve_path(asset_name, partition_key)
        with open(path, "r") as f:
            return f.read()

    async def save(self, asset_name: str, data: Any, partition_key: Optional[str] = None) -> None:
        path = self._resolve_path(asset_name, partition_key)
        with open(path, "w") as f:
            f.write(str(data))

    async def exists(self, asset_name: str, partition_key: Optional[str] = None) -> bool:
        import os
        return os.path.exists(self._resolve_path(asset_name, partition_key))

    def _resolve_path(self, asset_name: str, partition_key: Optional[str]) -> str:
        import os
        if partition_key:
            return os.path.join(self.base_path, asset_name, f"{partition_key}.md")
        return os.path.join(self.base_path, asset_name, "latest.md")


class GitIOManager(IOManager):
    """Stores assets in a git-tracked directory with commit metadata."""
    # Implementation tracks materialization as git commits
    ...
```

### IO Manager Registry

```yaml
io_managers:
  default: filesystem
  filesystem:
    type: FileSystemIOManager
    base_path: "./artifacts"
  git:
    type: GitIOManager
    repo_path: "."
    branch: "assets"
```

## Integration with AGENT-33 Dependency Graph

The asset lineage graph integrates with the existing dependency graph (see [Dependency Graph Spec](../dependencies/DEPENDENCY_GRAPH_SPEC.md)) by mapping assets to `NodeType.ARTIFACT` nodes and asset dependencies to `EdgeType.IMPORTS` edges.

```python
def sync_to_dependency_graph(
    asset_graph: AssetLineageGraph,
    dep_graph: "DependencyGraph"  # From DEPENDENCY_GRAPH_SPEC
) -> None:
    """Project asset lineage into the main dependency graph."""
    for name, asset in asset_graph.assets.items():
        dep_graph.add_node(GraphNode(
            id=f"asset:{name}",
            type=NodeType.ARTIFACT,
            path="",
            name=name,
            metadata={
                "asset_type": asset.type.value,
                "owner": asset.owner,
                "tags": asset.tags,
            }
        ))
    for edge in asset_graph.edges:
        dep_graph.add_edge(GraphEdge(
            source=f"asset:{edge.source}",
            target=f"asset:{edge.target}",
            type=EdgeType.IMPORTS,
        ))
```

## Complete Example

```yaml
assets:
  - name: competitive_research
    type: research
    description: "Raw competitive analysis data from 10 frameworks"
    dependencies: []
    freshness_policy:
      max_staleness: "30d"
      auto_refresh: false
    materialization:
      strategy: on_demand
      timeout: "2h"
      retries: 1
    io_manager: git
    metadata:
      owner: research-agent
      tags: [competitive, research]
      quality_checks: [has_minimum_frameworks, valid_markdown]

  - name: gap_analysis
    type: specification
    description: "Feature gap analysis derived from competitive research"
    dependencies: [competitive_research]
    freshness_policy:
      max_staleness: "7d"
      auto_refresh: true
    materialization:
      strategy: eager
      timeout: "30m"
      retries: 2
    partitions:
      type: key
      definition:
        keys: [workflow, expression, error_handling, observability]
    io_manager: filesystem
    metadata:
      owner: architect-agent
      tags: [analysis, architecture]
      quality_checks: [covers_all_domains, no_empty_sections]

sensors:
  - name: refresh_gap_on_research_update
    watched_assets: [competitive_research]
    target_assets: [gap_analysis]
    condition: "${competitive_research.changed}"
    min_interval: "1h"

asset_groups:
  - name: intelligence
    assets: [competitive_research, gap_analysis]
    description: "Competitive intelligence pipeline"
```
