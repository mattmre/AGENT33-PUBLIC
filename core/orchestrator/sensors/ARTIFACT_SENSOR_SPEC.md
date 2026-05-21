# Artifact Sensor Specification

**Status**: Specification
**Sources**: Dagster (CA-119 to CA-130), Kestra (CA-041 to CA-052)

## Overview

This document specifies the event-driven sensor system for AGENT-33. Sensors monitor for changes in artifacts, files, schedules, and external systems, then trigger workflows in response. They are the primary mechanism for reactive, event-driven orchestration.

## Sensor Definition Schema

```yaml
sensor:
  id: string
  name: string
  type: file_change | git_commit | schedule | webhook | asset_materialized | manual
  enabled: boolean
  trigger:
    condition: expression
    debounce: duration (e.g., "5m" - ignore re-triggers within window)
    filter: expression (only trigger for matching events)
  target:
    workflow: workflow_id
    inputs: {key: value_or_expression}
  evaluation:
    mode: polling | event_driven
    interval: duration (for polling)
  error_handling:
    on_failure: retry | alert | disable
    max_retries: number
    alert_after: number (consecutive failures)
  metadata:
    owner: string
    tags: [string]
    last_triggered: ISO-8601
    trigger_count: number
```

## Sensor Types

### file_change

Triggers when a file or directory is created, modified, or deleted.

```yaml
sensor:
  id: sensor-file-prompt-change
  name: "Prompt File Change"
  type: file_change
  enabled: true
  trigger:
    condition: "file.modified('core/prompts/**/*.md')"
    debounce: "5m"
    filter: "not file.path.endswith('.tmp')"
  target:
    workflow: prompt-validation
    inputs:
      changed_file: "{{ event.file_path }}"
      change_type: "{{ event.change_type }}"
  evaluation:
    mode: polling
    interval: "30s"
```

### git_commit

Triggers when new commits are pushed to a branch or match certain patterns.

```yaml
sensor:
  id: sensor-git-main-push
  name: "Main Branch Push"
  type: git_commit
  enabled: true
  trigger:
    condition: "git.branch == 'main'"
    debounce: "1m"
    filter: "git.files_changed.any(f => f.startsWith('core/'))"
  target:
    workflow: integration-validation
    inputs:
      commit_sha: "{{ event.commit_sha }}"
      author: "{{ event.author }}"
      changed_files: "{{ event.files_changed }}"
  evaluation:
    mode: polling
    interval: "60s"
```

### schedule

Triggers on a cron schedule or at fixed intervals.

```yaml
sensor:
  id: sensor-nightly-quality
  name: "Nightly Quality Check"
  type: schedule
  enabled: true
  trigger:
    condition: "cron('0 2 * * *')"
    debounce: "0s"
    filter: ""
  target:
    workflow: quality-sweep
    inputs:
      scope: "full"
      timestamp: "{{ now() }}"
  evaluation:
    mode: event_driven
    interval: ""
```

### webhook

Triggers when an external HTTP request is received at a registered endpoint.

```yaml
sensor:
  id: sensor-webhook-deploy
  name: "Deploy Webhook"
  type: webhook
  enabled: true
  trigger:
    condition: "webhook.method == 'POST'"
    debounce: "10s"
    filter: "webhook.headers['X-Deploy-Key'] == secret('deploy_key')"
  target:
    workflow: deploy-pipeline
    inputs:
      environment: "{{ webhook.body.environment }}"
      version: "{{ webhook.body.version }}"
  evaluation:
    mode: event_driven
    interval: ""
```

### asset_materialized

Triggers when an asset in the lineage graph is materialized (created or updated).

```yaml
sensor:
  id: sensor-asset-prompt-ready
  name: "Prompt Asset Ready"
  type: asset_materialized
  enabled: true
  trigger:
    condition: "asset.type == 'prompt' and asset.quality_score >= 0.8"
    debounce: "2m"
    filter: "asset.partition == 'production'"
  target:
    workflow: prompt-deployment
    inputs:
      asset_id: "{{ event.asset_id }}"
      version: "{{ event.version }}"
      quality_score: "{{ event.quality_score }}"
  evaluation:
    mode: event_driven
    interval: ""
```

### manual

Triggers only when explicitly invoked by a user or another workflow.

```yaml
sensor:
  id: sensor-manual-hotfix
  name: "Manual Hotfix Trigger"
  type: manual
  enabled: true
  trigger:
    condition: "true"
    debounce: "0s"
    filter: ""
  target:
    workflow: hotfix-pipeline
    inputs:
      reason: "{{ manual.reason }}"
      requested_by: "{{ manual.user }}"
  evaluation:
    mode: event_driven
    interval: ""
```

## Data Model

```python
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from enum import Enum
from datetime import datetime, timedelta


class SensorType(Enum):
    FILE_CHANGE = "file_change"
    GIT_COMMIT = "git_commit"
    SCHEDULE = "schedule"
    WEBHOOK = "webhook"
    ASSET_MATERIALIZED = "asset_materialized"
    MANUAL = "manual"


class EvaluationMode(Enum):
    POLLING = "polling"
    EVENT_DRIVEN = "event_driven"


class FailureAction(Enum):
    RETRY = "retry"
    ALERT = "alert"
    DISABLE = "disable"


class SensorState(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass
class TriggerConfig:
    """Defines when and how a sensor fires."""
    condition: str                    # Expression to evaluate
    debounce: timedelta               # Minimum interval between triggers
    filter: str = ""                  # Additional filter expression


@dataclass
class TargetConfig:
    """Defines what the sensor triggers."""
    workflow: str                     # Target workflow ID
    inputs: Dict[str, str] = field(default_factory=dict)  # Input mappings


@dataclass
class EvaluationConfig:
    """Defines how the sensor checks for events."""
    mode: EvaluationMode
    interval: Optional[timedelta] = None  # For polling mode


@dataclass
class ErrorConfig:
    """Defines error handling behavior."""
    on_failure: FailureAction = FailureAction.RETRY
    max_retries: int = 3
    alert_after: int = 3              # Consecutive failures before alerting


@dataclass
class SensorMetrics:
    """Runtime metrics for a sensor."""
    last_triggered: Optional[str] = None  # ISO-8601
    last_evaluated: Optional[str] = None  # ISO-8601
    trigger_count: int = 0
    error_count: int = 0
    consecutive_failures: int = 0


@dataclass
class Sensor:
    """A fully defined sensor."""
    id: str
    name: str
    type: SensorType
    enabled: bool
    trigger: TriggerConfig
    target: TargetConfig
    evaluation: EvaluationConfig
    error_handling: ErrorConfig = field(default_factory=ErrorConfig)
    owner: str = ""
    tags: List[str] = field(default_factory=list)
    state: SensorState = SensorState.ACTIVE
    metrics: SensorMetrics = field(default_factory=SensorMetrics)
```

## Debounce and Deduplication

Debouncing prevents a sensor from firing repeatedly for rapid successive events. Deduplication ensures the same logical event does not trigger multiple workflow runs.

```python
@dataclass
class DebounceState:
    """Tracks debounce windows per sensor."""
    last_fire_time: Dict[str, datetime] = field(default_factory=dict)

    def should_fire(self, sensor: Sensor) -> bool:
        """
        Check if enough time has passed since the last trigger.

        Returns:
            True if the debounce window has elapsed.
        """
        last = self.last_fire_time.get(sensor.id)
        if last is None:
            return True
        elapsed = datetime.utcnow() - last
        return elapsed >= sensor.trigger.debounce

    def record_fire(self, sensor: Sensor) -> None:
        """Record that the sensor just fired."""
        self.last_fire_time[sensor.id] = datetime.utcnow()


@dataclass
class DeduplicationState:
    """Tracks event fingerprints to prevent duplicate triggers."""
    seen_events: Dict[str, set] = field(default_factory=dict)
    window: timedelta = field(default_factory=lambda: timedelta(hours=1))

    def is_duplicate(self, sensor_id: str, event_fingerprint: str) -> bool:
        """Check if this event has already been processed."""
        seen = self.seen_events.setdefault(sensor_id, set())
        if event_fingerprint in seen:
            return True
        seen.add(event_fingerprint)
        return False
```

## Sensor Chaining

Sensors can be chained so that the output of one workflow triggers another sensor. This enables multi-stage reactive pipelines.

```yaml
# Sensor A: Watch for file changes, trigger build workflow
sensor:
  id: sensor-chain-source
  name: "Source Change"
  type: file_change
  enabled: true
  trigger:
    condition: "file.modified('src/**/*.py')"
    debounce: "10s"
  target:
    workflow: build-artifacts

# Sensor B: Watch for build artifacts, trigger deploy workflow
sensor:
  id: sensor-chain-deploy
  name: "Artifact Built"
  type: asset_materialized
  enabled: true
  trigger:
    condition: "asset.type == 'build_artifact' and asset.quality_score >= 0.9"
    debounce: "1m"
  target:
    workflow: deploy-staging
    inputs:
      artifact_id: "{{ event.asset_id }}"
```

```python
def resolve_sensor_chain(
    sensors: List[Sensor],
    workflows: Dict[str, Any]
) -> List[List[str]]:
    """
    Identify chains of sensors linked through workflow outputs.

    A chain exists when sensor A targets a workflow whose output asset
    is watched by sensor B.

    Returns:
        List of chains, each a list of sensor IDs in firing order.
    """
    # Map: workflow_id -> list of sensors watching its outputs
    output_watchers: Dict[str, List[str]] = {}
    for sensor in sensors:
        if sensor.type == SensorType.ASSET_MATERIALIZED:
            # Determine which workflows produce the watched asset type
            for wf_id, wf in workflows.items():
                for output_asset in wf.get("outputs", []):
                    output_watchers.setdefault(wf_id, []).append(sensor.id)

    # Build chains
    chains = []
    for sensor in sensors:
        target_wf = sensor.target.workflow
        if target_wf in output_watchers:
            for downstream_sensor_id in output_watchers[target_wf]:
                chains.append([sensor.id, downstream_sensor_id])

    return chains
```

## Error Handling

```python
@dataclass
class SensorError:
    """A recorded sensor evaluation error."""
    sensor_id: str
    timestamp: str          # ISO-8601
    error_type: str
    message: str
    stack_trace: Optional[str] = None


def handle_sensor_failure(
    sensor: Sensor,
    error: SensorError,
    registry: "SensorRegistry"
) -> None:
    """
    Apply the sensor's error handling policy.

    Increments failure counters and takes action based on configuration:
    - retry: Re-evaluate on next cycle (default behavior).
    - alert: Send alert notification after threshold consecutive failures.
    - disable: Disable the sensor after max retries exceeded.
    """
    sensor.metrics.error_count += 1
    sensor.metrics.consecutive_failures += 1

    if sensor.metrics.consecutive_failures >= sensor.error_handling.alert_after:
        registry.send_alert(
            sensor_id=sensor.id,
            message=f"Sensor '{sensor.name}' has failed "
                    f"{sensor.metrics.consecutive_failures} times: "
                    f"{error.message}",
        )

    if sensor.error_handling.on_failure == FailureAction.DISABLE:
        if sensor.metrics.consecutive_failures > sensor.error_handling.max_retries:
            sensor.state = SensorState.DISABLED
            sensor.enabled = False
            registry.send_alert(
                sensor_id=sensor.id,
                message=f"Sensor '{sensor.name}' disabled after "
                        f"{sensor.error_handling.max_retries} retries.",
            )
```

## Sensor Registry

```python
@dataclass
class SensorRegistry:
    """Central registry of all sensors with lifecycle management."""
    sensors: Dict[str, Sensor] = field(default_factory=dict)

    def register(self, sensor: Sensor) -> None:
        """Add a sensor to the registry."""
        self.sensors[sensor.id] = sensor

    def unregister(self, sensor_id: str) -> None:
        """Remove a sensor from the registry."""
        self.sensors.pop(sensor_id, None)

    def enable(self, sensor_id: str) -> None:
        """Enable a sensor."""
        if sensor_id in self.sensors:
            self.sensors[sensor_id].enabled = True
            self.sensors[sensor_id].state = SensorState.ACTIVE

    def disable(self, sensor_id: str) -> None:
        """Disable a sensor."""
        if sensor_id in self.sensors:
            self.sensors[sensor_id].enabled = False
            self.sensors[sensor_id].state = SensorState.DISABLED

    def list_active(self) -> List[Sensor]:
        """Return all active, enabled sensors."""
        return [
            s for s in self.sensors.values()
            if s.enabled and s.state == SensorState.ACTIVE
        ]

    def list_by_type(self, sensor_type: SensorType) -> List[Sensor]:
        """Return all sensors of a given type."""
        return [
            s for s in self.sensors.values()
            if s.type == sensor_type
        ]

    def get_status_summary(self) -> Dict[str, Any]:
        """Return a summary of all sensor statuses."""
        by_state = {}
        for sensor in self.sensors.values():
            state = sensor.state.value
            by_state.setdefault(state, []).append(sensor.id)

        return {
            "total": len(self.sensors),
            "by_state": by_state,
            "by_type": {
                t.value: len(self.list_by_type(t))
                for t in SensorType
            },
        }

    def send_alert(self, sensor_id: str, message: str) -> None:
        """Send an alert for a sensor issue. Implementation varies by deployment."""
        # Hook for alert integration (Slack, email, PagerDuty, etc.)
        pass
```

## CLI Commands

```bash
# Sensor management
agent-33 sensor list [--type file_change] [--state active]
agent-33 sensor status
agent-33 sensor enable <sensor-id>
agent-33 sensor disable <sensor-id>

# Manual trigger
agent-33 sensor trigger <sensor-id> [--reason "hotfix needed"]

# Evaluation
agent-33 sensor evaluate <sensor-id>    # Force single evaluation
agent-33 sensor history <sensor-id>     # Show trigger history

# Registry
agent-33 sensor register <sensor-file.yaml>
agent-33 sensor unregister <sensor-id>

# Debugging
agent-33 sensor chain                   # Show sensor chains
agent-33 sensor dry-run <sensor-id>     # Evaluate without triggering
```

## Integration Points

### Change Detection (CA-007)

File change sensors build on the incremental change detection system. When the change detector identifies modified files, it emits events that `file_change` sensors consume.

### Triggers (CA-009)

Sensors are the evaluation layer on top of the trigger system. A trigger defines what happens; a sensor defines when and why the trigger fires.

### Asset-First Schema

`asset_materialized` sensors integrate directly with the asset schema. When an asset is materialized (recorded in the lineage graph), the sensor evaluator checks all active `asset_materialized` sensors for matching conditions.

### Lineage Tracking

Sensor activations are recorded in the lineage graph as provenance events. This enables tracing why a workflow ran and what external event caused it.

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| uses | `../lineage/LINEAGE_TRACKING_SPEC.md` | Records sensor events in lineage |
| uses | `../dependencies/DEPENDENCY_GRAPH_SPEC.md` | Resolves target workflows |
| integrates | `../incremental/ARTIFACT_GRAPH.md` | Asset materialization events |
| used-by | `../decision/DECISION_ROUTING_SPEC.md` | Sensor output feeds decisions |
| sources | Dagster CA-119 to CA-130 | Asset sensor patterns |
| sources | Kestra CA-041 to CA-052 | Event-driven trigger patterns |
