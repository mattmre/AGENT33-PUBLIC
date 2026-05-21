# Autonomy Budget Enforcement & Policy Automation

Purpose: Define preflight checks, enforcement rules, stop conditions, and escalation paths for autonomy budget compliance.

Related docs:
- `core/orchestrator/handoff/AUTONOMY_BUDGET.md` (budget template)
- `core/orchestrator/SECURITY_HARDENING.md` (sandbox approvals)
- `core/orchestrator/TOOL_GOVERNANCE.md` (allowlist policy)
- `core/orchestrator/CODE_EXECUTION_CONTRACT.md` (execution limits)

---

## Autonomy Budget Schema

### Full Budget Schema

```yaml
autonomy_budget:
  budget_id: <unique-id>
  task_id: <associated-task>
  version: <budget-version>
  effective_from: <ISO8601>
  expires_at: <optional-expiry>

  # Scope Boundaries
  scope:
    in_scope:
      - <allowed-scope-item>
    out_of_scope:
      - <excluded-scope-item>
    files:
      read: [<allowed-read-patterns>]
      write: [<allowed-write-patterns>]
      deny: [<blocked-patterns>]
    directories:
      allowed: [<allowed-dirs>]
      denied: [<denied-dirs>]

  # Command Permissions
  commands:
    allowed:
      - command: <command-name>
        args_pattern: <optional-arg-regex>
        max_calls: <optional-limit>
    denied:
      - command: <command-name>
        reason: <why-blocked>
    require_approval:
      - command: <command-name>
        approver: <role-or-human>

  # Network Permissions
  network:
    enabled: <true|false>
    allowed_domains: [<domain-list>]
    denied_domains: [<blocked-domains>]
    allowed_protocols: [<http|https|ws|wss>]
    max_requests: <optional-limit>

  # Resource Limits
  limits:
    max_iterations: <count>
    max_duration_minutes: <minutes>
    max_files_modified: <count>
    max_lines_changed: <count>
    max_tool_calls: <count>

  # Stop Conditions
  stop_conditions:
    - condition: <condition-description>
      action: <stop|escalate|warn>
    - condition: <condition-description>
      action: <stop|escalate|warn>

  # Escalation
  escalation:
    triggers:
      - trigger: <trigger-description>
        target: <escalation-target>
        urgency: <immediate|normal|low>
    default_target: <default-escalation-role>

  # Metadata
  metadata:
    created_by: <creator>
    approved_by: <approver>
    created_at: <ISO8601>
    rationale: <budget-justification>
```

### Minimal Budget Schema

For simple tasks, use this minimal schema:

```yaml
autonomy_budget_minimal:
  task_id: <task>
  scope: <brief-scope-description>
  files_allowed: [<patterns>]
  commands_allowed: [<commands>]
  network: <off|limited|open>
  max_iterations: <count>
  stop_on: [<conditions>]
```

---

## Preflight Enforcement

### Preflight Checklist

Before any task execution, validate these checks:

| Check | ID | Validation | Block on Fail |
|-------|----|-----------:|---------------|
| Budget exists | PF-01 | Task has associated autonomy budget | Yes |
| Budget valid | PF-02 | Budget schema validates | Yes |
| Budget not expired | PF-03 | Current time < expires_at | Yes |
| Scope defined | PF-04 | in_scope and out_of_scope populated | Yes |
| Files scoped | PF-05 | File read/write patterns defined | Yes |
| Commands scoped | PF-06 | Command allowlist defined | Yes |
| Network scoped | PF-07 | Network permissions explicit | Yes |
| Limits set | PF-08 | At least one resource limit defined | Warn |
| Stop conditions | PF-09 | At least one stop condition defined | Warn |
| Escalation path | PF-10 | Escalation target defined | Warn |

### Preflight Workflow

```
1. Task assigned to agent
   ↓
2. Load autonomy budget for task
   ├─ Budget not found → BLOCK, escalate to Orchestrator
   └─ Budget found → Continue
   ↓
3. Validate budget schema
   ├─ Invalid → BLOCK, return validation errors
   └─ Valid → Continue
   ↓
4. Check budget expiry
   ├─ Expired → BLOCK, request budget renewal
   └─ Active → Continue
   ↓
5. Run preflight checks PF-01 to PF-10
   ├─ Any blocking check fails → BLOCK with details
   ├─ Warning checks fail → LOG warnings, continue
   └─ All pass → Continue
   ↓
6. Initialize enforcement context
   - Load file patterns
   - Load command allowlist
   - Set network policy
   - Initialize counters
   ↓
7. Begin task execution with enforcement active
```

### Preflight Evidence Template

```yaml
preflight_result:
  task_id: <task>
  budget_id: <budget>
  executed_at: <ISO8601>
  executed_by: <agent>

  checks:
    - check_id: PF-01
      status: <pass|fail|warn>
      details: <optional-details>
    # ... all checks

  outcome: <proceed|blocked|proceed_with_warnings>
  block_reason: <optional-reason>
  warnings: [<warning-list>]

  enforcement_context:
    file_patterns_loaded: <count>
    commands_allowed: <count>
    network_policy: <off|limited|open>
    limits_active: <list>
```

---

## Runtime Enforcement

### Enforcement Points

| Point | Trigger | Validation | Action |
|-------|---------|------------|--------|
| **EF-01** | File read | Path matches read patterns | Allow/Block |
| **EF-02** | File write | Path matches write patterns | Allow/Block |
| **EF-03** | Command execution | Command in allowlist | Allow/Block |
| **EF-04** | Network request | Domain in allowed list | Allow/Block |
| **EF-05** | Iteration increment | Count < max_iterations | Continue/Stop |
| **EF-06** | Duration check | Elapsed < max_duration | Continue/Stop |
| **EF-07** | Files modified | Count < max_files | Continue/Stop |
| **EF-08** | Lines changed | Count < max_lines | Continue/Stop |

### Enforcement Decision Tree

```
Action requested
    ↓
Is action type in budget?
├─ No → BLOCK (unknown action type)
└─ Yes → Check specific permissions
    ↓
Does action match allowed patterns?
├─ No → Check if in denied patterns
│   ├─ Yes → BLOCK (explicitly denied)
│   └─ No → BLOCK (not explicitly allowed)
└─ Yes → Check resource limits
    ↓
Are resource limits exceeded?
├─ Yes → STOP (limit reached)
└─ No → Check stop conditions
    ↓
Any stop condition triggered?
├─ Yes → Execute stop action
└─ No → ALLOW action
```

### Enforcement Log Schema

```yaml
enforcement_log:
  task_id: <task>
  budget_id: <budget>
  session_id: <session>

  entries:
    - timestamp: <ISO8601>
      action_type: <file_read|file_write|command|network|other>
      action_detail: <specific-action>
      enforcement_point: <EF-XX>
      decision: <allow|block|stop|escalate>
      reason: <decision-reason>
      resource_state:
        iterations: <current/max>
        duration_minutes: <current/max>
        files_modified: <current/max>
        lines_changed: <current/max>

  summary:
    total_actions: <count>
    allowed: <count>
    blocked: <count>
    stops_triggered: <count>
    escalations: <count>
```

---

## Stop Conditions

### Standard Stop Conditions

| ID | Condition | Default Action | Rationale |
|----|-----------|----------------|-----------|
| **SC-01** | Unclear acceptance criteria | Stop + Escalate | Cannot verify completion |
| **SC-02** | New risk trigger discovered | Stop + Escalate | Security review needed |
| **SC-03** | Scope change required | Stop + Escalate | Budget may need update |
| **SC-04** | Tests/verification unavailable | Stop + Warn | Cannot verify correctness |
| **SC-05** | Max iterations reached | Stop | Prevent infinite loops |
| **SC-06** | Max duration exceeded | Stop | Prevent runaway tasks |
| **SC-07** | Max files modified exceeded | Stop + Escalate | Scope creep detected |
| **SC-08** | Max lines changed exceeded | Stop + Escalate | Large change detected |
| **SC-09** | Repeated failures (3+) | Stop + Escalate | Possible blocker |
| **SC-10** | Security violation detected | Stop + Escalate | Immediate review |

### Stop Condition Schema

```yaml
stop_condition:
  condition_id: <SC-XX>
  description: <what-triggers-this>
  detection:
    method: <threshold|pattern|event>
    parameters:
      <param>: <value>
  action:
    type: <stop|escalate|warn|pause>
    target: <optional-escalation-target>
    message: <notification-message>
  recovery:
    resumable: <true|false>
    requires_approval: <true|false>
    approval_role: <optional-role>
```

### Stop Handling Workflow

```
Stop condition triggered
    ↓
Log stop event with context
    ↓
Determine action type
├─ STOP: Halt execution, preserve state
├─ ESCALATE: Halt + notify target
├─ WARN: Log warning, continue
└─ PAUSE: Halt, await approval
    ↓
If STOP or ESCALATE:
├─ Save current progress
├─ Record enforcement log
├─ Notify relevant parties
└─ Update task status to blocked
    ↓
If resumable:
├─ Document resume conditions
└─ Await approval or resolution
```

---

## Escalation Paths

### Escalation Triggers

| ID | Trigger | Urgency | Default Target |
|----|---------|---------|----------------|
| **ET-01** | Security violation | Immediate | Security Agent + Human |
| **ET-02** | Budget violation attempt | Immediate | Orchestrator |
| **ET-03** | Scope expansion needed | Normal | Orchestrator |
| **ET-04** | Repeated failures | Normal | Architect |
| **ET-05** | Resource limit exceeded | Normal | Orchestrator |
| **ET-06** | Unknown error | Normal | QA Agent |
| **ET-07** | Human judgment needed | Low | Director |
| **ET-08** | Policy clarification | Low | Orchestrator |

### Escalation Matrix

| From Agent | Security Issue | Scope Issue | Technical Issue | Policy Issue |
|------------|---------------|-------------|-----------------|--------------|
| Implementer | Security Agent | Orchestrator | Architect | Orchestrator |
| Tester | Security Agent | Orchestrator | Debugger | QA Agent |
| Documentation | Security Agent | Orchestrator | Architect | Orchestrator |
| Any Agent | Human (critical) | Director (block) | Human (unresolved) | Human (policy) |

### Escalation Record Schema

```yaml
escalation:
  escalation_id: <unique-id>
  task_id: <task>
  budget_id: <budget>

  trigger:
    type: <ET-XX>
    description: <what-triggered>
    detected_at: <ISO8601>
    detected_by: <agent>

  context:
    action_attempted: <what-was-tried>
    enforcement_log_ref: <path>
    current_state: <state-snapshot>

  routing:
    urgency: <immediate|normal|low>
    target: <escalation-target>
    notified_at: <ISO8601>
    acknowledged_at: <optional>

  resolution:
    status: <pending|acknowledged|resolved|deferred>
    resolved_by: <resolver>
    resolved_at: <ISO8601>
    decision: <approve|deny|modify>
    notes: <resolution-notes>
    budget_updated: <true|false>
```

### Escalation Workflow

```
Escalation triggered
    ↓
Create escalation record
    ↓
Determine urgency
├─ IMMEDIATE: Synchronous notification, block until ack
├─ NORMAL: Async notification, continue if safe
└─ LOW: Queue for review, continue
    ↓
Route to target
├─ Agent target: Send to agent queue
└─ Human target: Send notification, await response
    ↓
Track acknowledgment
├─ Ack received: Update record, await resolution
└─ No ack (timeout): Re-escalate or escalate higher
    ↓
Resolution received
├─ APPROVE: Update budget if needed, resume task
├─ DENY: Mark task blocked, document reason
└─ MODIFY: Apply modifications, resume with new constraints
```

---

## Policy Automation

### Automatable Policies

| Policy | Automation Level | Implementation |
|--------|-----------------|----------------|
| File pattern matching | Full | Regex validation |
| Command allowlist | Full | Exact or pattern match |
| Network domain check | Full | Domain allowlist |
| Resource counting | Full | Counter increment/check |
| Duration tracking | Full | Timer comparison |
| Stop condition detection | Full | Threshold/pattern match |
| Escalation routing | Full | Rule-based routing |
| Budget validation | Full | Schema validation |

### Policy Rule Schema

```yaml
policy_rule:
  rule_id: <unique-id>
  name: <rule-name>
  description: <what-it-does>

  trigger:
    event: <action_requested|threshold_reached|pattern_matched>
    conditions:
      - field: <field-to-check>
        operator: <eq|ne|gt|lt|gte|lte|matches|in|not_in>
        value: <comparison-value>

  action:
    type: <allow|block|warn|escalate|stop>
    parameters:
      <param>: <value>

  priority: <1-100>  # Higher = evaluated first
  enabled: <true|false>

  metadata:
    owner: <rule-owner>
    created_at: <ISO8601>
    last_modified: <ISO8601>
```

### Policy Evaluation Order

```
1. Security policies (highest priority)
   - Secrets detection
   - Injection patterns
   - Sandbox violations
   ↓
2. Explicit deny rules
   - Denied commands
   - Denied files
   - Denied domains
   ↓
3. Explicit allow rules
   - Allowed commands
   - Allowed files
   - Allowed domains
   ↓
4. Resource limit policies
   - Iteration limits
   - Duration limits
   - Size limits
   ↓
5. Default deny (if no rule matches)
```

---

## Budget Lifecycle

### Budget States

| State | Description | Transitions |
|-------|-------------|-------------|
| **DRAFT** | Being created/edited | → PENDING_APPROVAL |
| **PENDING_APPROVAL** | Awaiting approval | → ACTIVE, REJECTED |
| **ACTIVE** | In use for task | → SUSPENDED, EXPIRED, COMPLETED |
| **SUSPENDED** | Temporarily disabled | → ACTIVE, EXPIRED |
| **EXPIRED** | Past expiry date | → RENEWED (new budget) |
| **COMPLETED** | Task finished | Terminal |
| **REJECTED** | Approval denied | → DRAFT (revision) |

### Budget Modification Rules

| Modification | Requires | During Active Task |
|--------------|----------|-------------------|
| Expand scope | Approval | Pause task, re-preflight |
| Reduce scope | Notification | Apply immediately |
| Add command | Approval | Pause task |
| Remove command | Notification | Apply immediately |
| Extend limits | Approval | Apply after approval |
| Reduce limits | Notification | Apply immediately |
| Extend expiry | Approval | Apply after approval |

---

## Quick Reference

### Preflight Checklist Summary

- [ ] PF-01: Budget exists
- [ ] PF-02: Budget valid
- [ ] PF-03: Budget not expired
- [ ] PF-04: Scope defined
- [ ] PF-05: Files scoped
- [ ] PF-06: Commands scoped
- [ ] PF-07: Network scoped
- [ ] PF-08: Limits set (warn)
- [ ] PF-09: Stop conditions (warn)
- [ ] PF-10: Escalation path (warn)

### Stop Conditions Summary

| Condition | Action |
|-----------|--------|
| Unclear requirements | Stop + Escalate |
| New risk discovered | Stop + Escalate |
| Scope change needed | Stop + Escalate |
| Max iterations | Stop |
| Max duration | Stop |
| Security violation | Stop + Escalate |

### Escalation Quick Guide

| Issue Type | Target |
|------------|--------|
| Security | Security Agent → Human |
| Scope | Orchestrator → Director |
| Technical | Architect → Human |
| Policy | Orchestrator → Human |

---

## References

- Autonomy budget template: `core/orchestrator/handoff/AUTONOMY_BUDGET.md`
- Security hardening: `core/orchestrator/SECURITY_HARDENING.md`
- Tool governance: `core/orchestrator/TOOL_GOVERNANCE.md`
- Code execution contract: `core/orchestrator/CODE_EXECUTION_CONTRACT.md`
- Trace schema: `core/orchestrator/TRACE_SCHEMA.md`
