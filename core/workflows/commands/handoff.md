# /handoff Command

## Purpose

Generate a session wrap summary for the next session, documenting current state, decisions made, and recommended next steps.

## Invocation

```
/handoff [notes]
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| notes | No | Additional context or notes to include |

## Workflow

### 1. Context Load

Read the following handoff documents:
- `core/orchestrator/handoff/STATUS.md`
- `core/orchestrator/handoff/TASKS.md`
- `core/orchestrator/handoff/DECISIONS.md`
- `core/orchestrator/handoff/PLAN.md`
- `core/orchestrator/handoff/PRIORITIES.md`

### 2. Session Analysis

Synthesize session activity:
- **Completed Tasks**: Tasks moved to `done` this session
- **Active Work**: Tasks still `in_progress`
- **Decisions Made**: Entries added to DECISIONS.md
- **Blockers Encountered**: Issues that slowed progress
- **Plan Changes**: Modifications to PLAN.md

### 3. Next Actions Derivation

Determine recommended next steps:
- Priority tasks from PRIORITIES.md
- Unblocked tasks ready for work
- Review items awaiting input
- Follow-up actions from decisions

### 4. Handoff Generation

Append entry to `SESSION_WRAP.md`:

```markdown
## Session Wrap: [YYYY-MM-DD HH:MM]

### Status Summary

**Session Duration**: [start] - [end]
**Tasks Completed**: [count]
**Tasks In Progress**: [count]
**Blockers**: [count]

### Completed This Session

- [x] [task-id]: [description]
- [x] [task-id]: [description]

### Still In Progress

- [ ] [task-id]: [description] - [status note]

### Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| [decision] | [why] | [what changes] |

### Blockers & Issues

- [blocker description and mitigation]

### Recommended Next Steps

1. **[Priority]**: [action description]
2. **[Priority]**: [action description]
3. **[Priority]**: [action description]

### Notes

[Additional context or operator notes]

---
```

## Outputs

| Output | Destination | Action |
|--------|-------------|--------|
| Handoff summary | stdout | display |
| Session wrap entry | `handoff/SESSION_WRAP.md` | append |

## Handoff Quality Checklist

Before generating handoff:
- [ ] All task statuses are current
- [ ] Decisions are documented with rationale
- [ ] Blockers have clear descriptions
- [ ] Next steps are actionable

## Error Handling

- If handoff documents are missing, report which files are absent
- If no session activity detected, generate minimal handoff noting "No activity this session"
- If SESSION_WRAP.md doesn't exist, create it with header

## Related Documents

- `core/orchestrator/handoff/SESSION_WRAP.md`: Session wrap template
- `core/orchestrator/handoff/STATUS.md`: Runtime status
- `core/orchestrator/handoff/DECISIONS.md`: Decision log
- `core/orchestrator/handoff/TASKS.md`: Task queue
- `COMMAND_REGISTRY.md`: Command registry
