# Backpressure Specification

**Status**: Specification
**Source**: CA-053 to CA-064 (Camunda), CA-041 to CA-052 (Kestra)

## Overview

This document defines flow control mechanisms that prevent system overload when task production exceeds consumption capacity. Backpressure is the propagation of resource constraints from consumers back to producers, enabling the orchestrator to maintain stability, fairness, and predictable latency under load.

## Backpressure Signals

The orchestrator monitors four signal categories to detect when demand exceeds capacity.

### Signal Types

| Signal | Metric | Description |
|--------|--------|-------------|
| Queue depth | Pending task count per queue | Number of tasks waiting for execution |
| Processing latency | p50, p95, p99 task duration | Time from enqueue to completion |
| Error rate | Failures per total executions | Ratio of failed tasks over a sliding window |
| Resource utilization | CPU, memory, agent slots | Infrastructure and agent capacity consumption |

### Signal Configuration

```yaml
backpressure:
  signals:
    queue_depth:
      metric: pending_task_count
      window: instantaneous
      per: [agent, task_type, workflow, global]
    latency:
      metric: task_duration_ms
      percentile: p99
      window: 5m
      per: [task_type, workflow, global]
    error_rate:
      metric: task_failure_ratio
      window: 5m
      per: [agent, task_type, workflow, global]
    resource_utilization:
      metrics: [cpu_percent, memory_percent, agent_slots_used_ratio]
      window: 1m
      per: [global]
```

### Threshold Configuration

```yaml
backpressure:
  thresholds:
    queue_depth_warn: 100
    queue_depth_critical: 500
    latency_p99_warn: 30s
    latency_p99_critical: 120s
    error_rate_warn: 0.05
    error_rate_critical: 0.20
    cpu_warn: 0.80
    cpu_critical: 0.95
    memory_warn: 0.80
    memory_critical: 0.95
    agent_slots_warn: 0.80
    agent_slots_critical: 0.95
```

## Response Strategies

When backpressure signals exceed thresholds, the orchestrator applies one or more response strategies.

### Strategy Overview

| Strategy | Behavior | When to Use |
|----------|----------|-------------|
| Throttle | Reduce task acceptance rate | Gradual overload, preserving all work |
| Shed | Drop low-priority tasks | Acute overload, protect critical work |
| Buffer | Queue tasks for later processing | Burst traffic with eventual capacity |
| Scale | Increase capacity dynamically | Sustained load increase, elastic infrastructure |

### Throttle

Reduce the rate at which new tasks are accepted or dispatched.

```yaml
backpressure:
  strategy: throttle
  throttle:
    mode: adaptive         # adaptive | fixed
    min_rate: 1             # minimum tasks/second
    target_latency_p99: 30s # target latency to converge toward
    adjustment_interval: 10s
    decrease_factor: 0.5    # multiplicative decrease on threshold breach
    increase_factor: 1.1    # multiplicative increase on recovery
```

**Adaptive throttling** adjusts the dispatch rate using an AIMD (Additive Increase, Multiplicative Decrease) algorithm:

```python
class AdaptiveThrottle:
    def __init__(self, config: ThrottleConfig):
        self.rate = config.max_rate
        self.min_rate = config.min_rate
        self.config = config

    def on_threshold_breach(self):
        """Multiplicative decrease on overload signal."""
        self.rate = max(
            self.min_rate,
            self.rate * self.config.decrease_factor
        )

    def on_recovery(self):
        """Additive increase on healthy signal."""
        self.rate = min(
            self.config.max_rate,
            self.rate * self.config.increase_factor
        )
```

### Shed

Drop tasks that exceed system capacity, prioritizing critical work.

```yaml
backpressure:
  strategy: shed
  shed:
    priority_field: task.priority    # field used for ordering
    shed_below_priority: low         # shed tasks at or below this level
    shed_ratio: 0.2                  # fraction of incoming tasks to shed
    notify_on_shed: true             # emit event when shedding
    dead_letter: true                # send shed tasks to dead letter queue
```

Priority levels (highest to lowest): `critical`, `high`, `medium`, `low`, `background`.

Shedding order:
1. Background tasks are shed first
2. Low-priority tasks are shed next
3. Medium and above are never shed (escalate to other strategies instead)

### Buffer

Accept tasks into bounded queues for deferred processing.

```yaml
backpressure:
  strategy: buffer
  buffer:
    max_size: 10000
    overflow_action: reject | shed_lowest
    ordering: fifo | priority | deadline
    ttl: 1h                          # tasks expire after this duration
    persistence: memory | disk | database
```

### Scale

Dynamically increase processing capacity in response to sustained load.

```yaml
backpressure:
  strategy: scale
  scale:
    mode: horizontal               # horizontal | vertical
    min_instances: 1
    max_instances: 10
    scale_up_threshold: queue_depth_critical
    scale_down_threshold: queue_depth_warn
    cooldown_up: 60s
    cooldown_down: 300s
    provider: kubernetes | docker | process
```

### Combined Strategy

In practice, strategies are layered:

```yaml
backpressure:
  strategy: combined
  layers:
    - strategy: buffer
      trigger: queue_depth >= queue_depth_warn
    - strategy: throttle
      trigger: queue_depth >= queue_depth_warn AND latency_p99 >= latency_p99_warn
    - strategy: scale
      trigger: queue_depth >= queue_depth_critical
    - strategy: shed
      trigger: error_rate >= error_rate_critical OR resource_utilization >= cpu_critical
```

## Queue Management

### Bounded Queues

All task queues have configurable upper bounds to prevent unbounded memory growth.

```yaml
queues:
  default:
    max_size: 1000
    ordering: priority
    overflow: reject
  agent_specific:
    max_size: 100
    ordering: fifo
    overflow: shed_lowest
  high_priority:
    max_size: 500
    ordering: deadline
    overflow: reject
```

### Priority Queues

Tasks are ordered by priority, then by arrival time within the same priority level.

```python
@dataclass(order=True)
class PrioritizedTask:
    priority: int          # lower number = higher priority
    deadline: datetime     # earlier deadline = higher urgency
    enqueued_at: datetime  # FIFO within same priority+deadline
    task: Any = field(compare=False)
```

### Dead Letter Queues

Tasks that fail permanently (exhausted retries, shed, or timed out) are routed to dead letter queues for inspection and manual replay.

```yaml
dead_letter:
  enabled: true
  retention: 7d
  max_size: 10000
  alert_on_growth: true
  alert_threshold: 100
  replay:
    enabled: true
    require_approval: true
    max_batch_size: 50
```

### Queue Metrics

| Metric | Description |
|--------|-------------|
| `queue.depth` | Current number of pending tasks |
| `queue.enqueue_rate` | Tasks entering the queue per second |
| `queue.dequeue_rate` | Tasks leaving the queue per second |
| `queue.wait_time_p99` | 99th percentile time in queue |
| `queue.dead_letter.depth` | Dead letter queue size |
| `queue.overflow_count` | Tasks rejected due to full queue |

## Rate Limiting

Rate limits cap the maximum throughput at configurable granularities.

### Configuration

```yaml
rate_limit:
  global:
    requests_per_second: 100
    burst_size: 150
  per_agent:
    requests_per_second: 20
    burst_size: 30
  per_task_type:
    http:
      requests_per_second: 50
      burst_size: 75
    shell:
      requests_per_second: 5
      burst_size: 5
    llm_generate:
      requests_per_second: 10
      burst_size: 15
  per_workflow:
    requests_per_second: 30
    burst_size: 45
```

### Token Bucket Algorithm

Rate limiting uses a token bucket algorithm:

```python
class TokenBucket:
    def __init__(self, rate: float, burst: int):
        self.rate = rate          # tokens per second
        self.burst = burst        # maximum tokens
        self.tokens = burst
        self.last_refill = time.monotonic()

    def acquire(self, count: int = 1) -> bool:
        """Attempt to acquire tokens. Returns True if allowed."""
        self._refill()
        if self.tokens >= count:
            self.tokens -= count
            return True
        return False

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_refill = now
```

### Rate Limit Exceeded Behavior

When a rate limit is exceeded:

1. Task is queued (if buffer strategy is active)
2. Caller receives a `RATE_LIMITED` response with `retry_after` hint
3. Metric `rate_limit.exceeded` is incremented

## Circuit Breaker Pattern

The circuit breaker prevents cascading failures by temporarily halting requests to a failing downstream dependency.

### State Machine

```
     success / under threshold
     +-------+
     |       |
     v       |
  +--------+ |    failure threshold    +------+
  | CLOSED |---+--------------------->| OPEN |
  +--------+                          +------+
     ^                                   |
     |          reset_timeout            |
     |                                   v
     |                             +-----------+
     +-------- success -----------| HALF-OPEN |
               (trial request)    +-----------+
                                       |
                        failure -------+
                        (back to OPEN)
```

### Configuration

```yaml
circuit_breaker:
  enabled: true
  scope: per_task_type          # per_task_type | per_agent | per_service | global
  failure_threshold: 5          # consecutive failures to trip
  failure_window: 60s           # sliding window for counting failures
  reset_timeout: 30s            # time in OPEN before transitioning to HALF-OPEN
  half_open_requests: 3         # trial requests allowed in HALF-OPEN
  success_threshold: 2          # successes in HALF-OPEN to close
  monitored_errors:             # error types that count as failures
    - TIMEOUT
    - CONNECTION_REFUSED
    - HTTP_5XX
    - HANDLER_CRASH
```

### Implementation

```python
class CircuitBreaker:
    def __init__(self, config: CircuitBreakerConfig):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.config = config

    async def call(self, fn, *args, **kwargs):
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
            else:
                raise CircuitOpenError(retry_after=self._retry_after())

        try:
            result = await fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            if self._is_monitored_error(e):
                self._on_failure()
            raise

    def _on_success(self):
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
        else:
            self.failure_count = 0

    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self.success_count = 0
        elif self.failure_count >= self.config.failure_threshold:
            self.state = CircuitState.OPEN

    def _should_attempt_reset(self) -> bool:
        elapsed = time.monotonic() - self.last_failure_time
        return elapsed >= self.config.reset_timeout
```

### Circuit Breaker Events

| Event | Description |
|-------|-------------|
| `circuit.opened` | Breaker tripped from CLOSED to OPEN |
| `circuit.half_opened` | Breaker moved from OPEN to HALF-OPEN |
| `circuit.closed` | Breaker recovered from HALF-OPEN to CLOSED |
| `circuit.rejected` | Request rejected while OPEN |

## Graceful Degradation

When the system is under sustained pressure, reduce quality or scope of work before failing entirely.

### Degradation Levels

| Level | Condition | Behavior |
|-------|-----------|----------|
| Normal | All signals below warn | Full processing |
| Degraded | Any signal at warn | Reduce optional work (skip non-critical checks) |
| Limited | Any signal at critical | Process only critical-priority tasks |
| Emergency | Multiple signals at critical | Reject all new work, drain existing queues |

### Configuration

```yaml
graceful_degradation:
  enabled: true
  levels:
    degraded:
      trigger: any_signal >= warn
      actions:
        - skip_optional_validations: true
        - reduce_parallelism: 0.5
        - disable_telemetry_detail: true
    limited:
      trigger: any_signal >= critical
      actions:
        - accept_priority_only: [critical, high]
        - reduce_parallelism: 0.25
        - disable_non_essential_logging: true
    emergency:
      trigger: multiple_signals >= critical
      actions:
        - reject_all_new: true
        - drain_existing: true
        - alert_operator: true
```

## Load Balancing Across Agents

When multiple agents can handle a task type, the orchestrator distributes work to balance load and avoid hotspots.

### Strategies

| Strategy | Description |
|----------|-------------|
| Round-robin | Rotate sequentially through available agents |
| Least-loaded | Route to agent with fewest pending tasks |
| Weighted | Route based on agent capacity weights |
| Latency-based | Route to agent with lowest recent p50 latency |
| Affinity | Route to agent with cached context for the workflow |

### Configuration

```yaml
load_balancing:
  strategy: least_loaded
  health_check_interval: 10s
  agent_weights:
    implementer_1: 1.0
    implementer_2: 1.5     # 50% more capacity
  affinity:
    enabled: true
    key: workflow_id
    ttl: 300s
  exclude_unhealthy: true
  unhealthy_threshold: 3   # consecutive health check failures
```

### Agent Health

An agent is considered healthy when:

1. It responds to health checks within the timeout
2. Its error rate is below the per-agent threshold
3. Its queue depth is below the per-agent critical threshold
4. Its circuit breaker is not OPEN

Unhealthy agents are excluded from load balancing until they recover.

## Metrics for Backpressure Monitoring

All backpressure mechanisms emit metrics for observability. These integrate with the analytics spec in `core/orchestrator/analytics/METRICS_CATALOG.md`.

### Metric Catalog

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `backpressure.signal.queue_depth` | Gauge | agent, task_type, workflow | Current queue depth |
| `backpressure.signal.latency_p99` | Gauge | task_type, workflow | 99th percentile latency |
| `backpressure.signal.error_rate` | Gauge | agent, task_type, workflow | Current error rate |
| `backpressure.throttle.rate` | Gauge | scope | Current throttle rate |
| `backpressure.shed.count` | Counter | task_type, priority | Tasks shed |
| `backpressure.buffer.depth` | Gauge | queue_name | Buffer queue depth |
| `backpressure.buffer.overflow` | Counter | queue_name | Buffer overflow events |
| `backpressure.rate_limit.exceeded` | Counter | scope, key | Rate limit exceeded events |
| `backpressure.circuit.state` | Gauge | scope, key | Circuit breaker state (0=closed, 1=half-open, 2=open) |
| `backpressure.circuit.rejections` | Counter | scope, key | Requests rejected by open circuit |
| `backpressure.degradation.level` | Gauge | global | Current degradation level (0-3) |
| `backpressure.agent.health` | Gauge | agent_id | Agent health status (0=unhealthy, 1=healthy) |
| `backpressure.agent.load` | Gauge | agent_id | Agent current load ratio |

### Alerting Rules

```yaml
alerts:
  - name: high_queue_depth
    condition: backpressure.signal.queue_depth > queue_depth_critical
    duration: 5m
    severity: warning
    action: notify_operator

  - name: circuit_open
    condition: backpressure.circuit.state == 2
    duration: 0s
    severity: critical
    action: [notify_operator, page_oncall]

  - name: sustained_shedding
    condition: rate(backpressure.shed.count[5m]) > 10
    duration: 5m
    severity: warning
    action: notify_operator

  - name: emergency_degradation
    condition: backpressure.degradation.level == 3
    duration: 0s
    severity: critical
    action: [notify_operator, page_oncall, freeze_deployments]

  - name: dead_letter_growth
    condition: backpressure.buffer.depth{queue_name="dead_letter"} > 100
    duration: 10m
    severity: warning
    action: notify_operator
```

## Analytics Integration

Backpressure metrics feed into the AGENT-33 analytics pipeline defined in `core/orchestrator/analytics/METRICS_CATALOG.md` (CA-015). Key integration points:

1. **Dashboards**: Real-time backpressure signal visualization with threshold lines
2. **Trend analysis**: Historical queue depth and latency trends for capacity planning
3. **Incident correlation**: Correlate backpressure events with workflow failures
4. **SLA tracking**: Monitor whether backpressure mechanisms maintain SLA targets
5. **Tuning recommendations**: Use historical data to suggest threshold adjustments

## Full Configuration Example

```yaml
backpressure:
  strategy: combined

  thresholds:
    queue_depth_warn: 100
    queue_depth_critical: 500
    latency_p99_warn: 30s
    latency_p99_critical: 120s
    error_rate_warn: 0.05
    error_rate_critical: 0.20

  layers:
    - strategy: buffer
      trigger: queue_depth >= 100
      buffer:
        max_size: 10000
        ordering: priority
        ttl: 1h
    - strategy: throttle
      trigger: queue_depth >= 100 AND latency_p99 >= 30s
      throttle:
        mode: adaptive
        min_rate: 1
        target_latency_p99: 30s
    - strategy: scale
      trigger: queue_depth >= 500
      scale:
        max_instances: 10
        cooldown_up: 60s
    - strategy: shed
      trigger: error_rate >= 0.20
      shed:
        shed_below_priority: low
        dead_letter: true

  circuit_breaker:
    enabled: true
    scope: per_task_type
    failure_threshold: 5
    reset_timeout: 30s
    half_open_requests: 3

  rate_limit:
    global:
      requests_per_second: 100
      burst_size: 150
    per_agent:
      requests_per_second: 20
      burst_size: 30

  graceful_degradation:
    enabled: true

  load_balancing:
    strategy: least_loaded
    health_check_interval: 10s
    exclude_unhealthy: true

  dead_letter:
    enabled: true
    retention: 7d
    replay:
      enabled: true
      require_approval: true
```
