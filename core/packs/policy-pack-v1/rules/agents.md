# agents.md (Rules)

Purpose: Define rules for agent delegation and multi-agent coordination.

Related docs:
- `core/orchestrator/AGENT_ROUTING_MAP.md` (agent routing decisions)
- `core/orchestrator/AGENT_REGISTRY.md` (agent capabilities)
- `core/packs/policy-pack-v1/AGENTS.md` (agent principles)

---

## When to Delegate

### Delegate When
- Task requires specialized capability not in current role
- Task is independent and can run in parallel
- Task has clear inputs and expected outputs
- Workload exceeds current agent capacity

### Do Not Delegate When
- Task is trivial (faster to do inline)
- Context transfer cost exceeds benefit
- Task requires current agent's accumulated context
- Tight coupling with current work

---

## Agent Selection Criteria

### Match by Task Type

| Task Type | Agent | Reason |
|-----------|-------|--------|
| Implementation | Implementer (AGT-003) | Code/config changes |
| Testing | QA (AGT-004) | Test execution |
| Security concern | Security (AGT-008) | Security assessment |
| Architecture decision | Architect (AGT-009) | Design validation |
| Documentation | Documentation (AGT-007) | Doc updates |
| Research | Researcher (AGT-006) | Context gathering |

### Selection Checklist
1. Identify task type
2. Check AGENT_ROUTING_MAP.md for primary role
3. Verify agent has required capabilities
4. Check agent availability
5. Prepare clear handoff

---

## Parallel Execution Guidelines

### Safe for Parallel Execution
- Independent file changes (different files)
- Read-only research tasks
- Test execution (if isolated)
- Documentation updates (non-overlapping)

### Requires Sequential Execution
- Dependent changes (same files)
- Changes requiring prior results
- Database migrations
- API contract changes

### Parallel Coordination

1. Define clear boundaries for each agent
2. Specify non-overlapping file scopes
3. Establish merge order if needed
4. Plan conflict resolution

---

## Escalation Patterns

### Standard Escalation Chain
```
Worker → Orchestrator → Director → Human
```

### Escalation Triggers
- Scope ambiguity
- Risk trigger activated
- Resource constraint
- Approval required
- Conflict resolution needed

### Escalation Format
```markdown
## Escalation Request

### From: <agent-id>
### To: <escalation-target>

### Issue
<description of blocker>

### Context
<relevant background>

### Options
1. <option-1>
2. <option-2>

### Recommendation
<preferred approach>

### Urgency
<high/medium/low>
```

---

## Handoff Protocol

### Minimum Handoff Content
- Task description
- Acceptance criteria
- Relevant file paths
- Constraints and boundaries
- Expected output format

### Context Transfer
- Include only essential context
- Link to full docs rather than copying
- Specify what agent should NOT do
- Define completion criteria

---

## Evidence Requirements

Document agent delegation:
```markdown
## Agent Delegation Evidence

### Task Delegated
- Description: <task>
- Delegated to: <agent-id>
- Rationale: <why this agent>

### Handoff Content
- Scope: <files/paths>
- Criteria: <acceptance>

### Result
- Status: <complete/escalated>
- Output: <summary>
```
