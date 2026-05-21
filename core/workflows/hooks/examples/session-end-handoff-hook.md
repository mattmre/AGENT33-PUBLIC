# session-end-handoff-hook

Purpose: Automatically generate handoff documentation when a session ends.

Related docs:
- `core/orchestrator/handoff/SESSION_WRAP.md` (session wrap template)
- `core/orchestrator/handoff/STATUS.md` (status tracking)
- `core/packs/policy-pack-v1/ORCHESTRATION.md` (handoff protocol)

---

## Hook Configuration

```yaml
hook:
  name: session-end-handoff
  trigger: session-end
  scope: workspace
  blocking: false
  auto-commit: false
```

---

## Actions Performed

### 1. Read Current State
- Parse STATUS.md for current progress
- Parse TASKS.md for completed/pending items
- Parse DECISIONS.md for recent decisions
- Collect evidence from verification logs

### 2. Generate SESSION_WRAP
- Summarize work completed
- List pending items
- Note blockers or escalations
- Provide next session recommendations

### 3. Update Handoff Docs
- Append session summary to SESSION_WRAP.md
- Update STATUS.md with final state
- Mark completed tasks in TASKS.md

---

## Pseudo-code Implementation

```pseudo
function sessionEndHandoffHook():
    # Gather current state
    status = parseMarkdown("handoff/STATUS.md")
    tasks = parseMarkdown("handoff/TASKS.md")
    decisions = parseMarkdown("handoff/DECISIONS.md")
    evidence = collectEvidence("handoff/evidence/")
    
    # Build session summary
    sessionSummary = {
        sessionId: generateSessionId(),
        timestamp: now(),
        duration: calculateSessionDuration(),
        
        completed: [],
        inProgress: [],
        blocked: [],
        
        decisions: [],
        evidence: [],
        
        nextSteps: []
    }
    
    # Categorize tasks
    for task in tasks.items:
        if task.status == "complete":
            sessionSummary.completed.append({
                id: task.id,
                description: task.description,
                evidence: task.evidenceRef
            })
        else if task.status == "in-progress":
            sessionSummary.inProgress.append({
                id: task.id,
                description: task.description,
                progress: task.progressPercent,
                blockers: task.blockers
            })
        else if task.status == "blocked":
            sessionSummary.blocked.append({
                id: task.id,
                description: task.description,
                blocker: task.blockerReason,
                escalation: task.escalationPath
            })
    
    # Collect recent decisions
    for decision in decisions.items:
        if decision.timestamp > sessionStart():
            sessionSummary.decisions.append({
                id: decision.id,
                summary: decision.summary,
                rationale: decision.rationale
            })
    
    # Generate next steps
    sessionSummary.nextSteps = inferNextSteps(
        sessionSummary.inProgress,
        sessionSummary.blocked
    )
    
    # Write SESSION_WRAP entry
    wrapEntry = formatSessionWrap(sessionSummary)
    appendToFile("handoff/SESSION_WRAP.md", wrapEntry)
    
    # Update STATUS.md
    statusUpdate = formatStatusUpdate(sessionSummary)
    updateFile("handoff/STATUS.md", statusUpdate)
    
    return {
        success: true,
        sessionId: sessionSummary.sessionId,
        summary: summarizeForLog(sessionSummary)
    }

function formatSessionWrap(summary):
    return """
## Session: ${summary.sessionId}

**Date**: ${summary.timestamp}
**Duration**: ${summary.duration}

### Completed
${formatList(summary.completed)}

### In Progress
${formatList(summary.inProgress)}

### Blocked
${formatList(summary.blocked)}

### Decisions Made
${formatList(summary.decisions)}

### Next Steps
${formatList(summary.nextSteps)}

---
"""

function inferNextSteps(inProgress, blocked):
    steps = []
    
    for task in inProgress:
        steps.append("Continue: " + task.description)
    
    for task in blocked:
        steps.append("Unblock: " + task.blocker)
    
    return steps
```

---

## Output Format

### SESSION_WRAP.md Entry

```markdown
## Session: SES-2024-0115-001

**Date**: 2024-01-15T18:30:00Z
**Duration**: 2h 15m

### Completed
- [x] TASK-001: Implement user authentication endpoint
- [x] TASK-002: Add unit tests for auth service

### In Progress
- [ ] TASK-003: Integrate with OAuth provider (60% complete)

### Blocked
- [ ] TASK-004: Deploy to staging - waiting for infra team

### Decisions Made
- DEC-005: Use JWT for session tokens (see DECISIONS.md)

### Next Steps
1. Continue: OAuth provider integration
2. Unblock: Follow up with infra team on staging access

---
```

---

## Integration Notes

- Hook triggers on explicit session end or timeout
- Gracefully handles partial state
- Does not auto-commit (operator can review first)
- Preserves previous session entries
