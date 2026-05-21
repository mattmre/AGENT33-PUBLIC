# Solution-Wide Change Triggers

**Status**: Specification  
**Source**: CA-009 (Incrementalist SolutionWideChangeDetector.cs pattern)  
**Priority**: High

## Overview

Solution-wide triggers define which files, when changed, require full processing of all artifacts rather than incremental processing. This prevents stale artifacts when foundational components change.

## Entry Points

- `TRIGGER_CATALOG.md` - Complete catalog of trigger patterns

## Core Concept

When a trigger file changes:
1. Incremental detection is bypassed
2. All artifacts in scope are marked for processing
3. A clear reason is logged for auditability

```python
@dataclass
class TriggerMatch:
    """Result when a trigger file is detected."""
    trigger_file: Path
    trigger_rule: str
    scope: str  # "full" or "category"
    affected_categories: List[str]
    reason: str
```

## Trigger Categories

### Full Refresh Triggers

These files affect everything:

| Pattern | Reason |
|---------|--------|
| `core/prompts/SYSTEM.md` | Base system prompt for all agents |
| `core/packs/policy-pack-v1/**` | Governance policies affect all behavior |
| `.claude/**` | Project-wide AI configuration |
| `manifest.md` | Repository structure definition |
| `dedup-policy.md` | Deduplication rules affect canonicalization |

### Category Triggers

These files affect specific categories:

| Pattern | Affected Category | Reason |
|---------|-------------------|--------|
| `core/orchestrator/prompts/**` | orchestrator | Agent prompts changed |
| `core/workflows/PROMOTION_CRITERIA.md` | workflows | Promotion rules changed |
| `core/templates/README.md` | templates | Template index changed |
| `core/agents/AGENT_REGISTRY.md` | agents | Agent definitions changed |

## Detection Flow

```
Changed Files → Match Triggers → Determine Scope
      │               │                │
      ▼               ▼                ▼
  ChangeSet    TriggerCatalog    Full/Incremental
```

```python
def check_triggers(
    changes: ChangeSet,
    catalog: TriggerCatalog
) -> Optional[TriggerMatch]:
    """
    Check if any changed file is a trigger.
    
    Returns:
        TriggerMatch if a trigger was hit, None otherwise
    """
    for file in changes.files:
        for rule in catalog.rules:
            if rule.matches(file):
                return TriggerMatch(
                    trigger_file=file,
                    trigger_rule=rule.name,
                    scope=rule.scope,
                    affected_categories=rule.categories,
                    reason=rule.reason
                )
    return None
```

## Quick Example

```python
from orchestrator.triggers import load_catalog, check_triggers

changes = detect_changes(repo_path=".", target_branch="main")
catalog = load_catalog()

trigger = check_triggers(changes, catalog)
if trigger:
    print(f"Full refresh needed: {trigger.reason}")
    print(f"Trigger file: {trigger.trigger_file}")
    # Process all artifacts
else:
    # Use incremental processing
    affected = find_affected(graph, changes.files)
```

## CLI Integration

```bash
# Check if current changes trigger full refresh
agent-33 triggers check

# List all triggers
agent-33 triggers list

# Explain why full refresh
agent-33 triggers explain
```

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| depends-on | `TRIGGER_CATALOG.md` | Trigger definitions |
| uses | `../incremental/CHANGE_DETECTION.md` | Changed file input |
| informs | `../incremental/README.md` | Incremental decision |
| implements | CA-009 | Incrementalist competitive analysis |
