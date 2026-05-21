# Guardrails & Validation Hooks Specification

Purpose: Define pre/post execution validation hooks that enforce safety constraints on agent actions.

Related docs:
- `core/orchestrator/AUTONOMY_ENFORCEMENT.md` (autonomy budget and enforcement rules)
- `core/orchestrator/SECURITY_HARDENING.md` (sandbox and approval policies)
- `core/orchestrator/TOOL_GOVERNANCE.md` (tool allowlist policy)
- `core/orchestrator/CODE_EXECUTION_CONTRACT.md` (execution limits)
- `core/orchestrator/agent-protocols/AGENT_HANDOFF_PROTOCOL.md` (handoff validation)

Sources:
- Agency Swarm (CA-077 to CA-088)
- AGENT-33 AUTONOMY_ENFORCEMENT.md

---

## Guardrail Schema

```yaml
guardrail:
  id: string
  name: string
  type: pre_execution | post_execution | pre_handoff | post_handoff | on_error
  priority: number (lower = runs first)
  category: safety | quality | compliance | budget | scope
  condition:
    expression: string (when to apply this guardrail)
  validation:
    check: string (what to validate)
    threshold: number (optional)
    action_on_fail: block | warn | escalate | log
  bypass:
    allowed: boolean
    requires_approval: role_id
    audit_required: true
```

---

## 1. Hook Types

### 1.1 Pre-Execution

Runs before an agent executes any action (tool call, file write, command execution).

```yaml
pre_execution:
  trigger: agent is about to execute an action
  timing: synchronous (execution blocks until hook completes)
  purpose:
    - Validate the action is within scope
    - Check autonomy budget is sufficient
    - Verify tool is on the allowlist
    - Confirm target files are not locked by another agent
  on_block: action is prevented, agent receives rejection with reason
  on_warn: action proceeds, warning logged, agent notified
```

### 1.2 Post-Execution

Runs after an agent completes an action, before results are committed or forwarded.

```yaml
post_execution:
  trigger: agent has completed an action, results pending commit
  timing: synchronous (commit blocks until hook completes)
  purpose:
    - Validate output quality (no empty results, no obvious errors)
    - Check for sensitive data in output (secrets, credentials, PII)
    - Verify output conforms to expected schema
    - Update budget consumption counters
  on_block: results are discarded, action rolled back if possible
  on_warn: results committed with warning annotation
```

### 1.3 Pre-Handoff

Runs before an agent transfers control to another agent.

```yaml
pre_handoff:
  trigger: handoff initiated but not yet sent
  timing: synchronous (handoff blocks until hook completes)
  purpose:
    - Validate handoff payload is complete (context, artifacts, rationale)
    - Check receiving agent has required capabilities
    - Verify autonomy budget is sufficient for the receiving agent
    - Confirm no file lock conflicts
  on_block: handoff prevented, agent must resolve issues first
  on_warn: handoff proceeds with warning in audit trail
```

### 1.4 Post-Handoff

Runs after a handoff has been accepted by the receiving agent.

```yaml
post_handoff:
  trigger: receiving agent has acknowledged handoff
  timing: asynchronous (does not block workflow)
  purpose:
    - Log handoff completion in audit trail
    - Release file locks held by sending agent
    - Update task status in workflow tracker
    - Notify orchestrator of workflow progression
  on_block: not applicable (post-handoff hooks do not block)
  on_warn: warning logged for orchestrator review
```

### 1.5 On-Error

Runs when an agent encounters an error during execution.

```yaml
on_error:
  trigger: agent reports an error or exception
  timing: synchronous (error handling blocks until hook completes)
  purpose:
    - Classify error severity (recoverable, fatal, unknown)
    - Determine recovery action (retry, rollback, escalate)
    - Capture error context for diagnostics
    - Prevent cascading failures
  on_block: not applicable (error hooks always execute)
  actions:
    - retry: re-attempt the failed action (up to max_retries)
    - rollback: undo partial changes
    - escalate: forward to supervisor or human
    - quarantine: isolate the failing agent from further work
```

---

## 2. Validation Categories

### 2.1 Safety

Prevents actions that could cause harm to systems, data, or workflows.

```yaml
safety_guardrails:
  - id: safety-001
    name: destructive_command_block
    check: command does not match destructive patterns (rm -rf, DROP TABLE, force push)
    action_on_fail: block

  - id: safety-002
    name: sensitive_file_protection
    check: target file is not in protected paths (.env, credentials, keys)
    action_on_fail: block

  - id: safety-003
    name: output_secret_scan
    check: output does not contain API keys, passwords, tokens, or PII
    action_on_fail: block

  - id: safety-004
    name: sandbox_boundary
    check: action stays within designated sandbox directory
    action_on_fail: block
```

### 2.2 Quality

Ensures agent outputs meet minimum quality standards.

```yaml
quality_guardrails:
  - id: quality-001
    name: non_empty_output
    check: action produced non-trivial output
    action_on_fail: warn

  - id: quality-002
    name: schema_conformance
    check: output matches expected schema or format
    action_on_fail: block

  - id: quality-003
    name: test_pass_required
    check: modified code passes existing test suite
    action_on_fail: escalate

  - id: quality-004
    name: lint_clean
    check: modified code passes linting rules
    action_on_fail: warn
```

### 2.3 Compliance

Enforces organizational policies and workflow rules.

```yaml
compliance_guardrails:
  - id: compliance-001
    name: file_ownership_check
    check: agent has lock on file before writing
    action_on_fail: block

  - id: compliance-002
    name: review_before_merge
    check: code changes have been reviewed by reviewer agent
    action_on_fail: block

  - id: compliance-003
    name: branch_policy
    check: commits target correct branch per workflow rules
    action_on_fail: block

  - id: compliance-004
    name: documentation_required
    check: public API changes include documentation updates
    action_on_fail: warn
```

### 2.4 Budget

Enforces resource consumption limits.

```yaml
budget_guardrails:
  - id: budget-001
    name: token_budget_check
    check: cumulative tokens consumed < task.token_budget
    threshold: 0.9 (warn at 90%)
    action_on_fail: escalate (at 100%)

  - id: budget-002
    name: time_budget_check
    check: elapsed time < task.time_budget
    threshold: 0.8 (warn at 80%)
    action_on_fail: escalate (at 100%)

  - id: budget-003
    name: api_call_limit
    check: external API calls < task.api_call_budget
    action_on_fail: block

  - id: budget-004
    name: cost_ceiling
    check: estimated cost of action < remaining cost budget
    action_on_fail: escalate
```

### 2.5 Scope

Ensures agents stay within their assigned boundaries.

```yaml
scope_guardrails:
  - id: scope-001
    name: task_boundary
    check: action is relevant to assigned task (not drifting to unrelated work)
    action_on_fail: warn

  - id: scope-002
    name: file_scope
    check: file being modified is within allowed file patterns for this task
    action_on_fail: block

  - id: scope-003
    name: capability_scope
    check: action matches agent's declared capabilities
    action_on_fail: block

  - id: scope-004
    name: decision_authority
    check: decision is within agent's autonomy level
    action_on_fail: escalate
```

---

## 3. Hook Chaining

Multiple hooks can be attached to the same trigger point. They execute in priority order.

### 3.1 Execution Order

```yaml
hook_chain:
  ordering: by priority ascending (lower number = runs first)
  tie_breaking: by category order [safety, compliance, budget, scope, quality]
  execution: sequential (each hook runs after the previous completes)
  short_circuit:
    on_block: remaining hooks in chain are skipped
    on_warn: remaining hooks continue to execute
    on_escalate: remaining hooks continue, escalation queued
    on_log: remaining hooks continue
```

### 3.2 Chain Configuration Example

```yaml
pre_execution_chain:
  - guardrail: safety-001    # priority: 10
  - guardrail: safety-002    # priority: 10
  - guardrail: compliance-001 # priority: 20
  - guardrail: budget-001    # priority: 30
  - guardrail: scope-002     # priority: 40
  - guardrail: quality-002   # priority: 50
```

### 3.3 Chain Results Aggregation

```yaml
chain_result:
  final_verdict: pass | warn | block | escalate
  resolution:
    - if any hook returns "block": final verdict is "block"
    - if any hook returns "escalate" (and no block): final verdict is "escalate"
    - if any hook returns "warn" (and no block/escalate): final verdict is "warn"
    - if all hooks return "pass": final verdict is "pass"
  details:
    - guardrail_id: string
      result: pass | warn | block | escalate
      message: string
      duration_ms: number
```

---

## 4. Hook Results

### 4.1 Pass

The validation succeeded. No action required.

```yaml
pass:
  action: proceed with execution
  logging: optional (configurable per guardrail)
  notification: none
```

### 4.2 Warn

The validation detected a concern but not severe enough to block.

```yaml
warn:
  action: proceed with execution
  logging: required (warning recorded in audit trail)
  notification: agent receives warning message
  accumulation: 3 warnings on same guardrail within a task triggers automatic escalation
```

### 4.3 Block

The validation failed. The action must not proceed.

```yaml
block:
  action: prevent execution
  logging: required (block recorded in audit trail)
  notification: agent receives block reason and remediation guidance
  recovery:
    - agent may modify the action and retry
    - agent may request bypass (if allowed for this guardrail)
    - agent may escalate to supervisor
```

### 4.4 Escalate

The validation requires human or supervisor judgment.

```yaml
escalate:
  action: pause execution, forward to escalation target
  logging: required
  notification: escalation target receives full context
  escalation_target:
    priority_order: [reviewer, architect, human_operator]
  timeout: 30 minutes (if no response, default to block)
```

---

## 5. Built-in Guardrails

These guardrails are always active and cannot be disabled without emergency bypass.

### 5.1 Token Budget Enforcement

```yaml
builtin_token_budget:
  id: builtin-001
  type: pre_execution
  priority: 1
  check: |
    current_tokens + estimated_action_tokens <= task.token_budget
  thresholds:
    warn: 80% consumed
    escalate: 95% consumed
    block: 100% consumed
  action_on_fail: escalate
```

### 5.2 Time Budget Enforcement

```yaml
builtin_time_budget:
  id: builtin-002
  type: pre_execution
  priority: 2
  check: |
    current_elapsed + estimated_action_duration <= task.time_budget
  thresholds:
    warn: 70% elapsed
    escalate: 90% elapsed
    block: 100% elapsed
  action_on_fail: escalate
```

### 5.3 Scope Boundary Enforcement

```yaml
builtin_scope_boundary:
  id: builtin-003
  type: pre_execution
  priority: 3
  check: |
    action.target_files all match task.scope.files.write patterns
    AND action.target_files none match task.scope.files.deny patterns
  action_on_fail: block
```

### 5.4 Tool Allowlist Enforcement

```yaml
builtin_tool_allowlist:
  id: builtin-004
  type: pre_execution
  priority: 4
  check: |
    action.tool_name in agent.allowed_tools
    OR action.tool_name in task.additional_tools
  action_on_fail: block
```

---

## 6. Custom Guardrail Definitions

Users and workflow designers can define additional guardrails beyond the built-in set.

### 6.1 Custom Guardrail Template

```yaml
custom_guardrail:
  id: custom-{category}-{number}
  name: descriptive_name
  description: string (what this guardrail protects against)
  type: pre_execution | post_execution | pre_handoff | post_handoff | on_error
  priority: number (must be > 100, to run after built-in guardrails)
  category: safety | quality | compliance | budget | scope
  enabled: boolean
  condition:
    expression: string (when to apply, e.g., "agent.role == 'implementer'")
    applies_to:
      agents: [agent_id] | "*"
      tasks: [task_pattern] | "*"
      tools: [tool_name] | "*"
  validation:
    check: string (validation logic)
    threshold: number (optional)
    action_on_fail: block | warn | escalate | log
  bypass:
    allowed: boolean
    requires_approval: role_id
    audit_required: true
```

### 6.2 Custom Guardrail Example

```yaml
# Prevent implementer from modifying test files
custom_guardrail:
  id: custom-scope-001
  name: implementer_test_separation
  description: Implementer agents should not modify test files; test-writer handles tests.
  type: pre_execution
  priority: 110
  category: scope
  enabled: true
  condition:
    expression: "agent.role == 'implementer' AND action.type == 'file_write'"
    applies_to:
      agents: ["implementer-*"]
      tasks: "*"
      tools: ["Write", "Edit"]
  validation:
    check: "action.target_file does not match '**/test_*' AND '**/*_test.*'"
    action_on_fail: block
  bypass:
    allowed: true
    requires_approval: architect
    audit_required: true
```

---

## 7. Bypass Protocol

In exceptional circumstances, a guardrail may be bypassed. Bypasses are tightly controlled.

### 7.1 Bypass Request Schema

```yaml
bypass_request:
  id: string (uuid)
  guardrail_id: string
  requested_by: agent_id
  reason: string (required, must be substantive)
  urgency: normal | urgent | emergency
  timestamp: ISO-8601
```

### 7.2 Bypass Approval Flow

```yaml
bypass_flow:
  1_request: agent submits bypass request with reason
  2_validate: system checks if guardrail allows bypass (bypass.allowed == true)
  3_route: request routed to required approver (bypass.requires_approval)
  4_decide: approver reviews context and approves or denies
  5_execute: if approved, guardrail is suspended for this single action
  6_audit: bypass event recorded with full context

  approval_timeout: 15 minutes
  on_timeout:
    normal: deny bypass
    urgent: escalate to next authority
    emergency: auto-approve with mandatory post-review
```

### 7.3 Emergency Override

For situations where immediate action is critical and normal approval is too slow.

```yaml
emergency_override:
  condition: urgency == "emergency" AND no approver available within 60 seconds
  action: bypass granted automatically
  constraints:
    - only for safety-critical response actions (e.g., stopping a runaway process)
    - limited to single action, guardrail re-engages immediately after
    - mandatory post-incident review within 24 hours
  audit:
    level: critical
    notification: all supervisors and human operators notified immediately
    review_required: true
    review_deadline: 24 hours
```

---

## 8. Integration with Risk Triggers and Autonomy Enforcement

### 8.1 Risk Trigger Mapping

Guardrails integrate with the risk trigger system defined in AUTONOMY_ENFORCEMENT.md.

```yaml
risk_integration:
  risk_level_mapping:
    low:
      active_guardrails: [builtin-001, builtin-002, builtin-003, builtin-004]
      action_on_fail_default: warn
    medium:
      active_guardrails: [all builtin + safety-* + compliance-*]
      action_on_fail_default: escalate
    high:
      active_guardrails: [all guardrails]
      action_on_fail_default: block
    critical:
      active_guardrails: [all guardrails, strictest thresholds]
      action_on_fail_default: block
      additional: human approval required for any action
```

### 8.2 Autonomy Budget Interaction

```yaml
autonomy_interaction:
  budget_remaining_high: # >50% budget remaining
    guardrail_mode: standard
    bypass_allowed: per guardrail config
  budget_remaining_low: # 20-50% budget remaining
    guardrail_mode: strict (thresholds tightened by 20%)
    bypass_allowed: only with supervisor approval
  budget_remaining_critical: # <20% budget remaining
    guardrail_mode: lockdown (all warns become blocks)
    bypass_allowed: only with human approval
  budget_exhausted:
    guardrail_mode: halt (all actions blocked)
    bypass_allowed: emergency override only
```

---

## 9. Guardrail Lifecycle Management

### 9.1 Registration

```yaml
registration:
  method: guardrails defined in YAML configuration files
  location: core/orchestrator/agent-protocols/guardrails/
  loading: guardrails loaded at system startup and on configuration reload
  validation: guardrail definitions validated against schema before activation
```

### 9.2 Runtime State

```yaml
runtime_state:
  per_guardrail:
    enabled: boolean
    invocation_count: number
    pass_count: number
    warn_count: number
    block_count: number
    escalate_count: number
    avg_duration_ms: number
    last_triggered: ISO-8601
```

### 9.3 Monitoring and Alerting

```yaml
monitoring:
  metrics:
    - guardrail_invocations_total (counter, by guardrail_id and result)
    - guardrail_duration_ms (histogram, by guardrail_id)
    - guardrail_blocks_total (counter, by category)
    - bypass_requests_total (counter, by guardrail_id and outcome)
  alerts:
    - name: high_block_rate
      condition: block_rate > 30% over 10 minute window
      action: notify orchestrator
    - name: bypass_abuse
      condition: bypass_requests > 5 per agent per hour
      action: notify human operator
    - name: guardrail_slow
      condition: avg_duration_ms > 500
      action: log warning, consider optimization
```

---

## 10. Implementation Notes

- Built-in guardrails have priority 1-99. Custom guardrails must use priority 100+.
- Guardrail evaluation is synchronous for pre-execution and pre-handoff hooks to prevent unsafe actions.
- Post-execution and post-handoff hooks may run asynchronously where blocking is unnecessary.
- Guardrail configuration is hot-reloadable; changes take effect without system restart.
- All guardrail results are included in the execution trace for full observability.
- Bypass audit records are permanent and cannot be deleted or modified.
- The guardrail system itself has a self-check: if guardrail evaluation fails (crash, timeout), the default action is "block" (fail-closed).
