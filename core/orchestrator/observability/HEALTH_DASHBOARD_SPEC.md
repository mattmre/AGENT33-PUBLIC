# Health Dashboard Specification

Purpose: Define the health monitoring dashboard for orchestration system observability.

Sources: Dagster (CA-119 to CA-130), all observability features across analyses

Related docs:
- `core/orchestrator/TRACE_SCHEMA.md` (trace schema and artifact retention)
- `core/orchestrator/analytics/METRICS_CATALOG.md` (metrics definitions)
- `core/orchestrator/handoff/EVIDENCE_CAPTURE.md` (evidence template)
- `core/orchestrator/testing/WORKFLOW_TESTING_FRAMEWORK.md` (test result feeds)
- `core/orchestrator/plugins/PLUGIN_REGISTRY_SPEC.md` (plugin health monitoring)

---

## Overview

The health dashboard provides a unified view of the AGENT-33 orchestration system's operational status. It surfaces real-time metrics, historical trends, active alerts, and dependency health to operators. The dashboard is the primary interface for understanding whether the system is operating correctly and for diagnosing problems when it is not.

## Dashboard Architecture

```
Data Sources                    Aggregation              Presentation
-----------                    -----------              ------------
Trace Schema  ----+
                  |
Metrics Store ----+--> Metric Aggregator --> Dashboard API --> Dashboard UI
                  |                                       --> Status Page
Health Checks ----+                                       --> Alert Router
                  |
Test Results  ----+
```

### Data Flow

1. **Collection**: Trace events, metrics, health check results, and test outcomes are emitted by system components.
2. **Aggregation**: The metric aggregator computes rollups (1-minute, 5-minute, 1-hour, 24-hour windows).
3. **Storage**: Aggregated metrics are stored in a time-series format with configurable retention.
4. **Presentation**: The dashboard API serves current and historical data to the UI and status page.
5. **Alerting**: The alert router evaluates rules against aggregated metrics and dispatches notifications.

### Retention Policy

| Resolution | Retention |
|------------|-----------|
| Raw events | 7 days |
| 1-minute rollups | 30 days |
| 5-minute rollups | 90 days |
| 1-hour rollups | 1 year |
| 24-hour rollups | Indefinite |

## Dashboard Panels

### System Health

Displays the overall health of the orchestration infrastructure.

```yaml
panel:
  name: "System Health"
  layout: grid_2x2
  refresh_interval: 30s
  widgets:
    - type: gauge
      metric: uptime_percentage
      label: "Uptime"
      thresholds: {green: 99.9, yellow: 99.0, red: 0}
      unit: "%"
    - type: gauge
      metric: cpu_utilization
      label: "CPU"
      thresholds: {green: 70, yellow: 85, red: 95}
      unit: "%"
    - type: gauge
      metric: memory_utilization
      label: "Memory"
      thresholds: {green: 70, yellow: 85, red: 95}
      unit: "%"
    - type: gauge
      metric: queue_depth
      label: "Queue Depth"
      thresholds: {green: 50, yellow: 100, red: 200}
      unit: "tasks"
    - type: timeseries
      metrics: [cpu_utilization, memory_utilization]
      label: "Resource Usage (24h)"
      window: 24h
      resolution: 5m
    - type: timeseries
      metric: queue_depth
      label: "Queue Depth (24h)"
      window: 24h
      resolution: 1m
```

### Workflow Status

Displays the state of workflow executions.

```yaml
panel:
  name: "Workflow Status"
  layout: grid_2x3
  refresh_interval: 60s
  widgets:
    - type: counter
      metric: active_workflows
      label: "Active Workflows"
      color: blue
    - type: counter
      metric: completed_today
      label: "Completed Today"
      color: green
    - type: counter
      metric: failed_today
      label: "Failed Today"
      color: red
      alert_if: "> 0"
    - type: histogram
      metric: workflow_duration_ms
      label: "Duration Distribution (24h)"
      window: 24h
      buckets: [1000, 5000, 15000, 30000, 60000, 300000]
    - type: table
      metric: recent_workflows
      label: "Recent Workflows"
      columns: [workflow_id, status, started_at, duration, stage_count]
      limit: 20
      sort: started_at_desc
    - type: timeseries
      metrics: [completed_per_hour, failed_per_hour]
      label: "Throughput (24h)"
      window: 24h
      resolution: 1h
```

### Agent Activity

Displays agent utilization and handoff patterns.

```yaml
panel:
  name: "Agent Activity"
  layout: grid_2x2
  refresh_interval: 30s
  widgets:
    - type: counter
      metric: active_agents
      label: "Active Agents"
      color: green
    - type: counter
      metric: idle_agents
      label: "Idle Agents"
      color: gray
    - type: counter
      metric: handoffs_per_hour
      label: "Handoffs/Hour"
      color: blue
    - type: table
      metric: agent_status
      label: "Agent Status"
      columns: [agent_name, role, status, current_task, uptime]
      sort: status_asc
    - type: heatmap
      metric: handoff_matrix
      label: "Handoff Heatmap"
      x_axis: source_agent
      y_axis: target_agent
      value: handoff_count
      window: 24h
    - type: timeseries
      metric: agent_utilization
      label: "Utilization (24h)"
      window: 24h
      resolution: 5m
      group_by: agent_role
```

### Error Rates

Displays error frequency, patterns, and trends.

```yaml
panel:
  name: "Error Rates"
  layout: grid_2x2
  refresh_interval: 30s
  widgets:
    - type: gauge
      metric: error_rate_1h
      label: "Error Rate (1h)"
      thresholds: {green: 1, yellow: 5, red: 10}
      unit: "%"
    - type: gauge
      metric: error_rate_24h
      label: "Error Rate (24h)"
      thresholds: {green: 1, yellow: 5, red: 10}
      unit: "%"
    - type: table
      metric: top_errors
      label: "Top Errors (24h)"
      columns: [error_type, count, last_seen, affected_workflows]
      sort: count_desc
      limit: 10
    - type: timeseries
      metric: error_count
      label: "Errors Over Time (7d)"
      window: 7d
      resolution: 1h
      group_by: error_type
```

### Plugin Health

Displays the status of registered plugins.

```yaml
panel:
  name: "Plugin Health"
  layout: grid_1x2
  refresh_interval: 60s
  widgets:
    - type: table
      metric: plugin_status
      label: "Plugin Status"
      columns: [plugin_name, version, type, status, invocations_24h, error_rate, avg_latency_ms]
      sort: status_asc
    - type: timeseries
      metric: plugin_latency
      label: "Plugin Latency (24h)"
      window: 24h
      resolution: 5m
      group_by: plugin_name
```

## Health Check Endpoints

Health checks provide machine-readable signals for load balancers, orchestration platforms, and monitoring systems.

### Endpoint Definitions

```yaml
health_checks:
  - name: readiness
    endpoint: /health/ready
    method: GET
    interval: 10s
    timeout: 5s
    description: >
      Returns 200 when the system is ready to accept work.
      Returns 503 during startup, shutdown, or when dependencies are unavailable.
    checks:
      - name: orchestrator_initialized
        description: Core orchestrator has completed startup
      - name: plugin_registry_loaded
        description: Plugin registry has been loaded and validated
      - name: queue_accessible
        description: Task queue is reachable and accepting writes
    response_schema:
      status: ready | not_ready
      checks:
        - name: string
          status: pass | fail
          message: string
      timestamp: ISO-8601

  - name: liveness
    endpoint: /health/live
    method: GET
    interval: 30s
    timeout: 5s
    description: >
      Returns 200 when the process is alive and not deadlocked.
      Returns 503 if the process is unresponsive or in a failed state.
    checks:
      - name: process_responsive
        description: Main event loop is processing events
      - name: no_deadlock
        description: No thread or process deadlock detected
    response_schema:
      status: alive | dead
      uptime_seconds: number
      timestamp: ISO-8601

  - name: dependency_health
    endpoint: /health/dependencies
    method: GET
    interval: 60s
    timeout: 10s
    description: >
      Returns the health status of all external dependencies.
    checks:
      - name: trace_store
        description: Trace storage backend is reachable
        type: connection
      - name: metrics_store
        description: Metrics storage backend is reachable
        type: connection
      - name: plugin_sandboxes
        description: Plugin sandbox runtime is available
        type: connection
    response_schema:
      status: healthy | degraded | unhealthy
      dependencies:
        - name: string
          status: healthy | degraded | unhealthy
          latency_ms: number
          last_checked: ISO-8601
          message: string
      timestamp: ISO-8601
```

### Health Status Aggregation

The overall system status is computed from individual checks.

| Condition | Overall Status |
|-----------|---------------|
| All checks pass | `healthy` |
| At least one non-critical check fails | `degraded` |
| Any critical check fails | `unhealthy` |
| Liveness check fails | `dead` (triggers restart) |

## Alerting Rules

### Alert Definition Schema

```yaml
alert:
  name: string                        # unique alert identifier
  description: string                 # what this alert detects
  condition: expression               # boolean expression over metrics
  evaluation_interval: duration       # how often to evaluate (e.g., 30s)
  severity: critical | high | medium | low | info
  notify:
    channels: [string]                # notification channels (e.g., slack, email, pager)
    recipients: [string]              # roles or individuals
  cooldown: duration                  # minimum time between repeated alerts (e.g., 15m)
  auto_resolve: boolean               # automatically resolve when condition clears
  runbook_url: string                 # link to remediation instructions
  tags: [string]                      # categorization tags
```

### Built-in Alert Rules

```yaml
alerts:
  - name: high_error_rate
    description: "Error rate exceeded 5% over the last hour"
    condition: "error_rate_1h > 5"
    evaluation_interval: 1m
    severity: high
    notify:
      channels: [slack]
      recipients: [maintainer, oncall]
    cooldown: 15m
    auto_resolve: true
    runbook_url: "/runbooks/high-error-rate"

  - name: queue_backlog
    description: "Task queue depth exceeded 100"
    condition: "queue_depth > 100"
    evaluation_interval: 30s
    severity: medium
    notify:
      channels: [slack]
      recipients: [orchestrator]
    cooldown: 10m
    auto_resolve: true
    runbook_url: "/runbooks/queue-backlog"

  - name: workflow_stuck
    description: "A workflow has been in the same stage for over 30 minutes"
    condition: "max(workflow_stage_duration_seconds) > 1800"
    evaluation_interval: 5m
    severity: high
    notify:
      channels: [slack, email]
      recipients: [maintainer]
    cooldown: 30m
    auto_resolve: true
    runbook_url: "/runbooks/stuck-workflow"

  - name: agent_all_idle
    description: "All agents have been idle for over 10 minutes while queue is non-empty"
    condition: "active_agents == 0 and queue_depth > 0"
    evaluation_interval: 1m
    severity: critical
    notify:
      channels: [slack, pager]
      recipients: [oncall]
    cooldown: 5m
    auto_resolve: true
    runbook_url: "/runbooks/agents-idle"

  - name: health_check_failure
    description: "A critical health check has failed"
    condition: "health_status == 'unhealthy'"
    evaluation_interval: 10s
    severity: critical
    notify:
      channels: [slack, pager]
      recipients: [oncall]
    cooldown: 5m
    auto_resolve: true
    runbook_url: "/runbooks/health-check-failure"

  - name: plugin_high_error_rate
    description: "A plugin's error rate exceeded 10% over the last hour"
    condition: "max(plugin_error_rate_1h) > 10"
    evaluation_interval: 5m
    severity: medium
    notify:
      channels: [slack]
      recipients: [maintainer]
    cooldown: 15m
    auto_resolve: true
    runbook_url: "/runbooks/plugin-errors"

  - name: disk_space_low
    description: "Available disk space below 10%"
    condition: "disk_available_pct < 10"
    evaluation_interval: 5m
    severity: high
    notify:
      channels: [slack, email]
      recipients: [maintainer, oncall]
    cooldown: 30m
    auto_resolve: true
    runbook_url: "/runbooks/disk-space"

  - name: memory_pressure
    description: "Memory utilization exceeded 90% for 5 minutes"
    condition: "avg(memory_utilization, 5m) > 90"
    evaluation_interval: 1m
    severity: high
    notify:
      channels: [slack]
      recipients: [oncall]
    cooldown: 10m
    auto_resolve: true
    runbook_url: "/runbooks/memory-pressure"
```

### Alert Severity Levels

| Severity | Response Time | Notification | Escalation |
|----------|--------------|-------------|------------|
| **Critical** | Immediate | Pager + Slack + Email | Auto-escalate after 15 minutes |
| **High** | Within 1 hour | Slack + Email | Auto-escalate after 4 hours |
| **Medium** | Within 4 hours | Slack | Auto-escalate after 24 hours |
| **Low** | Next business day | Slack | No auto-escalation |
| **Info** | No response required | Dashboard only | None |

### Anomaly Detection (Future)

In addition to threshold-based alerts, the system supports anomaly detection.

| Method | Description | Use Case |
|--------|-------------|----------|
| **Baseline deviation** | Alert when a metric deviates more than N standard deviations from its rolling baseline | Sudden traffic spikes or drops |
| **Trend-based** | Alert when a metric's rate of change indicates it will breach a threshold within N hours | Disk filling, memory leak |
| **Seasonal comparison** | Alert when a metric differs significantly from the same time window in previous periods | Unexpected weekend activity |

## Status Page

The status page provides a public-facing (or team-facing) view of system health.

### Components

```yaml
status_page:
  title: "AGENT-33 System Status"
  refresh_interval: 60s
  components:
    - name: "Orchestrator"
      description: "Core workflow orchestration engine"
      health_check: readiness
    - name: "Agent Pool"
      description: "AI agent execution pool"
      health_check: liveness
      metric: active_agents
    - name: "Task Queue"
      description: "Task scheduling and dispatch"
      metric: queue_depth
      health_check: readiness
    - name: "Plugin Runtime"
      description: "Plugin sandbox execution environment"
      health_check: dependency_health
    - name: "Trace Store"
      description: "Execution trace and audit storage"
      health_check: dependency_health
    - name: "Metrics Store"
      description: "Time-series metrics storage"
      health_check: dependency_health
```

### Status Levels

| Status | Display | Description |
|--------|---------|-------------|
| **Operational** | Green | All checks passing, metrics within normal range |
| **Degraded** | Yellow | Non-critical checks failing or metrics outside normal range |
| **Partial Outage** | Orange | Some components unavailable |
| **Major Outage** | Red | Critical components unavailable |
| **Maintenance** | Blue | Planned maintenance in progress |

### Incident Timeline

The status page includes an incident timeline showing recent events.

```yaml
incident:
  id: string
  title: string
  status: investigating | identified | monitoring | resolved
  severity: critical | high | medium | low
  started_at: ISO-8601
  resolved_at: ISO-8601             # null if ongoing
  affected_components: [string]
  updates:
    - timestamp: ISO-8601
      status: string
      message: string
```

## Metrics Reference

### System Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `uptime_percentage` | gauge | % | System uptime over rolling 30-day window |
| `cpu_utilization` | gauge | % | Current CPU usage |
| `memory_utilization` | gauge | % | Current memory usage |
| `disk_available_pct` | gauge | % | Available disk space |
| `queue_depth` | gauge | tasks | Number of tasks waiting in queue |

### Workflow Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `active_workflows` | gauge | count | Currently executing workflows |
| `completed_today` | counter | count | Workflows completed in current UTC day |
| `failed_today` | counter | count | Workflows failed in current UTC day |
| `completed_per_hour` | rate | count/h | Workflow completion rate |
| `failed_per_hour` | rate | count/h | Workflow failure rate |
| `workflow_duration_ms` | histogram | ms | Workflow execution duration distribution |
| `workflow_stage_duration_seconds` | gauge | s | Time spent in current stage per workflow |

### Agent Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `active_agents` | gauge | count | Agents currently processing tasks |
| `idle_agents` | gauge | count | Agents available but not processing |
| `handoffs_per_hour` | rate | count/h | Agent-to-agent handoff rate |
| `agent_utilization` | gauge | % | Per-agent utilization percentage |
| `handoff_matrix` | matrix | count | Handoff counts between agent pairs |

### Error Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `error_rate_1h` | gauge | % | Error rate over the last hour |
| `error_rate_24h` | gauge | % | Error rate over the last 24 hours |
| `error_count` | counter | count | Total error count |
| `top_errors` | ranked list | - | Most frequent errors by type |

### Plugin Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `plugin_invocations_24h` | counter | count | Plugin invocation count per plugin (24h) |
| `plugin_error_rate_1h` | gauge | % | Per-plugin error rate (1h) |
| `plugin_latency` | histogram | ms | Per-plugin invocation latency |

## Integration Points

### Trace Schema

Dashboard data is derived from trace events. Each trace event that includes timing, status, or error information feeds into the metrics aggregation pipeline.

### Analytics Catalog

All metrics defined here are registered in the metrics catalog (`analytics/METRICS_CATALOG.md`). The dashboard consumes metrics through the same interface used by analytics queries.

### Testing Framework

Test execution results from the workflow testing framework feed into the dashboard as a dedicated panel showing test health trends, coverage metrics, and flaky test counts.

### Plugin Registry

Plugin health data is sourced from the plugin registry. Activation status, invocation counts, and error rates are reported per plugin.

---

## Appendix: Dashboard Configuration

Full dashboard configuration combining all panels.

```yaml
dashboard:
  title: "AGENT-33 Operations Dashboard"
  refresh_interval: 30s
  timezone: UTC
  layout:
    columns: 2
    rows: auto
  panels:
    - name: "System Health"
      position: {row: 0, col: 0}
      metrics: [uptime_percentage, cpu_utilization, memory_utilization, queue_depth]
      refresh_interval: 30s
    - name: "Workflow Status"
      position: {row: 0, col: 1}
      metrics: [active_workflows, completed_today, failed_today, workflow_duration_ms]
      refresh_interval: 60s
    - name: "Agent Activity"
      position: {row: 1, col: 0}
      metrics: [active_agents, idle_agents, handoffs_per_hour, agent_utilization]
      refresh_interval: 30s
    - name: "Error Rates"
      position: {row: 1, col: 1}
      metrics: [error_rate_1h, error_rate_24h, error_count, top_errors]
      refresh_interval: 30s
    - name: "Plugin Health"
      position: {row: 2, col: 0, colspan: 2}
      metrics: [plugin_status, plugin_latency, plugin_error_rate_1h]
      refresh_interval: 60s
  alerts:
    - name: "High Error Rate"
      condition: "error_rate_1h > 5"
      severity: high
      notify: [maintainer]
    - name: "Queue Backlog"
      condition: "queue_depth > 100"
      severity: medium
      notify: [orchestrator]
    - name: "Workflow Stuck"
      condition: "max(workflow_stage_duration_seconds) > 1800"
      severity: high
      notify: [maintainer]
    - name: "All Agents Idle"
      condition: "active_agents == 0 and queue_depth > 0"
      severity: critical
      notify: [oncall]
  health_checks:
    - name: readiness
      endpoint: /health/ready
      interval: 10s
    - name: liveness
      endpoint: /health/live
      interval: 30s
    - name: dependency_health
      endpoint: /health/dependencies
      interval: 60s
```
