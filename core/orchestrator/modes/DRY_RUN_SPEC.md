# Dry Run Mode Specification

**Status**: Specification  
**Source**: CA-011 (Incrementalist competitive analysis)

## Overview

This document specifies the behavior of dry run mode in the AGENT-33 orchestration engine. Dry run simulates execution without side effects, producing a detailed execution plan.

## Behavior Definition

### What Runs Normally

| Component | Behavior in Dry Run |
|-----------|---------------------|
| Change detection | Full analysis runs |
| Trigger matching | Full matching runs |
| Dependency resolution | Full graph traversal |
| Artifact filtering | Full filtering runs |
| Execution planning | Full planning runs |

### What Is Simulated

| Component | Behavior in Dry Run |
|-----------|---------------------|
| Agent invocation | Logged, not executed |
| File writes | Logged, not executed |
| External commands | Logged, not executed |
| API calls | Logged, not executed |
| Evidence capture | Simulated entries created |

## Implementation

```python
@dataclass
class DryRunConfig:
    """Configuration for dry run mode."""
    enabled: bool = False
    output_plan: bool = True
    output_file: Optional[str] = None
    format: Literal["markdown", "json", "yaml"] = "markdown"
    include_estimates: bool = True

class DryRunExecutor:
    """Executor that simulates without side effects."""
    
    def __init__(self, config: DryRunConfig):
        self.config = config
        self.plan = ExecutionPlan()
    
    async def run(
        self,
        tasks: List[AgentTask],
        graph: ArtifactGraph
    ) -> DryRunResult:
        """
        Simulate execution and generate plan.
        """
        # Build execution levels
        levels = topological_levels(tasks, graph)
        
        for level_num, level in enumerate(levels):
            for task in level:
                self.plan.add_step(DryRunStep(
                    level=level_num,
                    task=task,
                    dependencies=get_dependencies(task, graph),
                    estimated_duration=estimate_duration(task),
                    would_modify=predict_modifications(task)
                ))
        
        return DryRunResult(
            plan=self.plan,
            total_tasks=len(tasks),
            total_levels=len(levels),
            estimated_duration=self.plan.total_estimated_duration()
        )
```

## Output Formats

### Markdown Format

```markdown
# Execution Plan (Dry Run)

**Generated**: 2026-01-20T15:30:00Z  
**Mode**: parallel (limit: 4)  
**Total Artifacts**: 12

## Summary

| Metric | Value |
|--------|-------|
| Changed Files | 5 |
| Affected Artifacts | 12 |
| Execution Levels | 3 |
| Est. Duration (Sequential) | 15m |
| Est. Duration (Parallel) | 5m |

## Trigger Analysis

No solution-wide triggers matched. Using incremental mode.

## Execution Plan

### Level 0 (Root Dependencies)

| Step | Artifact | Agent | Est. Duration |
|------|----------|-------|---------------|
| 1 | `core/prompts/SYSTEM.md` | refinement | 60s |
| 2 | `core/prompts/WORKER.md` | refinement | 60s |

### Level 1 (Depends on Level 0)

| Step | Artifact | Agent | Est. Duration | Depends On |
|------|----------|-------|---------------|------------|
| 3 | `core/agents/worker.md` | refinement | 45s | Step 1 |
| 4 | `core/agents/reviewer.md` | refinement | 45s | Step 1 |

## Would Modify

These files would be modified during execution:

- `core/prompts/SYSTEM.md` (refinement updates)
- `core/agents/worker.md` (dependency sync)
```

### JSON Format

```json
{
  "generated": "2026-01-20T15:30:00Z",
  "mode": "parallel",
  "parallel_limit": 4,
  "summary": {
    "changed_files": 5,
    "affected_artifacts": 12,
    "levels": 3,
    "estimated_sequential_ms": 900000,
    "estimated_parallel_ms": 300000
  },
  "triggers": {
    "matched": false,
    "scope": "incremental"
  },
  "levels": [
    {
      "level": 0,
      "steps": [
        {
          "step": 1,
          "artifact": "core/prompts/SYSTEM.md",
          "agent": "refinement",
          "estimated_ms": 60000,
          "dependencies": []
        }
      ]
    }
  ],
  "would_modify": [
    "core/prompts/SYSTEM.md",
    "core/agents/worker.md"
  ]
}
```

## CLI Options

```bash
# Enable dry run
agent-33 run --dry-run

# Output to file
agent-33 run --dry-run --plan-output execution-plan.md

# JSON format
agent-33 run --dry-run --format json

# Include duration estimates
agent-33 run --dry-run --include-estimates

# Show what would be modified
agent-33 run --dry-run --show-modifications
```

## Duration Estimation

Estimates are based on:

1. **Historical data** - Past execution times for similar artifacts
2. **Artifact size** - Larger artifacts take longer
3. **Agent type** - Different agents have different baselines
4. **Dependency depth** - More dependencies = more time

```python
def estimate_duration(task: AgentTask) -> int:
    """
    Estimate task duration in milliseconds.
    """
    base_ms = AGENT_BASELINES.get(task.agent, 60000)
    
    # Adjust for artifact size
    artifact_size = get_artifact_size(task.artifact)
    size_factor = 1.0 + (artifact_size / 10000)  # 10KB baseline
    
    # Adjust for complexity
    complexity = estimate_complexity(task.artifact)
    complexity_factor = 1.0 + (complexity * 0.2)
    
    return int(base_ms * size_factor * complexity_factor)
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Dry run completed, no issues |
| 1 | Dry run completed, would have failures |
| 2 | Dry run failed (detection error) |

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| parent | `README.md` | Modes overview |
| uses | `../incremental/CHANGE_DETECTION.md` | Change detection |
| uses | `../incremental/ARTIFACT_GRAPH.md` | Dependency graph |
| uses | `../analytics/METRICS_CATALOG.md` | Duration estimation |
