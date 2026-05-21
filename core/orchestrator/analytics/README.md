# Execution Timing and Analytics

**Status**: Specification  
**Source**: CA-015 (Incrementalist RunDotNetCommandTask.cs timing pattern)  
**Priority**: Low

## Overview

The Analytics system captures execution timing, success rates, and resource usage metrics. This enables performance optimization and capacity planning.

## Entry Points

- `METRICS_CATALOG.md` - Complete metrics catalog

## Core Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `execution_duration_ms` | Timer | Total execution time |
| `task_duration_ms` | Timer | Per-task execution time |
| `tasks_total` | Counter | Total tasks processed |
| `tasks_succeeded` | Counter | Successful tasks |
| `tasks_failed` | Counter | Failed tasks |
| `parallel_utilization` | Gauge | % of parallel slots used |

## Quick Example

```python
from orchestrator.analytics import MetricsCollector

metrics = MetricsCollector()

with metrics.timer("execution"):
    results = await executor.run_all(tasks)

metrics.log_summary()
# Output:
# Execution Summary
# =================
# Duration: 45.3s
# Tasks: 12 total, 11 succeeded, 1 failed
# Avg task time: 3.8s
# Parallel utilization: 78%
```

## Output Formats

```bash
# Console summary (default)
agent-33 run --analytics

# JSON metrics file
agent-33 run --analytics --metrics-file metrics.json

# Structured log format
agent-33 run --analytics --log-format json
```

## Use Cases

1. **Performance Tuning** - Identify slow tasks
2. **Capacity Planning** - Estimate resource needs
3. **Trend Analysis** - Track performance over time
4. **SLA Monitoring** - Alert on threshold breaches

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| depends-on | `METRICS_CATALOG.md` | All metrics defined |
| used-by | `../parallel/README.md` | Parallel execution timing |
| used-by | `../modes/DRY_RUN_SPEC.md` | Duration estimation |
| implements | CA-015 | Incrementalist competitive analysis |
