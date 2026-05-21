# Example: Evidence Capture Hook

This document provides a complete implementation example of the PostTask Evidence Capture hook (HOOK-002).

## Overview

The evidence capture hook automatically logs commands and outcomes when a task completes. It integrates with TASKS.md for task context and verification-log.md for long-term evidence storage.

## Hook Specification

```yaml
hook:
  id: HOOK-002
  name: PostTask Evidence Capture
  trigger: PostTask
  scope: task
  action: Auto-log commands and outcomes to verification log
  evidence_capture:
    enabled: true
    target: core/arch/verification-log.md
    format: structured
  blocking: false
  severity: warning
```

## Integration Points

### Input Sources

| Source | Purpose | Path |
|--------|---------|------|
| Task Context | Task ID, acceptance criteria, branch | `core/orchestrator/handoff/TASKS.md` |
| Command History | Commands executed during task | Session runtime context |
| Session Log | Full session evidence | `docs/session-logs/SESSION-*.md` |

### Output Targets

| Target | Purpose | Path |
|--------|---------|------|
| Verification Log | Long-term evidence index | `core/arch/verification-log.md` |
| Task Entry | Task completion status | `core/orchestrator/handoff/TASKS.md` |

## Pseudo-Code Implementation

```
HOOK: PostTask Evidence Capture
TRIGGER: Task completion (success or failure)

FUNCTION execute_hook(task_context, command_history, session_id):
    
    # 1. Extract task metadata
    task_id = task_context.id
    task_branch = task_context.branch OR "N/A"
    task_result = task_context.outcome  # "success" | "failure" | "partial"
    
    # 2. Collect evidence from command history
    evidence_commands = []
    FOR EACH command IN command_history:
        IF command.is_verification_relevant():
            evidence_commands.APPEND({
                command: command.text,
                exit_code: command.exit_code,
                output_summary: command.output.truncate(500)
            })
    
    # 3. Determine verification command to record
    # Priority: test command > build command > manual verification
    IF evidence_commands.has_test_command():
        primary_command = evidence_commands.get_test_command().command
    ELSE IF evidence_commands.has_build_command():
        primary_command = evidence_commands.get_build_command().command
    ELSE:
        primary_command = "N/A (manual verification)"
    
    # 4. Format verification log entry
    log_entry = {
        date: current_date(),
        cycle_id: task_id,
        branch: task_branch,
        command: primary_command,
        result: format_result(task_result),
        session_link: format_session_path(session_id)
    }
    
    # 5. Append to verification log
    verification_log = READ("core/arch/verification-log.md")
    verification_log.append_to_index(log_entry)
    WRITE("core/arch/verification-log.md", verification_log)
    
    # 6. Update task entry with evidence link
    tasks_file = READ("core/orchestrator/handoff/TASKS.md")
    task_entry = tasks_file.find_task(task_id)
    task_entry.evidence_link = log_entry.session_link
    task_entry.verification_status = task_result
    WRITE("core/orchestrator/handoff/TASKS.md", tasks_file)
    
    # 7. Return hook result
    RETURN {
        success: TRUE,
        evidence_captured: TRUE,
        log_entry: log_entry
    }

FUNCTION format_result(outcome):
    MATCH outcome:
        "success" -> "verified"
        "failure" -> "failed"
        "partial" -> "partial (see session log)"
        DEFAULT -> "not run (reason pending)"

FUNCTION format_session_path(session_id):
    RETURN "docs/session-logs/SESSION-{date}_{session_id}.md"
```

## Example Execution

### Scenario

A task T29 completes after running build and test commands.

### Input

```yaml
task_context:
  id: T29
  name: "Add hooks system specification"
  branch: feature/hooks-system-specification
  outcome: success
  
command_history:
  - text: "npm run build"
    exit_code: 0
    output: "Build completed successfully"
  - text: "npm run test"
    exit_code: 0
    output: "42 tests passed"
  - text: "git status"
    exit_code: 0
    output: "nothing to commit"

session_id: "HOOKS-PHASE-1"
```

### Output

**Verification Log Entry**:
```
| 2026-01-20 | T29 | feature/hooks-system-specification | npm run test | verified | docs/session-logs/SESSION-2026-01-20_HOOKS-PHASE-1.md | N/A |
```

**TASKS.md Update**:
```markdown
### T29: Add hooks system specification
- **Status**: Done
- **Evidence**: `docs/session-logs/SESSION-2026-01-20_HOOKS-PHASE-1.md`
- **Verification**: verified via `npm run test`
```

## Edge Cases

### No Test Harness

When the repository has no test suite:

```
command: "N/A (docs-only repo; no test harness)"
result: "not run"
```

The hook still records this explicitly rather than leaving blank entries.

### Partial Verification

When some tests pass but verification is incomplete:

```
command: "npm run test -- --grep integration"
result: "partial (unit tests passed; integration skipped)"
```

### Command Failure

When verification commands fail:

```
command: "npm run test"
result: "failed (see session log for stack trace)"
```

The hook captures the failure and links to the full session log for details.

## Configuration Options

Implementations may support these optional parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `capture_output` | boolean | true | Include command output in evidence |
| `max_output_length` | integer | 500 | Truncate output at this length |
| `include_timing` | boolean | false | Record command execution time |
| `auto_link_pr` | boolean | true | Auto-detect and link PR number |

## Related Documents

- `core/workflows/hooks/README.md` - Hooks system overview
- `core/workflows/hooks/HOOK_REGISTRY.md` - Full hook registry
- `core/arch/verification-log.md` - Verification log format
- `core/orchestrator/handoff/EVIDENCE_CAPTURE.md` - Evidence capture specification
