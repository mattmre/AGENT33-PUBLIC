# Communication Flow Schema

Purpose: Define structured communication patterns between agents in multi-agent systems.

Related docs:
- `core/orchestrator/agent-protocols/AGENT_HANDOFF_PROTOCOL.md` (handoff-specific messaging)
- `core/orchestrator/AGENT_ROUTING_MAP.md` (agent addressing)
- `core/orchestrator/TRACE_SCHEMA.md` (message observability)

Sources:
- Agency Swarm (CA-077 to CA-088)

---

## Message Schema

```yaml
message:
  id: string (uuid)
  conversation_id: string
  type: request | response | notification | broadcast | query
  priority: critical | high | normal | low
  sender: agent_id
  receiver: agent_id | topic | broadcast
  payload:
    content_type: text | json | artifact_ref
    body: object
  metadata:
    timestamp: ISO-8601
    ttl: duration
    requires_ack: boolean
    in_reply_to: message_id (optional)
    sequence_number: number
    correlation_id: string (optional, links related messages across conversations)
```

---

## 1. Message Types

### 1.1 Request

A message that expects a response. The sender blocks or registers a callback until the response arrives.

```yaml
request:
  type: request
  requires_ack: true
  response_timeout: duration
  on_timeout: retry | escalate | fail
  idempotency_key: string (optional, for safe retries)
  examples:
    - "Implement the authentication module per the attached design"
    - "Review the changes in files X, Y, Z"
    - "Provide an estimate for task T-042"
```

### 1.2 Response

A reply to a previous request. Always references the original message via `in_reply_to`.

```yaml
response:
  type: response
  in_reply_to: message_id (required)
  status: success | partial | error | declined
  examples:
    - "Implementation complete. See artifacts A-001, A-002."
    - "Review findings attached. 2 blocking issues found."
    - "Unable to process: capability mismatch."
```

### 1.3 Notification

A one-way informational message. No response expected.

```yaml
notification:
  type: notification
  requires_ack: false
  examples:
    - "Task T-042 status changed to in_progress"
    - "Agent reviewer-01 is now available"
    - "Autonomy budget 80% consumed for current task"
```

### 1.4 Broadcast

A message sent to all agents on a topic or to all agents in the system.

```yaml
broadcast:
  type: broadcast
  receiver: topic_name | "*" (all agents)
  requires_ack: false (default) | true (roll-call mode)
  examples:
    - "System maintenance in 5 minutes, complete current tasks"
    - "New policy: all file writes require pre-commit validation"
    - "Task T-042 is now available for claiming"
```

### 1.5 Query

A lightweight request for information that does not trigger work execution.

```yaml
query:
  type: query
  requires_ack: true
  response_timeout: 30s (shorter than request default)
  examples:
    - "What is the current status of task T-042?"
    - "Which agents have capability 'security-review'?"
    - "What files are currently locked?"
```

---

## 2. Communication Patterns

### 2.1 Request-Reply

The fundamental synchronous pattern. One sender, one receiver, one response.

```
Sender ---[request]---> Receiver
Sender <--[response]--- Receiver
```

```yaml
request_reply:
  participants: 2 (sender, receiver)
  messages: 2 (request, response)
  ordering: strict (response follows request)
  timeout: required
  use_case: task assignment, information retrieval, approval requests
```

### 2.2 Publish-Subscribe (Pub-Sub)

Agents subscribe to topics and receive messages published to those topics.

```
Publisher ---[message]---> Topic ---[message]---> Subscriber A
                                ---[message]---> Subscriber B
                                ---[message]---> Subscriber C
```

```yaml
pub_sub:
  participants: 1 publisher, N subscribers
  messages: 1 publish, N deliveries
  ordering: per-topic FIFO (messages within a topic delivered in order)
  decoupling: publisher does not know subscribers
  use_case: status updates, event notifications, policy changes
  topics:
    - task.status_changed
    - agent.availability_changed
    - system.policy_updated
    - workflow.phase_completed
    - audit.event_logged
```

### 2.3 Pipeline

Sequential message flow through a chain of agents, each transforming or acting on the payload.

```
A ---[msg]--> B ---[msg']--> C ---[msg'']--> D
```

```yaml
pipeline:
  participants: N agents in ordered sequence
  messages: N-1 transfers
  ordering: strict sequential
  failure: pipeline halts at failing stage, escalates
  use_case: multi-stage processing (design -> implement -> review -> merge)
  backpressure: each stage may signal "busy" to pause upstream
```

### 2.4 Scatter-Gather

One agent sends work to multiple agents in parallel and aggregates responses.

```
           ---[request]---> B ---[response]--->
A (scatter)---[request]---> C ---[response]---> A (gather)
           ---[request]---> D ---[response]--->
```

```yaml
scatter_gather:
  participants: 1 coordinator, N workers
  messages: N requests, up to N responses
  aggregation:
    strategy: all | any | majority | quorum(N)
    timeout: duration (gather window)
    on_partial: proceed_with_available | fail | extend_timeout
  use_case: parallel review, consensus decisions, multi-perspective analysis
```

---

## 3. Channel Definitions

### 3.1 Direct Channel

Point-to-point communication between two specific agents.

```yaml
direct_channel:
  addressing: agent_id -> agent_id
  visibility: private (only sender and receiver)
  ordering: FIFO guaranteed
  persistence: messages retained until TTL expiry or acknowledgment
  use_case: task assignments, delegations, direct queries
```

### 3.2 Topic Channel

Named channel that multiple agents can subscribe to.

```yaml
topic_channel:
  addressing: publisher -> topic_name -> subscribers
  visibility: all subscribers on the topic
  ordering: FIFO within topic
  persistence: messages retained for late subscribers within retention window
  retention_window: 1 hour (configurable)
  use_case: status broadcasts, event notifications, policy updates
  naming_convention: "domain.event_type" (e.g., "task.status_changed")
```

### 3.3 Broadcast Channel

System-wide channel for messages intended for all agents.

```yaml
broadcast_channel:
  addressing: sender -> "*"
  visibility: all active agents
  ordering: best-effort (no strict ordering guarantee)
  persistence: not persisted (fire-and-forget)
  use_case: system announcements, emergency stops, global policy changes
```

---

## 4. Message Priority and Ordering

### 4.1 Priority Levels

```yaml
priority_levels:
  critical:
    description: Safety violations, system failures, emergency stops
    processing: immediate, preempts all other messages
    ttl: 5 minutes (short-lived, must be acted on immediately)
  high:
    description: Blocking issues, escalations, deadline-critical tasks
    processing: next in queue after current message
    ttl: 1 hour
  normal:
    description: Standard task communication, status updates
    processing: FIFO within priority band
    ttl: 24 hours
  low:
    description: Background tasks, optional notifications, analytics
    processing: processed when no higher-priority messages pending
    ttl: 72 hours
```

### 4.2 Ordering Guarantees

```yaml
ordering:
  within_channel:
    direct: strict FIFO (messages between A and B delivered in send order)
    topic: FIFO per publisher (messages from same publisher ordered)
    broadcast: best-effort (no ordering guarantee)
  across_channels:
    guarantee: none (messages on different channels may arrive in any order)
  priority_interaction:
    rule: higher priority messages may be delivered before lower priority
    exception: within a single direct channel, FIFO is preserved regardless of priority
```

---

## 5. Conversation Threading

Related messages are linked via `conversation_id` and `in_reply_to` fields.

### 5.1 Thread Structure

```yaml
thread:
  conversation_id: string (shared by all messages in the conversation)
  root_message_id: string (the first message that started the conversation)
  messages:
    - id: msg-001
      in_reply_to: null (root message)
      type: request
    - id: msg-002
      in_reply_to: msg-001
      type: response
    - id: msg-003
      in_reply_to: msg-001
      type: notification (follow-up to original request)
```

### 5.2 Thread Lifecycle

```yaml
thread_lifecycle:
  created: when root message is sent
  active: at least one pending request without a response
  resolved: all requests have responses, no pending work
  closed: explicitly closed by conversation owner or TTL expiry
  max_depth: 20 messages (prevent unbounded threads)
  max_duration: 24 hours (auto-close stale threads)
```

### 5.3 Cross-Thread References

```yaml
cross_reference:
  correlation_id: string (links messages across separate conversations)
  use_case: a review thread referencing an implementation thread
  resolution: agents can query by correlation_id to find related threads
```

---

## 6. Rate Limiting and Backpressure

### 6.1 Rate Limits

```yaml
rate_limits:
  per_agent:
    outbound: 60 messages/minute (default)
    inbound: 120 messages/minute (default)
  per_channel:
    direct: 30 messages/minute per pair
    topic: 100 messages/minute per topic
    broadcast: 10 messages/minute system-wide
  per_priority:
    critical: no rate limit
    high: 2x normal limit
    normal: standard limit
    low: 0.5x normal limit
  enforcement:
    action: queue excess messages, deliver when capacity available
    notification: sender receives backpressure signal after 80% threshold
```

### 6.2 Backpressure Signals

```yaml
backpressure:
  signal:
    type: notification
    payload:
      status: throttled | overloaded | recovering
      queue_depth: number
      estimated_delay: duration
  sender_behavior:
    on_throttled: reduce send rate by 50%
    on_overloaded: pause non-critical messages, queue locally
    on_recovering: gradually resume normal rate
  circuit_breaker:
    threshold: 10 consecutive failures or 90% queue capacity
    state: closed (normal) | open (rejecting) | half_open (testing)
    recovery: after 60s in open state, transition to half_open, allow 1 test message
```

---

## 7. Dead Letter Handling

Messages that cannot be delivered are routed to a dead letter queue for inspection and recovery.

### 7.1 Dead Letter Conditions

```yaml
dead_letter_conditions:
  - receiver_not_found: agent_id does not exist in registry
  - receiver_unavailable: agent is offline after retry exhaustion
  - ttl_expired: message exceeded its time-to-live
  - rejected: receiver explicitly rejected the message
  - malformed: message fails schema validation
  - queue_overflow: receiver's inbound queue is full and not accepting
```

### 7.2 Dead Letter Queue Schema

```yaml
dead_letter_entry:
  original_message: message (full original message)
  reason: string (why delivery failed)
  failed_at: ISO-8601
  retry_count: number (how many delivery attempts were made)
  last_error: string
  resolution:
    status: pending | retried | discarded | escalated
    resolved_by: agent_id | "system"
    resolved_at: ISO-8601
```

### 7.3 Dead Letter Processing

```yaml
dead_letter_processing:
  inspection:
    frequency: every 5 minutes
    handler: orchestrator
  actions:
    retryable_errors:
      action: retry delivery up to 3 times with exponential backoff
    permanent_failures:
      action: log, notify sender, escalate if critical priority
    stale_messages:
      condition: message age > 2x original TTL
      action: discard with audit record
  alerting:
    threshold: 10 dead letters in 5 minutes
    action: notify orchestrator, trigger system health check
```

---

## 8. Message Validation

All messages are validated against the schema before processing.

```yaml
validation_rules:
  required_fields: [id, conversation_id, type, sender, receiver, payload, metadata.timestamp]
  id_format: UUIDv4
  type_values: [request, response, notification, broadcast, query]
  priority_values: [critical, high, normal, low]
  timestamp_format: ISO-8601 UTC
  payload_max_size: 1MB
  in_reply_to:
    rule: if type is "response", in_reply_to is required
    validation: referenced message must exist
  on_validation_failure:
    action: reject message, send error notification to sender, log to dead letter queue
```

---

## 9. Implementation Notes

- Message IDs use UUIDv4 for global uniqueness across all channels.
- All timestamps are UTC in ISO-8601 format.
- Message payloads are serialized as JSON.
- The orchestrator owns the topic registry and manages subscriptions.
- Agents must register their subscriptions at startup and deregister on shutdown.
- Direct channel state is ephemeral; topic channel state persists within the retention window.
- Rate limits are enforced by the message broker, not by individual agents.
- Dead letter queue contents are included in system health reports.
