# Command Registry

This registry defines all available commands in the AGENT-33 orchestration framework.

Related docs:
- `core/orchestrator/OPERATOR_MANUAL.md` (operator usage guide)
- `core/packs/policy-pack-v1/ORCHESTRATION.md` (workflow protocol)

## Schema

Each command definition follows this schema:

```yaml
id: string           # Unique identifier (lowercase, no prefix)
name: string         # Display name with / prefix
description: string  # Brief purpose statement
workflow: string     # Path to workflow specification
triggers:            # What invokes this command
  - manual           # Operator-initiated
  - scheduled        # Time-based
  - event            # Triggered by system event
inputs:              # Required context documents
  - document: string # Handoff doc path
    required: bool   # Whether mandatory
outputs:             # Produced artifacts
  - document: string # Output path or pattern
    action: string   # create | update | append
```

---

## Available Commands

| Command | Purpose | Skill Invoked |
|---------|---------|---------------|
| `/status` | Review current STATUS.md and surface blockers | - |
| `/tasks` | List open tasks from TASKS.md with priorities | - |
| `/verify` | Capture verification evidence for current task | - |
| `/handoff` | Generate session wrap summary for next session | - |
| `/plan` | Create implementation plan with confirmation wait | - |
| `/review` | Trigger code review workflow | - |
| `/tdd` | Test-Driven Development workflow | tdd-workflow |
| `/build-fix` | Fix build or test failures | - |
| `/docs` | Sync documentation with code | - |
| `/e2e` | Generate or run E2E tests | - |
| `/refactor` | Clean up dead code or refactor | coding-standards |

---

## Registered Commands

### Phase 2 Commands

### /status

| Field | Value |
|-------|-------|
| id | `status` |
| name | `/status` |
| description | Review current STATUS.md and surface blockers |
| workflow | `commands/status.md` |
| triggers | manual |
| inputs | `handoff/STATUS.md`, `handoff/TASKS.md`, `handoff/PLAN.md`, `handoff/PRIORITIES.md` |
| outputs | Summary report (stdout) |

---

### /tasks

| Field | Value |
|-------|-------|
| id | `tasks` |
| name | `/tasks` |
| description | List open tasks from TASKS.md with priorities |
| workflow | `commands/tasks.md` |
| triggers | manual |
| inputs | `handoff/TASKS.md`, `handoff/PRIORITIES.md`, `handoff/DEFINITION_OF_DONE.md` |
| outputs | Task list (stdout) |

---

### /verify

| Field | Value |
|-------|-------|
| id | `verify` |
| name | `/verify` |
| description | Capture verification evidence for current task |
| workflow | `commands/verify.md` |
| triggers | manual |
| inputs | Current task context, test commands |
| outputs | `verification-log.md` (append) |

---

### /handoff

| Field | Value |
|-------|-------|
| id | `handoff` |
| name | `/handoff` |
| description | Generate session wrap summary for next session |
| workflow | `commands/handoff.md` |
| triggers | manual |
| inputs | `handoff/STATUS.md`, `handoff/TASKS.md`, `handoff/DECISIONS.md`, `handoff/PLAN.md`, `handoff/PRIORITIES.md` |
| outputs | `handoff/SESSION_WRAP.md` (append) |

---

### /plan

| Field | Value |
|-------|-------|
| id | `plan` |
| name | `/plan` |
| description | Create implementation plan with confirmation wait |
| workflow | `commands/plan.md` |
| triggers | manual |
| inputs | User request, `handoff/TASKS.md`, `handoff/PLAN.md`, `handoff/PRIORITIES.md`, `ACCEPTANCE_CHECKS.md` |
| outputs | `handoff/PLAN.md` (update), `handoff/TASKS.md` (append) |

---

### /review

| Field | Value |
|-------|-------|
| id | `review` |
| name | `/review` |
| description | Trigger code review workflow |
| workflow | `commands/review.md` |
| triggers | manual, event (PR opened) |
| inputs | Code diff, `RISK_TRIGGERS.md`, `AGENT_ROUTING_MAP.md`, `TWO_LAYER_REVIEW.md`, `REVIEW_CHECKLIST.md` |
| outputs | `handoff/REVIEW_CAPTURE.md` (append) |

---

### Phase 4 Commands

### /tdd

- **[/tdd](./tdd.md)** - Direct entry point for TDD workflow
  - Invoke TDD skill, track RED/GREEN/REFACTOR stages
  - Outputs: Tests, implementation, evidence

---

### /build-fix

- **[/build-fix](./build-fix.md)** - Fix build or test failures
  - Analyze error output, identify root cause, apply minimal fix
  - Outputs: Fixed code, verification evidence

---

### /refactor

- **[/refactor](./refactor.md)** - Code cleanup and refactoring
  - Identify candidates, verify no behavior change
  - Outputs: Refactored code, test verification

---

### /e2e

- **[/e2e](./e2e.md)** - End-to-end testing
  - Identify critical flows, create scenarios, capture evidence
  - Outputs: E2E test files, execution results

---

### /docs

- **[/docs](./docs.md)** - Documentation synchronization
  - Identify affected docs, update content, verify links
  - Outputs: Updated docs, link verification

---

## Command Conventions

### Invocation
```
/<command> [required-args] [optional-args]
```

### Standard Outputs
All commands should produce:
1. Primary artifacts (code, docs, tests)
2. Evidence of execution
3. TASKS.md update

### Error Handling
- Commands should fail gracefully with clear messages
- Partial progress should be captured in STATUS.md
- Escalation path should be clear

---

## Adding New Commands

1. Create command specification in `commands/<id>.md`
2. Add entry to this registry following the schema
3. Update `core/ORCHESTRATION_INDEX.md` if command affects orchestration flow
4. Document any new handoff artifacts in `core/orchestrator/handoff/`

### Command Template Structure

```markdown
# /<command-name> Command

Purpose: <one-line description>

Related docs:
- <related-file-1>
- <related-file-2>

---

## Command Signature
## Workflow
## Inputs
## Outputs
## Evidence Capture
## Example Usage
```

## Related Documents

- `commands/README.md`: Commands specification
- `core/ORCHESTRATION_INDEX.md`: Orchestration index
- `core/orchestrator/AGENT_ROUTING_MAP.md`: Role routing
