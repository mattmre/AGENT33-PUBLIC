# Trigger Catalog

**Status**: Specification  
**Source**: CA-009 (Incrementalist SolutionWideChangeDetector.cs pattern)

## Overview

This catalog defines all solution-wide triggers for AGENT-33. When any of these files change, the system bypasses incremental processing and processes the specified scope.

## Catalog Format

```python
@dataclass
class TriggerRule:
    """A rule that defines when to trigger broad processing."""
    name: str
    patterns: List[str]  # Glob patterns to match
    scope: Literal["full", "category"]
    categories: List[str]  # Affected categories (if scope=category)
    reason: str  # Human-readable explanation
    priority: int = 0  # Higher = checked first
```

## Full Refresh Triggers

These patterns trigger processing of ALL artifacts:

### Framework Core

```yaml
- name: system-prompt
  patterns:
    - "core/prompts/SYSTEM.md"
    - "core/prompts/GLOBAL_RULES.md"
  scope: full
  reason: "Base system prompt affects all agent behavior"
  priority: 100

- name: policy-pack
  patterns:
    - "core/packs/policy-pack-v1/**"
  scope: full
  reason: "Governance policies affect all artifact validation"
  priority: 100

- name: project-config
  patterns:
    - ".claude/**"
    - "CLAUDE.md"
  scope: full
  reason: "Project-wide AI configuration changed"
  priority: 90

- name: repository-structure
  patterns:
    - "manifest.md"
    - "README.md"
    - "sync-plan.md"
  scope: full
  reason: "Repository structure definition changed"
  priority: 80
```

### Deduplication & Canonicalization

```yaml
- name: dedup-rules
  patterns:
    - "dedup-policy.md"
    - "core/ARTIFACT_INDEX.md"
  scope: full
  reason: "Deduplication rules affect artifact canonicalization"
  priority: 85
```

## Category Triggers

These patterns trigger processing of specific categories:

### Orchestrator Category

```yaml
- name: orchestrator-prompts
  patterns:
    - "core/orchestrator/prompts/**"
  scope: category
  categories: ["orchestrator"]
  reason: "Orchestrator-specific prompts changed"
  priority: 50

- name: orchestrator-agents
  patterns:
    - "core/orchestrator/agents/**"
    - "core/orchestrator/AGENT_REGISTRY.md"
    - "core/orchestrator/AGENT_ROUTING_MAP.md"
  scope: category
  categories: ["orchestrator", "agents"]
  reason: "Agent definitions changed"
  priority: 50
```

### Workflow Category

```yaml
- name: workflow-promotion
  patterns:
    - "core/workflows/PROMOTION_CRITERIA.md"
    - "core/workflows/README.md"
  scope: category
  categories: ["workflows"]
  reason: "Workflow promotion rules changed"
  priority: 50

- name: workflow-templates
  patterns:
    - "core/workflows/PULL_REQUEST_TEMPLATE.md"
    - "core/workflows/ISSUE_TEMPLATE/**"
  scope: category
  categories: ["workflows", "templates"]
  reason: "Workflow templates changed"
  priority: 40
```

### Agent Category

```yaml
- name: agent-registry
  patterns:
    - "core/agents/AGENT_MEMORY_PROTOCOL.md"
    - "core/agents/SESSION_BOUNDARIES.md"
  scope: category
  categories: ["agents"]
  reason: "Agent behavior protocols changed"
  priority: 50
```

### Template Category

```yaml
- name: template-index
  patterns:
    - "core/templates/README.md"
    - "core/templates/TEMPLATE_REGISTRY.md"
  scope: category
  categories: ["templates"]
  reason: "Template index changed"
  priority: 40
```

## Custom Triggers

Teams can define project-specific triggers in `.agent33/triggers.yaml`:

```yaml
# .agent33/triggers.yaml
custom_triggers:
  - name: my-shared-config
    patterns:
      - "config/shared/**"
    scope: category
    categories: ["config"]
    reason: "Shared configuration changed"
    priority: 30
```

## Trigger Matching Logic

```python
class TriggerCatalog:
    """Catalog of all trigger rules."""
    
    def __init__(self, rules: List[TriggerRule]):
        # Sort by priority (highest first)
        self.rules = sorted(rules, key=lambda r: -r.priority)
    
    def find_match(self, file: Path) -> Optional[TriggerRule]:
        """Find first matching trigger rule."""
        file_str = str(file).replace("\\", "/")
        
        for rule in self.rules:
            for pattern in rule.patterns:
                if fnmatch(file_str, pattern):
                    return rule
        
        return None
    
    def all_matches(self, files: Set[Path]) -> List[TriggerMatch]:
        """Find all trigger matches for a set of files."""
        matches = []
        for file in files:
            rule = self.find_match(file)
            if rule:
                matches.append(TriggerMatch(
                    trigger_file=file,
                    trigger_rule=rule.name,
                    scope=rule.scope,
                    affected_categories=rule.categories,
                    reason=rule.reason
                ))
        return matches
```

## Trigger Aggregation

When multiple triggers match, they are aggregated:

```python
def aggregate_triggers(matches: List[TriggerMatch]) -> TriggerResult:
    """
    Aggregate multiple trigger matches.
    
    Rules:
    1. If any trigger has scope="full", result is full refresh
    2. Otherwise, union of all affected categories
    """
    if any(m.scope == "full" for m in matches):
        return TriggerResult(
            scope="full",
            categories=["all"],
            triggers=matches,
            reason="Full refresh: " + matches[0].reason
        )
    
    all_categories = set()
    for m in matches:
        all_categories.update(m.affected_categories)
    
    return TriggerResult(
        scope="category",
        categories=list(all_categories),
        triggers=matches,
        reason=f"Category refresh: {', '.join(all_categories)}"
    )
```

## Escape Hatches

### Force Incremental

Skip trigger detection (use with caution):

```bash
agent-33 run --force-incremental
```

### Force Full

Always do full processing:

```bash
agent-33 run --force-full
```

## Trigger Report

The system logs trigger decisions for auditability:

```python
logger.info(
    "trigger_decision",
    trigger_file=str(match.trigger_file),
    trigger_rule=match.trigger_rule,
    scope=match.scope,
    categories=match.affected_categories,
    reason=match.reason
)
```

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| parent | `README.md` | Triggers overview |
| informs | `../incremental/CHANGE_DETECTION.md` | Bypass incremental |
| loaded-by | `../config-gen/README.md` | Config generation |
