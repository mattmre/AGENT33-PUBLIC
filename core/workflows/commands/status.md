# /status Command

## Purpose

Review current operational state from `STATUS.md` and surface blockers, constraints, or pending actions that require attention.

## Invocation

```
/status
```

No arguments required.

## Workflow

### 1. Context Load

Read the following handoff documents:
- `core/orchestrator/handoff/STATUS.md`
- `core/orchestrator/handoff/TASKS.md`
- `core/orchestrator/handoff/PLAN.md`
- `core/orchestrator/handoff/PRIORITIES.md`

### 2. State Analysis

Extract and synthesize:
- **Current Task**: Active task from TASKS.md (status: `in_progress`)
- **Blockers**: Any tasks with status `blocked` and their dependencies
- **Runtime State**: Constraints and assumptions from STATUS.md
- **Priorities**: Current rolling horizon from PRIORITIES.md

### 3. Blocker Detection

Flag items requiring attention:
- Tasks blocked > 24 hours
- Missing dependencies or undefined owners
- Escalation triggers from `ESCALATION_PATHS.md`
- Resource constraints documented in STATUS.md

### 4. Output Generation

Produce a structured summary:

```markdown
## Current State

**Active Task**: [task-id] - [description]
**Owner**: [assigned owner]
**Status**: [in_progress | blocked | review]

## Blockers

| Task | Blocker | Duration | Escalation |
|------|---------|----------|------------|
| ... | ... | ... | ... |

## Next Actions

1. [Recommended action]
2. [Recommended action]

## Runtime Notes

- [Any relevant constraints or warnings]
```

## Outputs

| Output | Destination | Action |
|--------|-------------|--------|
| Status summary | stdout | display |

This command does not modify handoff documents; it is read-only.

## Error Handling

- If handoff documents are missing, report which files are absent
- If no active task exists, report "No active tasks in queue"
- If STATUS.md is stale (>24h), flag for refresh

## Related Documents

- `core/orchestrator/handoff/STATUS.md`: Runtime status template
- `core/orchestrator/handoff/TASKS.md`: Task queue
- `core/orchestrator/handoff/ESCALATION_PATHS.md`: Escalation triggers
- `COMMAND_REGISTRY.md`: Command registry
