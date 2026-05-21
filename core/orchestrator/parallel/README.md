# Parallel Execution Control

**Status**: Specification  
**Source**: CA-008 (Incrementalist RunDotNetCommandTask.cs pattern)  
**Priority**: High

## Overview

The Parallel Execution Control system enables AGENT-33 to run multiple agents concurrently while respecting resource limits and handling failures gracefully.

## Entry Points

- `SEMAPHORE_CONTROL.md` - Semaphore-based concurrency limiting
- `EXECUTION_MODES.md` - Sequential, parallel, and hybrid modes

## Core Concepts

### Execution Model

```
Tasks → Semaphore Gate → Parallel Workers → Result Aggregation
   │          │                  │                  │
   ▼          ▼                  ▼                  ▼
 Queue    Limit=N          Async Exec         Success/Fail
```

### Key Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `parallel` | bool | false | Enable parallel execution |
| `parallel_limit` | int | 4 | Maximum concurrent tasks |
| `timeout_seconds` | int | 300 | Per-task timeout |
| `continue_on_error` | bool | false | Continue if task fails |
| `fail_fast` | bool | true | Stop on first failure |

## Quick Example

```python
from orchestrator.parallel import ParallelExecutor

executor = ParallelExecutor(
    parallel_limit=4,
    timeout_seconds=300,
    continue_on_error=True
)

results = await executor.run_all([
    AgentTask("refinement", artifact="core/prompts/SYSTEM.md"),
    AgentTask("validation", artifact="core/agents/worker.md"),
    AgentTask("refinement", artifact="core/templates/README.md"),
])

print(f"Completed: {results.succeeded}/{results.total}")
if results.failed:
    print(f"Failed: {[f.task.artifact for f in results.failed]}")
```

## Failure Handling

### Continue-on-Error Mode

When `continue_on_error=True`:
1. Failed tasks are recorded but don't stop execution
2. All tasks complete (or timeout)
3. Aggregated failure report at the end

### Fail-Fast Mode

When `fail_fast=True` (default):
1. First failure triggers cancellation
2. In-flight tasks receive cancellation signal
3. Pending tasks are not started

### Timeout Handling

Each task has its own timeout:
1. Task exceeds `timeout_seconds`
2. Task is cancelled
3. Recorded as `TimeoutError` in results

## Result Types

```python
@dataclass
class TaskResult:
    """Result of a single task execution."""
    task: AgentTask
    status: Literal["success", "failed", "timeout", "cancelled"]
    duration_ms: int
    output: Optional[str] = None
    error: Optional[str] = None

@dataclass
class ExecutionResults:
    """Aggregated results from parallel execution."""
    total: int
    succeeded: List[TaskResult]
    failed: List[TaskResult]
    cancelled: List[TaskResult]
    duration_ms: int
    
    @property
    def success_rate(self) -> float:
        return len(self.succeeded) / self.total if self.total > 0 else 0.0
```

## CLI Integration

```bash
# Run agents in parallel
agent-33 run --parallel --parallel-limit 4

# Continue on errors
agent-33 run --parallel --continue-on-error

# Set timeout
agent-33 run --parallel --timeout 600
```

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| depends-on | `SEMAPHORE_CONTROL.md` | Concurrency implementation |
| depends-on | `EXECUTION_MODES.md` | Mode specifications |
| uses | `../analytics/METRICS_CATALOG.md` | Timing metrics |
| implements | CA-008 | Incrementalist competitive analysis |
