# Workflow Dependency Graph

**Status**: Specification  
**Source**: CA-014 (Incrementalist EmitDependencyGraphTask.cs pattern)  
**Priority**: Medium

## Overview

The Workflow Dependency Graph tracks relationships between workflows, agents, and artifacts. This enables impact analysis, execution ordering, and visualization of the orchestration system.

## Entry Points

- `DEPENDENCY_GRAPH_SPEC.md` - Graph structure and algorithms

## Core Concept

The graph contains three node types:

```
    ┌─────────────┐
    │  Workflows  │
    └──────┬──────┘
           │ invokes
    ┌──────▼──────┐
    │   Agents    │
    └──────┬──────┘
           │ processes
    ┌──────▼──────┐
    │  Artifacts  │
    └─────────────┘
```

## Graph Operations

### Build Graph

```bash
# Build full dependency graph
agent-33 graph build

# Update graph incrementally
agent-33 graph update
```

### Query Graph

```bash
# What depends on this artifact?
agent-33 graph dependents core/prompts/SYSTEM.md

# What does this workflow depend on?
agent-33 graph dependencies workflow:refinement

# Impact analysis
agent-33 graph impact core/packs/policy-pack-v1/
```

### Export Graph

```bash
# Export as Mermaid diagram
agent-33 graph export --format mermaid

# Export as JSON
agent-33 graph export --format json

# Export as DOT (Graphviz)
agent-33 graph export --format dot
```

## Use Cases

1. **Execution Ordering** - Process dependencies before dependents
2. **Impact Analysis** - Know what's affected by a change
3. **Visualization** - Understand system structure
4. **Cycle Detection** - Prevent circular dependencies

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| depends-on | `DEPENDENCY_GRAPH_SPEC.md` | Full specification |
| uses | `../incremental/ARTIFACT_GRAPH.md` | Artifact relationships |
| implements | CA-014 | Incrementalist competitive analysis |
