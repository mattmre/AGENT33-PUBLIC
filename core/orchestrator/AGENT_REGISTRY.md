# Agent Registry

Purpose: Canonical registry of agent roles with capabilities, constraints, and ownership metadata.

Related docs:
- `core/orchestrator/AGENT_ROUTING_MAP.md` (task-to-role routing)
- `core/packs/policy-pack-v1/AGENTS.md` (agent operating principles)
- `core/orchestrator/agents/` (role-specific rules)

---

## Registry Schema

Each agent entry follows this schema:

```yaml
agent_id: <unique-identifier>
role: <role-name>
description: <brief-description>
capabilities:
  - <capability-1>
  - <capability-2>
constraints:
  scope: <allowed-scope>
  commands: <command-policy>
  network: <network-policy>
  approval_required: <list-of-actions>
owner: <owner-identifier>
escalation_target: <role-to-escalate-to>
status: <active|deprecated|experimental>
```

---

## Capability Taxonomy

### Planning & Coordination (P)
| ID | Capability | Description |
|----|------------|-------------|
| P-01 | Task Decomposition | Break work into scoped tasks with acceptance criteria |
| P-02 | Sequencing | Order tasks by dependencies and priorities |
| P-03 | Conflict Resolution | Resolve cross-task or cross-agent conflicts |
| P-04 | Portfolio Management | Manage multi-repo priorities and scheduling |
| P-05 | Scope Definition | Define boundaries and non-goals |

### Implementation (I)
| ID | Capability | Description |
|----|------------|-------------|
| I-01 | Code Writing | Create or modify source code |
| I-02 | Config Editing | Modify configuration files |
| I-03 | Documentation Writing | Create or update documentation |
| I-04 | Template Instantiation | Create files from templates |
| I-05 | Refactoring | Restructure code without changing behavior |

### Verification (V)
| ID | Capability | Description |
|----|------------|-------------|
| V-01 | Test Execution | Run existing test suites |
| V-02 | Test Writing | Create new test cases |
| V-03 | Lint/Format Check | Run code quality tools |
| V-04 | Evidence Capture | Document commands, outputs, artifacts |
| V-05 | Acceptance Verification | Verify task meets criteria |

### Review (R)
| ID | Capability | Description |
|----|------------|-------------|
| R-01 | Code Review | Evaluate code changes for quality |
| R-02 | Security Review | Assess security implications |
| R-03 | Architecture Review | Validate design decisions |
| R-04 | Risk Assessment | Identify and document risks |
| R-05 | Compliance Check | Verify policy adherence |

### Research (X)
| ID | Capability | Description |
|----|------------|-------------|
| X-01 | Codebase Exploration | Navigate and understand code structure |
| X-02 | Documentation Reading | Gather context from docs |
| X-03 | Dependency Analysis | Map dependencies and impacts |
| X-04 | Comparison Analysis | Compare alternatives or variants |
| X-05 | Pattern Identification | Find patterns and anti-patterns |

---

## Registered Agents

### AGT-001: Orchestrator

```yaml
agent_id: AGT-001
role: Orchestrator
description: Scopes tasks, defines acceptance criteria, sequences work, resolves conflicts.
capabilities:
  - P-01 (Task Decomposition)
  - P-02 (Sequencing)
  - P-03 (Conflict Resolution)
  - P-05 (Scope Definition)
  - V-05 (Acceptance Verification)
constraints:
  scope: handoff docs, task files, status updates
  commands: read-only file ops, git status
  network: off
  approval_required: [scope changes, priority overrides]
owner: project-lead
escalation_target: Director
status: active
```

**Rules file**: `core/orchestrator/agents/CLAUDE_ORCHESTRATOR_RULES.md`

---

### AGT-002: Director

```yaml
agent_id: AGT-002
role: Director
description: Portfolio-level oversight for multi-repo orchestration, priorities, and escalations.
capabilities:
  - P-04 (Portfolio Management)
  - P-05 (Scope Definition)
  - P-03 (Conflict Resolution)
  - R-04 (Risk Assessment)
constraints:
  scope: priorities, scheduling, escalation decisions
  commands: read-only
  network: off
  approval_required: [budget changes, external escalations]
owner: org-lead
escalation_target: human-stakeholder
status: active
```

**Rules file**: `core/orchestrator/agents/DIRECTOR_RULES.md`

---

### AGT-003: Implementer (Worker-Impl)

```yaml
agent_id: AGT-003
role: Implementer
description: Writes or modifies code, config, and docs within scoped tasks.
capabilities:
  - I-01 (Code Writing)
  - I-02 (Config Editing)
  - I-03 (Documentation Writing)
  - I-04 (Template Instantiation)
  - I-05 (Refactoring)
constraints:
  scope: files specified in task acceptance criteria
  commands: build, test, lint (per autonomy budget)
  network: off by default
  approval_required: [new dependencies, schema changes, API changes]
owner: orchestrator
escalation_target: Orchestrator
status: active
```

**Rules file**: `core/orchestrator/prompts/WORKER_RULES.md`

---

### AGT-004: QA (Worker-QA)

```yaml
agent_id: AGT-004
role: QA
description: Runs tests, verifies outcomes, captures evidence, writes smoke checks.
capabilities:
  - V-01 (Test Execution)
  - V-02 (Test Writing)
  - V-03 (Lint/Format Check)
  - V-04 (Evidence Capture)
  - V-05 (Acceptance Verification)
constraints:
  scope: test files, evidence docs, verification logs
  commands: test runners, lint tools
  network: off
  approval_required: [test infrastructure changes]
owner: orchestrator
escalation_target: Orchestrator
status: active
```

**Rules file**: `core/orchestrator/prompts/WORKER_RULES.md` (QA variant)

---

### AGT-005: Reviewer

```yaml
agent_id: AGT-005
role: Reviewer
description: Reviews changes when risk triggers apply, provides second opinions on design.
capabilities:
  - R-01 (Code Review)
  - R-02 (Security Review)
  - R-03 (Architecture Review)
  - R-04 (Risk Assessment)
  - R-05 (Compliance Check)
constraints:
  scope: read-only access to all files
  commands: read-only, diff viewing
  network: off
  approval_required: [none - advisory role]
owner: project-lead
escalation_target: Director
status: active
```

**Rules file**: `core/orchestrator/agents/GEMINI_REVIEW_RULES.md`

---

### AGT-006: Researcher

```yaml
agent_id: AGT-006
role: Researcher
description: Gathers context, reads docs, compares variants, identifies patterns.
capabilities:
  - X-01 (Codebase Exploration)
  - X-02 (Documentation Reading)
  - X-03 (Dependency Analysis)
  - X-04 (Comparison Analysis)
  - X-05 (Pattern Identification)
constraints:
  scope: read-only access to all files
  commands: search, grep, file listing
  network: off (unless research requires external docs)
  approval_required: [external fetches]
owner: orchestrator
escalation_target: Orchestrator
status: active
```

---

### AGT-007: Documentation Agent

```yaml
agent_id: AGT-007
role: Documentation
description: Updates or creates docs, templates, and guides; ensures doc-code alignment.
capabilities:
  - I-03 (Documentation Writing)
  - I-04 (Template Instantiation)
  - X-02 (Documentation Reading)
  - V-04 (Evidence Capture)
constraints:
  scope: docs/, *.md files, templates
  commands: markdown lint, link check
  network: off
  approval_required: [public-facing doc changes]
owner: orchestrator
escalation_target: Orchestrator
status: active
```

---

### AGT-008: Security Agent

```yaml
agent_id: AGT-008
role: Security
description: Reviews security implications, assesses risks, validates defenses.
capabilities:
  - R-02 (Security Review)
  - R-04 (Risk Assessment)
  - R-05 (Compliance Check)
  - X-03 (Dependency Analysis)
constraints:
  scope: security-relevant files, risk triggers, dependencies
  commands: security scanners (if available)
  network: off
  approval_required: [none - advisory role]
owner: project-lead
escalation_target: Director
status: active
```

---

### AGT-009: Architect Agent

```yaml
agent_id: AGT-009
role: Architect
description: Validates design decisions, reviews architecture, ensures consistency.
capabilities:
  - R-03 (Architecture Review)
  - P-05 (Scope Definition)
  - X-03 (Dependency Analysis)
  - X-05 (Pattern Identification)
constraints:
  scope: architecture docs, design files, schemas
  commands: read-only
  network: off
  approval_required: [none - advisory role]
owner: project-lead
escalation_target: Director
status: active
```

---

### AGT-010: Test Engineer

```yaml
agent_id: AGT-010
role: Test Engineer
description: Writes tests, designs test strategies, maintains test infrastructure.
capabilities:
  - V-01 (Test Execution)
  - V-02 (Test Writing)
  - I-01 (Code Writing - test code)
  - X-05 (Pattern Identification)
constraints:
  scope: test files, fixtures, test config
  commands: test runners, coverage tools
  network: off
  approval_required: [test infrastructure changes]
owner: orchestrator
escalation_target: Orchestrator
status: active
```

---

## Agent Onboarding

### Adding a New Agent Role

1. **Define the role**:
   - Identify the gap in current capabilities
   - Document the role's purpose and responsibilities

2. **Create registry entry**:
   - Assign unique `agent_id` (AGT-NNN)
   - Map capabilities from taxonomy
   - Define constraints and approval requirements
   - Assign owner and escalation target

3. **Create rules file**:
   - Add `core/orchestrator/agents/<ROLE>_RULES.md`
   - Document responsibilities and deliverables
   - Reference capability IDs

4. **Update routing map**:
   - Add role to `AGENT_ROUTING_MAP.md`
   - Define "use when" criteria

5. **Verify onboarding**:
   - Cross-reference registry entry with routing map
   - Confirm rules file exists and is complete
   - Add entry to this registry

### Deprecating an Agent Role

1. Set `status: deprecated` in registry entry
2. Add deprecation note with replacement guidance
3. Update routing map to redirect tasks
4. Retain rules file for historical reference (archived)

---

## Registry Maintenance

### Update Checklist
- [ ] New capabilities added to taxonomy
- [ ] Registry entry follows schema
- [ ] Rules file created or updated
- [ ] Routing map references registry
- [ ] Onboarding/deprecation steps followed

### Version History
| Date | Change | Author |
|------|--------|--------|
| 2026-01-16 | Initial registry with 10 agents | Architect Agent |

---

## References

- Routing map: `core/orchestrator/AGENT_ROUTING_MAP.md`
- Agent principles: `core/packs/policy-pack-v1/AGENTS.md`
- Autonomy budget: `core/orchestrator/handoff/AUTONOMY_BUDGET.md`
- Escalation paths: `core/orchestrator/handoff/ESCALATION_PATHS.md`
