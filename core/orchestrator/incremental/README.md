# Incremental Artifact Detection System

**Status**: Specification  
**Source**: CA-007 (Incrementalist Competitive Analysis)  
**Priority**: High

## Overview

The Incremental Artifact Detection System enables AGENT-33 to process only the artifacts that have changed, rather than reprocessing entire artifact sets. This dramatically improves efficiency for large documentation repositories.

## Entry Points

- `CHANGE_DETECTION.md` - Git-based change detection specification
- `ARTIFACT_GRAPH.md` - Artifact dependency graph structure

## Core Concepts

### Three-Layer Detection Model

Adapted from Incrementalist's approach:

| Layer | Scope | AGENT-33 Equivalent |
|-------|-------|---------------------|
| Solution-Wide | Triggers full processing | Core framework changes |
| Import/Dependency | Affects related artifacts | Workflow/template dependencies |
| Direct Changes | Affects single artifact | Individual file edits |

### Detection Flow

```
Git Changes → Categorize → Build Dependency Set → Determine Scope
     │              │              │                    │
     ▼              ▼              ▼                    ▼
  DiffHelper   TriggerMatch   ArtifactGraph      Full/Incremental
```

## Integration Points

| Component | Role |
|-----------|------|
| `triggers/` | Defines solution-wide trigger patterns |
| `dependencies/` | Tracks artifact relationships |
| `filters/` | Applies include/exclude patterns |

## Usage Pattern

```python
from orchestrator.incremental import detect_changes, build_affected_set

# Detect what changed
changes = detect_changes(
    repo_path=".",
    target_branch="main"
)

# Determine affected artifacts
result = build_affected_set(
    changes=changes,
    trigger_catalog=load_triggers(),
    artifact_graph=load_graph()
)

if result.is_full_refresh:
    print(f"Full refresh needed: {result.reason}")
else:
    print(f"Incremental: {len(result.affected)} artifacts")
```

## Result Types

The system uses discriminated unions to clearly distinguish result types:

```python
@dataclass
class FullRefreshResult:
    """All artifacts need processing."""
    reason: str
    trigger_files: List[str]
    all_artifacts: List[str]

@dataclass
class IncrementalResult:
    """Only some artifacts need processing."""
    changed_files: List[str]
    affected_artifacts: List[str]
    dependency_chain: List[Tuple[str, str]]  # (source, affected)

ChangeResult = Union[FullRefreshResult, IncrementalResult]
```

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| depends-on | `triggers/TRIGGER_CATALOG.md` | Solution-wide trigger definitions |
| depends-on | `dependencies/DEPENDENCY_GRAPH_SPEC.md` | Artifact relationship graph |
| uses | `filters/GLOB_PATTERNS.md` | Include/exclude filtering |
| implements | CA-007 | Incrementalist competitive analysis |
