# Agent Handoff Protocol Specification

Purpose: Formalize how agents transfer control, context, and responsibility during multi-agent workflows.

Related docs:
- `core/orchestrator/AUTONOMY_ENFORCEMENT.md` (autonomy budget compliance)
- `core/orchestrator/AGENT_ROUTING_MAP.md` (agent capability routing)
- `core/orchestrator/AGENT_REGISTRY.md` (agent definitions)
- `core/orchestrator/TRACE_SCHEMA.md` (observability)

Sources:
- OpenAI Swarm (CA-131 to CA-142)
- Agency Swarm (CA-077 to CA-088)
- wshobson/agents (CA-029 to CA-040)

---

## Handoff Schema

```yaml
handoff:
  id: string (uuid)
  timestamp: ISO-8601
  from_agent: agent_id
  to_agent: agent_id
  type: sequential | delegation | broadcast | escalation
  reason: string
  context:
    task_id: string
    conversation_history: [message]
    context_variables: {key: value}
    artifacts: [artifact_ref]
    constraints:
      budget: number
      deadline: ISO-8601
  validation:
    required_capabilities: [capability_id]
    autonomy_budget: number
  return_protocol:
    expected: boolean
    timeout: duration
    on_timeout: retry | escalate | fail
  audit:
    decision_rationale: string
    risk_level: low | medium | high
```

---

## 1. Handoff Trigger Conditions

A handoff is initiated when any of the following conditions are met.

### 1.1 Task Completion

The current agent has finished its assigned work and the workflow requires the next agent to act.

```yaml
trigger:
  type: task_completion
  condition: agent reports status "complete"
  action: route to next agent in workflow sequence
  example: implementer finishes code, hands off to reviewer
```

### 1.2 Capability Mismatch

The current agent determines it lacks a required capability for the next phase of work.

```yaml
trigger:
  type: capability_mismatch
  condition: required_capability not in agent.capabilities
  action: route to agent possessing the required capability
  example: implementer encounters security concern, hands off to security-reviewer
```

### 1.3 Escalation

The current agent encounters a decision that exceeds its autonomy budget or risk threshold.

```yaml
trigger:
  type: escalation
  condition: decision.risk_level > agent.autonomy_budget.max_risk
  action: route to supervisor agent or human operator
  example: worker hits ambiguous requirement, escalates to architect
```

### 1.4 Timeout

The current agent has exceeded its allotted time without completing the task.

```yaml
trigger:
  type: timeout
  condition: elapsed_time > task.deadline OR elapsed_time > agent.max_execution_time
  action: escalate to orchestrator for reassignment or intervention
  example: agent stalls for 10 minutes, orchestrator reassigns
```

### 1.5 Explicit Request

An agent explicitly requests assistance from another agent.

```yaml
trigger:
  type: explicit_request
  condition: agent invokes handoff function targeting specific agent
  action: initiate handoff to requested agent
  example: implementer requests architect clarification mid-task
```

---

## 2. Handoff Types

### 2.1 Sequential (A -> B)

Linear transfer of control. Agent A completes its work and passes full responsibility to Agent B. Agent A does not expect a return.

```yaml
sequential:
  flow: A -> B
  return_expected: false
  use_case: pipeline workflows (architect -> implementer -> reviewer)
  context_transfer: full (all accumulated context forwarded)
  ownership: transfers completely to B
```

**Rules:**
- Agent A must mark its task segment as complete before handoff.
- Agent B receives full context and continues independently.
- Agent A is freed to accept new work.

### 2.2 Delegation (A -> B -> A)

Agent A assigns a subtask to Agent B and expects results back. Agent A retains overall task ownership.

```yaml
delegation:
  flow: A -> B -> A
  return_expected: true
  timeout: required (must specify max wait)
  use_case: orchestrator delegates subtask to specialist
  context_transfer: scoped (only subtask-relevant context)
  ownership: retained by A
```

**Rules:**
- Agent A specifies the subtask clearly in `context.task_id`.
- Agent B must return results within `return_protocol.timeout`.
- If timeout is reached, `on_timeout` action is executed.
- Agent A remains blocked on the subtask or continues other work (configurable).

### 2.3 Broadcast (A -> [B, C, D])

Agent A sends work to multiple agents simultaneously. Used for parallel execution or scatter-gather patterns.

```yaml
broadcast:
  flow: A -> [B, C, D]
  return_expected: true | false (configurable per target)
  aggregation: all | any | majority (when returns expected)
  use_case: parallel review, multi-perspective analysis
  context_transfer: identical copy to each recipient
  ownership: retained by A until aggregation complete
```

**Rules:**
- Each recipient receives an independent copy of context.
- Recipients do not coordinate with each other unless explicitly configured.
- Agent A aggregates results according to the `aggregation` strategy.
- Partial failures are tolerated based on aggregation mode (`any` = one success sufficient).

### 2.4 Escalation (Worker -> Reviewer -> Architect)

Hierarchical transfer up the authority chain when an agent cannot proceed within its autonomy budget.

```yaml
escalation:
  flow: worker -> reviewer -> architect -> human (as needed)
  return_expected: true (decision or guidance returned)
  urgency: inherits from original task priority
  use_case: autonomy budget exceeded, ambiguous requirements, safety concern
  context_transfer: full context plus escalation rationale
  ownership: temporarily held by escalation target
```

**Rules:**
- Escalation reason must be documented in `audit.decision_rationale`.
- Escalation target may resolve and return, or escalate further.
- Each escalation level adds its assessment to the audit trail.
- Maximum escalation depth is 3 (worker -> reviewer -> architect -> human).

---

## 3. Context Transfer Schema

Every handoff carries a context payload. The context schema ensures receiving agents have sufficient information to continue work without re-discovery.

### 3.1 Context Variables

Shared mutable state that persists across handoffs within a workflow.

```yaml
context_variables:
  # Task-level state
  task_id: string
  task_status: pending | in_progress | blocked | complete | failed
  task_priority: critical | high | normal | low

  # Accumulated decisions
  decisions_made:
    - decision_id: string
      description: string
      made_by: agent_id
      timestamp: ISO-8601

  # File ownership tracking
  files_in_progress:
    - path: string
      owner: agent_id
      lock_type: exclusive | shared

  # Custom key-value pairs (workflow-specific)
  custom: {key: value}
```

**Mutability Rules:**
- Any agent in the workflow may read all context variables.
- An agent may only write to context variables within its scope.
- File locks must be acquired before writing and released after.
- Conflicting writes are resolved by the orchestrator.

### 3.2 Conversation History

Relevant message history transferred between agents.

```yaml
conversation_history:
  transfer_mode: full | summary | relevant_only
  max_messages: number (optional, to limit token usage)
  include:
    - system_messages: boolean
    - tool_calls: boolean
    - tool_results: boolean
    - agent_reasoning: boolean
```

**Guidelines:**
- For sequential handoffs, transfer `relevant_only` to reduce token overhead.
- For escalations, transfer `full` to preserve maximum context.
- For delegations, transfer `summary` plus the specific subtask description.

### 3.3 Artifacts

References to files, code, documents, or other outputs produced during the workflow.

```yaml
artifact:
  id: string (uuid)
  type: file | code | document | test_result | review_comment
  path: string (filesystem path or URI)
  created_by: agent_id
  created_at: ISO-8601
  description: string
  status: draft | final | superseded
```

---

## 4. Return Protocol

When a handoff expects a return (delegation, broadcast, escalation), the return protocol governs how results flow back.

### 4.1 Return Payload

```yaml
return:
  handoff_id: string (references original handoff)
  from_agent: agent_id
  to_agent: agent_id (original sender)
  status: success | partial | failed | timeout
  result:
    content_type: text | json | artifact_ref
    body: object
  context_updates:
    variables_changed: {key: value}
    artifacts_produced: [artifact_ref]
  audit:
    completion_time: ISO-8601
    tokens_consumed: number
    notes: string
```

### 4.2 Timeout Handling

```yaml
timeout_policy:
  retry:
    max_attempts: 3
    backoff: exponential (base 2s)
    action: resend handoff to same agent
  escalate:
    target: next agent in escalation chain
    action: forward original handoff with timeout annotation
  fail:
    action: mark subtask as failed, notify orchestrator
    fallback: human intervention requested
```

---

## 5. Handoff Validation

Before a handoff is accepted, the receiving agent validates it can fulfill the request.

### 5.1 Capability Check

```yaml
validation:
  required_capabilities:
    - capability_id: string
      min_proficiency: number (0.0 - 1.0, optional)
  check_process:
    1. receiving agent compares required_capabilities against its own capability list
    2. if all capabilities matched: accept handoff
    3. if partial match: accept with warning, log gap
    4. if no match: reject handoff, return to sender with rejection reason
```

### 5.2 Capacity Check

```yaml
capacity:
  max_concurrent_tasks: number
  current_load: number
  check_process:
    1. if current_load < max_concurrent_tasks: accept
    2. if at capacity: reject with "at_capacity" reason
    3. orchestrator may queue or reroute
```

### 5.3 Acceptance Confirmation

```yaml
acceptance:
  status: accepted | rejected | deferred
  reason: string (required if rejected or deferred)
  estimated_completion: ISO-8601 (optional)
  acknowledged_at: ISO-8601
```

---

## 6. Failure Handling

### 6.1 Handoff Rejected

The receiving agent cannot accept the handoff.

```yaml
on_rejection:
  actions:
    - log rejection with reason
    - notify orchestrator
    - orchestrator selects alternative agent from routing map
    - if no alternative available: escalate to human
  max_reroute_attempts: 3
```

### 6.2 Agent Unavailable

The target agent is offline, crashed, or unresponsive.

```yaml
on_unavailable:
  detection: no acknowledgment within 30 seconds
  actions:
    - mark agent as unavailable in registry
    - orchestrator selects alternative agent
    - if critical task: escalate immediately
  health_check:
    interval: 60s
    timeout: 10s
    unhealthy_threshold: 3 consecutive failures
```

### 6.3 Handoff Timeout

The receiving agent accepted but did not return results within the expected window.

```yaml
on_handoff_timeout:
  actions:
    - send reminder notification to receiving agent
    - if no response after reminder: execute on_timeout policy (retry | escalate | fail)
    - log timeout event in audit trail
```

---

## 7. Audit Trail

Every handoff generates an audit record. Audit records are immutable once written.

### 7.1 Audit Record Schema

```yaml
audit_record:
  handoff_id: string
  timestamp: ISO-8601
  event_type: initiated | accepted | rejected | completed | failed | timeout | escalated
  from_agent: agent_id
  to_agent: agent_id
  handoff_type: sequential | delegation | broadcast | escalation
  reason: string
  context_snapshot:
    task_id: string
    task_status: string
    context_variables_hash: string (SHA-256 of serialized variables)
    artifact_count: number
  decision_rationale: string
  risk_level: low | medium | high
  duration_ms: number (time from initiation to resolution)
  tokens_consumed: number
  outcome: success | partial | failed
```

### 7.2 Audit Requirements

- Every handoff MUST produce at least two audit records: `initiated` and one of `accepted | rejected`.
- Completed handoffs MUST produce a `completed` or `failed` record.
- Audit records MUST be written before the handoff proceeds (write-ahead).
- Audit records are stored in the trace log alongside execution traces.
- Audit records MUST be queryable by `handoff_id`, `task_id`, `from_agent`, and `to_agent`.

### 7.3 Audit Retention

```yaml
retention:
  active_tasks: retained until task closure + 30 days
  completed_tasks: retained for 90 days minimum
  escalation_events: retained for 180 days minimum
  format: JSON lines, one record per line
  storage: core/logs/<project>/handoff-audit/
```

---

## 8. Handoff Lifecycle Summary

```
1. TRIGGER      Agent detects handoff condition
2. PREPARE      Agent assembles handoff payload (context, artifacts, constraints)
3. VALIDATE     Orchestrator checks routing map for target agent
4. INITIATE     Handoff message sent to target agent (audit: initiated)
5. ACKNOWLEDGE  Target agent validates capability and capacity
6. ACCEPT/REJECT Target agent responds (audit: accepted | rejected)
7. EXECUTE      Target agent performs work
8. RETURN       Target agent returns results (if delegation/broadcast/escalation)
9. COMPLETE     Originating agent processes return (audit: completed)
10. RELEASE     File locks released, context variables updated
```

---

## 9. Implementation Notes

- Handoff IDs use UUIDv4 for global uniqueness.
- All timestamps are UTC in ISO-8601 format.
- Context variable serialization uses JSON for portability.
- The orchestrator is the single authority for routing decisions; agents may suggest but not override routing.
- Broadcast handoffs create independent handoff records for each recipient, linked by a shared `broadcast_group_id`.
- This protocol integrates with the autonomy enforcement system: agents may not hand off to agents with insufficient autonomy budgets for the task.
