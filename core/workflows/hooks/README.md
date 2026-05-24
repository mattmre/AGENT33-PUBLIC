# Hooks System

This document defines the model-agnostic hooks system for AGENT-33 orchestration.

## Overview

Hooks are automation triggers that execute at defined points in the orchestration lifecycle. They enable consistent enforcement of governance policies, evidence capture, and workflow automation without coupling to any specific model or tool.

## Design Principles

1. **Model-Agnostic**: Hooks define *what* should happen, not *how* a specific model should do it.
2. **Evidence-First**: Every hook execution should produce auditable evidence.
3. **Composable**: Hooks can be combined and chained for complex workflows.
4. **Fail-Safe**: Hook failures should block or warn, never silently pass.

## Hook Points

### PreTask

Triggers before a task begins execution.

- **Purpose**: Validate preconditions, check task readiness, enforce governance.
- **Common Uses**:
  - Verify acceptance criteria exist in TASKS.md
  - Check autonomy budget is within limits
  - Validate required context files are present
- **Blocks Execution**: Yes, if validation fails.

### PostTask

Triggers after a task completes (success or failure).

- **Purpose**: Capture evidence, update logs, trigger downstream actions.
- **Common Uses**:
  - Log commands and outcomes to verification-log.md
  - Update TASKS.md with completion status
  - Trigger review if risk triggers apply
- **Blocks Execution**: No, but may require manual follow-up.

### SessionStart

Triggers when an orchestration session begins.

- **Purpose**: Establish context, verify state, load configuration.
- **Common Uses**:
  - Verify STATUS.md is current and accurate
  - Load active tasks from TASKS.md
  - Check for pending handoff items
- **Blocks Execution**: Yes, if critical state is invalid.

### SessionEnd

Triggers when an orchestration session concludes.

- **Purpose**: Generate summaries, prepare handoff, archive session data.
- **Common Uses**:
  - Generate session wrap summary
  - Update next-session.md
  - Archive session log to docs/session-logs/
- **Blocks Execution**: No, but may warn on incomplete items.

### PreCommit

Triggers before a commit is created.

- **Purpose**: Validate code quality, security, and compliance before commit.
- **Common Uses**:
  - Scan for secrets and credentials
  - Verify no debug code remains
  - Check commit message format
- **Blocks Execution**: Yes, if validation fails.

### PostVerify

Triggers after verification steps complete.

- **Purpose**: Record verification outcomes, update audit trail.
- **Common Uses**:
  - Update verification-log.md with results
  - Link evidence to task and session
  - Flag regression failures
- **Blocks Execution**: No, but may escalate failures.

## Integration with Evidence Capture

Hooks integrate directly with AGENT-33's evidence capture system:

1. **Automatic Logging**: Hook executions are logged with timestamp, trigger, and outcome.
2. **Cross-Reference**: Hook outputs link to relevant TASKS.md entries and session logs.
3. **Audit Trail**: All hook failures are recorded in verification-log.md.

See `core/orchestrator/handoff/EVIDENCE_CAPTURE.md` for the evidence capture specification.

## Integration with Existing Workflows

| Hook Point | Related Document | Integration |
|------------|------------------|-------------|
| PreTask | `core/orchestrator/handoff/TASKS.md` | Validates task has acceptance criteria |
| PostTask | `core/arch/verification-log.md` | Records task completion evidence |
| SessionStart | `core/orchestrator/handoff/STATUS.md` | Verifies current state |
| SessionEnd | `core/arch/next-session.md` | Prepares handoff context |
| PreCommit | `core/orchestrator/SECURITY_HARDENING.md` | Enforces security checks |
| PostVerify | `core/arch/verification-log.md` | Updates verification index |

## Hook Registry

See `core/workflows/hooks/HOOK_REGISTRY.md` for the full registry of available hooks.

## Examples

See `core/workflows/hooks/examples/` for complete hook implementation examples.

## Related Documents

- `core/orchestrator/OPERATOR_MANUAL.md` - Orchestration entrypoint
- `core/orchestrator/handoff/EVIDENCE_CAPTURE.md` - Evidence capture specification
- `core/arch/workflow.md` - AEP workflow definition
- `core/orchestrator/AUTONOMY_ENFORCEMENT.md` - Autonomy budget enforcement
