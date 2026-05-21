# Metrics Catalog

**Status**: Specification  
**Source**: CA-015 (Incrementalist competitive analysis)

## Overview

This catalog defines all metrics collected by the AGENT-33 analytics system.

## Metric Types

| Type | Description | Example |
|------|-------------|---------|
| **Counter** | Cumulative count, only increases | `tasks_total` |
| **Gauge** | Current value, can increase/decrease | `queue_depth` |
| **Timer** | Duration measurement | `task_duration_ms` |
| **Histogram** | Distribution of values | `task_duration_distribution` |

## Execution Metrics

### Overall Execution

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `execution_start_time` | Gauge | timestamp | When execution started |
| `execution_end_time` | Gauge | timestamp | When execution ended |
| `execution_duration_ms` | Timer | ms | Total execution duration |
| `execution_status` | Gauge | enum | success/failed/partial |

### Task Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `tasks_total` | Counter | count | Total tasks in execution |
| `tasks_succeeded` | Counter | count | Tasks completed successfully |
| `tasks_failed` | Counter | count | Tasks that failed |
| `tasks_skipped` | Counter | count | Tasks skipped (e.g., dry run) |
| `tasks_timeout` | Counter | count | Tasks that timed out |
| `task_duration_ms` | Timer | ms | Per-task duration |
| `task_retry_count` | Counter | count | Number of retries per task |

### Parallel Execution Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `parallel_limit` | Gauge | count | Configured parallel limit |
| `parallel_active` | Gauge | count | Currently active tasks |
| `parallel_peak` | Gauge | count | Peak concurrent tasks |
| `parallel_utilization` | Gauge | percent | Avg utilization of slots |
| `semaphore_wait_ms` | Timer | ms | Time waiting for semaphore |

### Change Detection Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `changed_files_count` | Gauge | count | Files detected as changed |
| `affected_artifacts_count` | Gauge | count | Artifacts affected |
| `trigger_matched` | Gauge | bool | Whether trigger file matched |
| `detection_duration_ms` | Timer | ms | Change detection time |

### Graph Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `graph_nodes_total` | Gauge | count | Total nodes in graph |
| `graph_edges_total` | Gauge | count | Total edges in graph |
| `graph_depth_max` | Gauge | count | Maximum dependency depth |
| `graph_build_duration_ms` | Timer | ms | Graph build time |

## Labels

Metrics can have labels for filtering:

| Label | Values | Description |
|-------|--------|-------------|
| `task_type` | refinement, validation, etc. | Type of task |
| `artifact_type` | prompt, agent, workflow, etc. | Artifact type |
| `status` | success, failed, timeout, skipped | Task result |
| `level` | 0, 1, 2, ... | Dependency level |

## Collection Implementation

```python
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from contextlib import contextmanager

@dataclass
class Metrics:
    """Container for collected metrics."""
    counters: Dict[str, int] = field(default_factory=dict)
    gauges: Dict[str, float] = field(default_factory=dict)
    timers: Dict[str, List[float]] = field(default_factory=dict)
    
    def increment(self, name: str, value: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + value
    
    def set_gauge(self, name: str, value: float) -> None:
        self.gauges[name] = value
    
    def record_time(self, name: str, duration_ms: float) -> None:
        if name not in self.timers:
            self.timers[name] = []
        self.timers[name].append(duration_ms)
    
    @contextmanager
    def timer(self, name: str):
        start = time.time()
        try:
            yield
        finally:
            duration_ms = (time.time() - start) * 1000
            self.record_time(name, duration_ms)

class MetricsCollector:
    """Collects and exports metrics."""
    
    def __init__(self):
        self.metrics = Metrics()
        self._start_time = None
    
    def start_execution(self) -> None:
        self._start_time = time.time()
        self.metrics.set_gauge("execution_start_time", self._start_time)
    
    def end_execution(self, status: str) -> None:
        end_time = time.time()
        self.metrics.set_gauge("execution_end_time", end_time)
        self.metrics.set_gauge("execution_status", status)
        if self._start_time:
            duration = (end_time - self._start_time) * 1000
            self.metrics.record_time("execution_duration_ms", duration)
    
    def record_task(
        self,
        task_type: str,
        duration_ms: float,
        status: str
    ) -> None:
        self.metrics.increment("tasks_total")
        self.metrics.increment(f"tasks_{status}")
        self.metrics.record_time(f"task_duration_ms", duration_ms)
        self.metrics.record_time(f"task_duration_ms.{task_type}", duration_ms)
    
    def to_dict(self) -> Dict:
        """Export metrics as dictionary."""
        result = {
            "counters": self.metrics.counters,
            "gauges": self.metrics.gauges,
            "timers": {}
        }
        
        for name, values in self.metrics.timers.items():
            result["timers"][name] = {
                "count": len(values),
                "sum": sum(values),
                "min": min(values) if values else 0,
                "max": max(values) if values else 0,
                "avg": sum(values) / len(values) if values else 0
            }
        
        return result
    
    def log_summary(self) -> None:
        """Log human-readable summary."""
        data = self.to_dict()
        
        print("Execution Summary")
        print("=================")
        
        if "execution_duration_ms" in data["timers"]:
            duration = data["timers"]["execution_duration_ms"]["sum"]
            print(f"Duration: {duration/1000:.1f}s")
        
        total = data["counters"].get("tasks_total", 0)
        succeeded = data["counters"].get("tasks_succeeded", 0)
        failed = data["counters"].get("tasks_failed", 0)
        print(f"Tasks: {total} total, {succeeded} succeeded, {failed} failed")
        
        if "task_duration_ms" in data["timers"]:
            avg = data["timers"]["task_duration_ms"]["avg"]
            print(f"Avg task time: {avg/1000:.1f}s")
```

## Output Formats

### Console Summary

```
Execution Summary
=================
Duration: 45.3s
Tasks: 12 total, 11 succeeded, 1 failed
Avg task time: 3.8s
Parallel utilization: 78%
Peak concurrent: 4/4
Change detection: 1.2s (5 files → 12 artifacts)
```

### JSON Export

```json
{
  "collected_at": "2026-01-20T15:45:00Z",
  "counters": {
    "tasks_total": 12,
    "tasks_succeeded": 11,
    "tasks_failed": 1
  },
  "gauges": {
    "parallel_limit": 4,
    "parallel_peak": 4,
    "changed_files_count": 5,
    "affected_artifacts_count": 12
  },
  "timers": {
    "execution_duration_ms": {
      "count": 1,
      "sum": 45300,
      "avg": 45300
    },
    "task_duration_ms": {
      "count": 12,
      "sum": 45600,
      "min": 2100,
      "max": 8900,
      "avg": 3800
    }
  }
}
```

### Structured Log

```json
{"timestamp": "2026-01-20T15:45:00Z", "event": "execution_complete", "duration_ms": 45300, "tasks_total": 12, "tasks_succeeded": 11, "tasks_failed": 1}
```

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| parent | `README.md` | Analytics overview |
| used-by | `../parallel/SEMAPHORE_CONTROL.md` | Task timing |
| used-by | `../modes/DRY_RUN_SPEC.md` | Duration estimation |
| used-by | `../incremental/CHANGE_DETECTION.md` | Detection timing |
