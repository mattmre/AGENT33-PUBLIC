# performance.md (Rules)

Purpose: Define rules for efficient agent operation and context management.

Related docs:
- `core/packs/policy-pack-v1/ORCHESTRATION.md` (workflow protocol)
- `core/packs/policy-pack-v1/AGENTS.md` (agent principles)

---

## Context Management

### Keep Context Focused
- Load only files relevant to current task
- Summarize large files instead of loading entirely
- Unload context when task is complete
- Prefer references over full content

### Context Budget
- Monitor token usage against limits
- Prioritize recent and relevant information
- Archive completed task context
- Clear temporary context regularly

### Context Hierarchy

1. Current task scope (highest priority)
2. Related files and dependencies
3. Project conventions and patterns
4. General knowledge (lowest priority)

---

## Efficient Tool Usage

### Minimize Tool Calls
- Batch related operations when possible
- Use specific queries over broad searches
- Cache results for repeated lookups
- Avoid redundant reads of same files

### Tool Selection
| Need | Preferred Tool | Avoid |
|------|---------------|-------|
| File content | Direct read | Search + read |
| Multiple files | Batch read | Sequential reads |
| Pattern search | Targeted grep | Full repo scan |
| Structure check | Specific path | Recursive listing |

### Command Efficiency
```
Prefer:
- Specific file paths over wildcards
- Filtered output over full dumps
- Combined commands over sequences

Avoid:
- Reading entire codebase
- Unfiltered recursive searches
- Multiple writes to same file
```

---

## Avoid Redundant Operations

### Caching Strategy
- Cache file contents within task
- Cache search results if reusable
- Cache computed values
- Invalidate cache on writes

### Redundancy Patterns to Avoid
```
❌ Read file, modify, read again to verify
✓ Read file, modify, trust operation succeeded

❌ Search for pattern, read files, search same pattern
✓ Search for pattern, save results, read files

❌ Run tests after every small change
✓ Batch changes, run tests once
```

### Validation Efficiency
- Validate at boundaries, not repeatedly
- Trust intermediate state within transaction
- Verify final state, not every step

---

## Scope Creep Prevention

### Stay In Scope
- Reference PLAN.md for current scope
- Check acceptance criteria before changes
- Reject out-of-scope discoveries as future work
- Document scope boundaries clearly

### Scope Creep Signals
- "While I'm here, I could also..."
- Fixing unrelated issues
- Adding unrequested features
- Expanding test coverage beyond requirements

### Handling Scope Expansion
```markdown
## Out-of-Scope Discovery

### Found
<description of issue/opportunity>

### Why Out of Scope
<explanation>

### Recommendation
- [ ] Add to backlog: <issue-title>
- [ ] Priority: <low/medium/high>
- [ ] Related to: <current-task>
```

---

## Efficiency Checklist

### Before Starting
- [ ] Scope is clearly defined
- [ ] Acceptance criteria are understood
- [ ] Required files are identified
- [ ] Tool strategy is planned

### During Execution
- [ ] Context is focused on task
- [ ] Tools are used efficiently
- [ ] Redundant operations are avoided
- [ ] Scope boundaries are respected

### After Completion
- [ ] Context is cleaned up
- [ ] Results are captured
- [ ] Out-of-scope items are logged
- [ ] Ready for next task

---

## Performance Metrics

### Track These Metrics
- Token usage per task
- Tool calls per task
- Time to completion
- Rework rate

### Efficiency Targets

**Optimal:**
- Single read per file (unless modified)
- Minimal search iterations
- Focused context (< 50% capacity)
- Zero scope creep

---

## Evidence Capture

```markdown
## Performance Review

### Context Usage
- Files loaded: X
- Token budget used: Y%
- Context cleanup: Done/Pending

### Tool Efficiency
- Total tool calls: X
- Redundant calls: Y
- Batch opportunities missed: Z

### Scope Compliance
- Scope creep instances: X
- Out-of-scope items logged: Y
```
