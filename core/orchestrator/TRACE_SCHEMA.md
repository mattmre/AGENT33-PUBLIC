# Trace Schema & Artifact Retention

Purpose: Define trace schema for agent runs, failure taxonomy, and artifact retention rules to enable audit-friendly reconstruction.

Related docs:
- `core/orchestrator/handoff/EVIDENCE_CAPTURE.md` (evidence template)
- `core/arch/verification-log.md` (verification entries)
- `core/orchestrator/TWO_LAYER_REVIEW.md` (review signoff records)
- `core/orchestrator/CODE_EXECUTION_CONTRACT.md` (execution outputs)

---

## Trace Schema

### Trace Hierarchy

```
Session
└── Run
    └── Task
        └── Step
            └── Action
```

| Level | ID Format | Description |
|-------|-----------|-------------|
| **Session** | `SES-YYYYMMDD-HHMMSS-XXXX` | Single agent session from start to end |
| **Run** | `RUN-YYYYMMDD-HHMMSS-XXXX` | Single execution cycle within session |
| **Task** | `T##` or `TSK-XXXX` | Discrete unit of work from TASKS.md |
| **Step** | `STP-###` | Numbered step within task |
| **Action** | `ACT-###` | Individual tool call or operation |

### Full Trace Schema

```yaml
trace:
  # Identity
  trace_id: <unique-trace-id>
  session_id: <parent-session-id>
  run_id: <parent-run-id>
  task_id: <associated-task-id>

  # Timing
  started_at: <ISO8601>
  completed_at: <ISO8601>
  duration_ms: <milliseconds>

  # Context
  context:
    agent_id: <executing-agent-id>
    agent_role: <agent-role>
    model: <model-identifier>
    branch: <git-branch>
    commit: <commit-hash>
    working_directory: <path>

  # Input
  input:
    prompt: <initial-prompt-or-task>
    parameters: <key-value-pairs>
    files_read: [<file-paths>]
    context_loaded: [<context-refs>]

  # Execution
  execution:
    steps:
      - step_id: <STP-###>
        started_at: <ISO8601>
        completed_at: <ISO8601>
        actions:
          - action_id: <ACT-###>
            tool: <tool-name>
            input: <tool-input>
            output: <tool-output>
            exit_code: <code>
            duration_ms: <ms>
            status: <success|failure|timeout|skipped>

  # Output
  output:
    result: <final-output>
    files_written: [<file-paths>]
    files_modified: [<file-paths>]
    artifacts_created: [<artifact-refs>]

  # Outcome
  outcome:
    status: <completed|failed|timeout|cancelled|escalated>
    failure_code: <optional-failure-code>
    failure_message: <optional-failure-message>
    failure_category: <optional-category>

  # Evidence
  evidence:
    verification_log_ref: <path>
    evidence_capture_ref: <path>
    session_log_ref: <path>
    review_signoff_ref: <optional-path>

  # Metadata
  metadata:
    tags: [<tag-list>]
    annotations: <key-value-pairs>
    parent_trace: <optional-parent-trace-id>
    child_traces: [<child-trace-ids>]
```

### Minimal Trace Schema

For lightweight logging, use this minimal schema:

```yaml
trace_minimal:
  trace_id: <id>
  task_id: <task>
  agent_id: <agent>
  started_at: <ISO8601>
  completed_at: <ISO8601>
  status: <completed|failed>
  failure_code: <optional>
  evidence_ref: <path>
```

---

## Failure Taxonomy

### Failure Categories

| Code | Category | Description | Retry | Escalate |
|------|----------|-------------|-------|----------|
| **F-ENV** | Environment | Setup, deps, permissions | Yes | After 2 retries |
| **F-INP** | Input | Invalid input, missing files | No | Immediately |
| **F-EXE** | Execution | Runtime errors, crashes | Yes | After 1 retry |
| **F-TMO** | Timeout | Exceeded time limit | Yes | After 1 retry |
| **F-RES** | Resource | Memory, disk, network | Yes | After 1 retry |
| **F-SEC** | Security | Blocked by policy | No | Immediately |
| **F-DEP** | Dependency | External service failure | Yes | After 3 retries |
| **F-VAL** | Validation | Output validation failed | No | Review needed |
| **F-REV** | Review | Reviewer rejected | No | Fix and resubmit |
| **F-UNK** | Unknown | Unclassified failure | No | Immediately |

### Failure Subcodes

#### F-ENV: Environment Failures

| Subcode | Description | Example |
|---------|-------------|---------|
| F-ENV-001 | Missing dependency | npm package not installed |
| F-ENV-002 | Wrong version | Python 3.8 required, 3.7 found |
| F-ENV-003 | Permission denied | Cannot write to directory |
| F-ENV-004 | Path not found | Working directory missing |
| F-ENV-005 | Config invalid | Malformed config file |

#### F-INP: Input Failures

| Subcode | Description | Example |
|---------|-------------|---------|
| F-INP-001 | Missing required input | No task ID provided |
| F-INP-002 | Invalid format | JSON parse error |
| F-INP-003 | File not found | Input file missing |
| F-INP-004 | Schema violation | Input doesn't match schema |
| F-INP-005 | Encoding error | Non-UTF8 input |

#### F-EXE: Execution Failures

| Subcode | Description | Example |
|---------|-------------|---------|
| F-EXE-001 | Command failed | Non-zero exit code |
| F-EXE-002 | Exception thrown | Unhandled runtime exception |
| F-EXE-003 | Assertion failed | Test assertion failed |
| F-EXE-004 | Infinite loop | Detected non-termination |
| F-EXE-005 | Deadlock | Resource deadlock detected |

#### F-TMO: Timeout Failures

| Subcode | Description | Example |
|---------|-------------|---------|
| F-TMO-001 | Step timeout | Single step exceeded limit |
| F-TMO-002 | Task timeout | Total task exceeded limit |
| F-TMO-003 | Network timeout | API call timed out |
| F-TMO-004 | Lock timeout | Could not acquire lock |
| F-TMO-005 | Idle timeout | No activity detected |

#### F-SEC: Security Failures

| Subcode | Description | Example |
|---------|-------------|---------|
| F-SEC-001 | Allowlist violation | Tool not in allowlist |
| F-SEC-002 | Sandbox violation | Attempted escape |
| F-SEC-003 | Secrets exposure | Secret detected in output |
| F-SEC-004 | Injection blocked | Prompt injection detected |
| F-SEC-005 | Approval denied | Human denied approval |

#### F-VAL: Validation Failures

| Subcode | Description | Example |
|---------|-------------|---------|
| F-VAL-001 | Output schema mismatch | Output doesn't match schema |
| F-VAL-002 | Acceptance criteria unmet | Test failed |
| F-VAL-003 | Quality gate failed | Lint errors |
| F-VAL-004 | Coverage insufficient | Below threshold |
| F-VAL-005 | Diff too large | Exceeded change limit |

### Failure Record Schema

```yaml
failure:
  trace_id: <parent-trace-id>
  failure_id: <unique-failure-id>
  occurred_at: <ISO8601>

  classification:
    code: <F-XXX>
    subcode: <F-XXX-###>
    category: <category-name>
    severity: <low|medium|high|critical>

  details:
    message: <human-readable-message>
    stack_trace: <optional-stack-trace>
    context: <relevant-context>
    input_snapshot: <relevant-input>
    output_snapshot: <relevant-output>

  resolution:
    retryable: <true|false>
    retry_count: <attempts>
    escalation_required: <true|false>
    escalation_target: <role-or-human>
    resolution_status: <pending|resolved|wontfix>
    resolution_notes: <optional-notes>

  evidence:
    log_ref: <path-to-logs>
    artifact_refs: [<paths>]
```

---

## Artifact Retention Rules

### Artifact Types

| Type | Description | Examples |
|------|-------------|----------|
| **LOG** | Execution logs | Console output, debug logs |
| **OUT** | Command outputs | Tool results, API responses |
| **DIF** | Diff artifacts | Git diffs, file comparisons |
| **TST** | Test artifacts | Test results, coverage reports |
| **REV** | Review artifacts | Review comments, signoff records |
| **EVD** | Evidence captures | Verification evidence |
| **SES** | Session logs | Full session transcripts |
| **CFG** | Configuration | Config snapshots |
| **TMP** | Temporary | Intermediate files |

### Retention Periods

| Artifact Type | Retention | Storage Tier | Rationale |
|---------------|-----------|--------------|-----------|
| **LOG** | 30 days | Hot | Debugging, audit |
| **OUT** | 30 days | Hot | Debugging |
| **DIF** | 90 days | Warm | Code review, audit |
| **TST** | 90 days | Warm | Quality tracking |
| **REV** | Permanent | Cold | Compliance, audit |
| **EVD** | Permanent | Cold | Compliance, audit |
| **SES** | 90 days | Warm | Debugging, training |
| **CFG** | 90 days | Warm | Reproducibility |
| **TMP** | 7 days | Hot | Cleanup |

### Storage Tiers

| Tier | Access Time | Cost | Use Case |
|------|-------------|------|----------|
| **Hot** | Immediate | High | Active debugging, recent runs |
| **Warm** | Minutes | Medium | Historical analysis, audits |
| **Cold** | Hours | Low | Long-term compliance, archives |

### Storage Paths

```
artifacts/
├── sessions/
│   └── YYYY/
│       └── MM/
│           └── DD/
│               └── SES-{id}/
│                   ├── session.log
│                   ├── runs/
│                   │   └── RUN-{id}/
│                   │       ├── trace.yaml
│                   │       ├── logs/
│                   │       ├── outputs/
│                   │       └── artifacts/
│                   └── metadata.yaml
├── evidence/
│   └── YYYY/
│       └── MM/
│           └── T{id}/
│               ├── evidence-capture.md
│               ├── verification.md
│               └── attachments/
├── reviews/
│   └── YYYY/
│       └── MM/
│           └── T{id}/
│               ├── signoff.yaml
│               └── comments/
└── archive/
    └── YYYY/
        └── Q{1-4}/
            └── {compressed-bundles}
```

### Retention Policy Schema

```yaml
retention_policy:
  policy_id: <unique-id>
  artifact_type: <LOG|OUT|DIF|TST|REV|EVD|SES|CFG|TMP>

  retention:
    period_days: <days>
    tier_transitions:
      - from_tier: hot
        to_tier: warm
        after_days: <days>
      - from_tier: warm
        to_tier: cold
        after_days: <days>

  deletion:
    auto_delete: <true|false>
    delete_after_days: <days>
    require_confirmation: <true|false>

  exceptions:
    hold_on_failure: <true|false>
    hold_on_review: <true|false>
    legal_hold: <true|false>

  metadata:
    owner: <owner>
    created_at: <ISO8601>
    updated_at: <ISO8601>
```

### Cleanup Rules

| Rule | Trigger | Action |
|------|---------|--------|
| **CL-001** | TMP artifact > 7 days | Auto-delete |
| **CL-002** | LOG artifact > 30 days, no failure | Archive or delete |
| **CL-003** | Hot artifact > 30 days | Move to warm |
| **CL-004** | Warm artifact > 90 days | Move to cold or delete |
| **CL-005** | Failed run artifacts | Extend retention by 30 days |
| **CL-006** | Under review | Hold until review complete |
| **CL-007** | Legal hold flag | Indefinite retention |

---

## Logging Standards

### Log Entry Schema

```yaml
log_entry:
  timestamp: <ISO8601>
  level: <DEBUG|INFO|WARN|ERROR|FATAL>
  trace_id: <trace-id>
  step_id: <optional-step-id>
  action_id: <optional-action-id>

  source:
    agent_id: <agent>
    component: <component>
    function: <function>

  message: <log-message>

  context:
    <key>: <value>

  error:
    code: <optional-error-code>
    stack: <optional-stack-trace>
```

### Log Levels

| Level | Use Case | Retention |
|-------|----------|-----------|
| **DEBUG** | Development details | 7 days |
| **INFO** | Normal operations | 30 days |
| **WARN** | Potential issues | 30 days |
| **ERROR** | Failures | 90 days |
| **FATAL** | Critical failures | Permanent |

### Structured Logging Requirements

| Requirement | Description |
|-------------|-------------|
| **SL-01** | Always include trace_id |
| **SL-02** | Use ISO8601 timestamps |
| **SL-03** | Use consistent log levels |
| **SL-04** | Include context for errors |
| **SL-05** | No secrets in logs |
| **SL-06** | Machine-parseable format (JSON) |

---

## Integration Points

### Session Log Integration

Session logs should reference traces:

```markdown
## Trace References
- Session: SES-20260116-143022-A1B2
- Run: RUN-20260116-143025-C3D4
- Task: T24
- Evidence: artifacts/evidence/2026/01/T24/
```

### Verification Log Integration

Verification log entries should include trace IDs:

```markdown
| date | cycle-id | trace-id | command | result | evidence |
| 2026-01-16 | T24 | RUN-20260116-143025-C3D4 | ... | ... | ... |
```

### TASKS.md Integration

Task entries should reference traces on completion:

```markdown
- [x] T24: Trace schema + artifact retention
  - Trace: RUN-20260116-143025-C3D4
  - Evidence: artifacts/evidence/2026/01/T24/
```

---

## Quick Reference

### Trace ID Formats

| ID Type | Format | Example |
|---------|--------|---------|
| Session | `SES-YYYYMMDD-HHMMSS-XXXX` | `SES-20260116-143022-A1B2` |
| Run | `RUN-YYYYMMDD-HHMMSS-XXXX` | `RUN-20260116-143025-C3D4` |
| Task | `T##` | `T24` |
| Step | `STP-###` | `STP-001` |
| Action | `ACT-###` | `ACT-001` |
| Failure | `FLR-YYYYMMDD-XXXX` | `FLR-20260116-E5F6` |

### Failure Quick Lookup

| Category | Code | Retry? | Escalate? |
|----------|------|--------|-----------|
| Environment | F-ENV | Yes | After 2 |
| Input | F-INP | No | Immediately |
| Execution | F-EXE | Yes | After 1 |
| Timeout | F-TMO | Yes | After 1 |
| Security | F-SEC | No | Immediately |
| Validation | F-VAL | No | Review |

### Retention Quick Lookup

| Type | Days | Tier |
|------|------|------|
| TMP | 7 | Hot |
| LOG, OUT | 30 | Hot→Warm |
| DIF, TST, SES, CFG | 90 | Warm→Cold |
| REV, EVD | Permanent | Cold |

---

## References

- Evidence capture: `core/orchestrator/handoff/EVIDENCE_CAPTURE.md`
- Verification log: `core/arch/verification-log.md`
- Two-layer review: `core/orchestrator/TWO_LAYER_REVIEW.md`
- Code execution: `core/orchestrator/CODE_EXECUTION_CONTRACT.md`
- Session logs: `docs/session-logs/`
