# Agent Routing Map (Model-Agnostic)

Use this map to decide which roles to invoke by task type.

Related docs:
- `core/orchestrator/AGENT_REGISTRY.md` (canonical registry with capabilities and constraints)
- `core/packs/policy-pack-v1/AGENTS.md` (agent operating principles)

---

## Quick Reference

| Task Type | Primary Role | Registry ID | Escalation |
|-----------|--------------|-------------|------------|
| Scope/priority decisions | Director | AGT-002 | Human stakeholder |
| Task sequencing/acceptance | Orchestrator | AGT-001 | Director |
| Code/config implementation | Implementer | AGT-003 | Orchestrator |
| Test execution/verification | QA | AGT-004 | Orchestrator |
| Risk-triggered review | Reviewer | AGT-005 | Director |
| Context gathering/research | Researcher | AGT-006 | Orchestrator |
| Documentation/templates | Documentation | AGT-007 | Orchestrator |
| Security assessment | Security | AGT-008 | Director |
| Architecture validation | Architect | AGT-009 | Director |
| Test writing/strategy | Test Engineer | AGT-010 | Orchestrator |

---

## Role Selection Checklist

Ask these questions in order:

1. **Is the task about scope/priority?** → Use **Director** (AGT-002)
2. **Is the task about sequencing or acceptance criteria?** → Use **Orchestrator** (AGT-001)
3. **Does a risk trigger apply?** → Use **Reviewer** (AGT-005)
4. **Is it a security concern?** → Use **Security** (AGT-008)
5. **Is it an architecture decision?** → Use **Architect** (AGT-009)
6. **Is the task about implementation?** → Use **Implementer** (AGT-003)
7. **Is the task about verification?** → Use **QA** (AGT-004)
8. **Is the task about test creation?** → Use **Test Engineer** (AGT-010)
9. **Is it a research/reading task?** → Use **Researcher** (AGT-006)
10. **Is it documentation or templates?** → Use **Documentation** (AGT-007)

---

## Role Details

### Orchestrator (AGT-001)

**Use when**:
- Scoping tasks, defining acceptance criteria, and sequencing work
- Resolving conflicts or cross-task dependencies
- Maintaining PLAN, TASKS, STATUS, DECISIONS

**Capabilities**: P-01, P-02, P-03, P-05, V-05

**Escalates to**: Director

---

### Director (AGT-002)

**Use when**:
- Managing multi-repo priorities and scheduling
- Escalating risks or scope changes
- Making portfolio-level decisions

**Capabilities**: P-04, P-05, P-03, R-04

**Escalates to**: Human stakeholder

---

### Implementer (AGT-003)

**Use when**:
- Writing or modifying code or config files
- Executing a scoped task with acceptance criteria
- Creating files from templates

**Capabilities**: I-01, I-02, I-03, I-04, I-05

**Escalates to**: Orchestrator

---

### QA (AGT-004)

**Use when**:
- Running tests and verifying outcomes
- Writing minimal smoke checks if no tests exist
- Capturing evidence of test execution

**Capabilities**: V-01, V-02, V-03, V-04, V-05

**Escalates to**: Orchestrator

---

### Reviewer (AGT-005)

**Use when**:
- Risk triggers apply (security, schema, API, CI/CD)
- A second opinion is needed for design or edge cases
- Compliance verification required

**Capabilities**: R-01, R-02, R-03, R-04, R-05

**Escalates to**: Director

---

### Researcher (AGT-006)

**Use when**:
- Gathering context, reading docs, and summarizing constraints
- Comparing source variants before promotion or merge
- Analyzing dependencies and impacts

**Capabilities**: X-01, X-02, X-03, X-04, X-05

**Escalates to**: Orchestrator

---

### Documentation (AGT-007)

**Use when**:
- Updating or creating docs, templates, or guides
- Ensuring doc and code alignment after changes
- Creating onboarding or reference materials

**Capabilities**: I-03, I-04, X-02, V-04

**Escalates to**: Orchestrator

---

### Security (AGT-008)

**Use when**:
- Assessing security implications of changes
- Reviewing risk triggers related to auth, crypto, secrets
- Validating prompt injection defenses

**Capabilities**: R-02, R-04, R-05, X-03

**Escalates to**: Director

---

### Architect (AGT-009)

**Use when**:
- Validating design decisions and patterns
- Reviewing architecture changes
- Ensuring consistency across components

**Capabilities**: R-03, P-05, X-03, X-05

**Escalates to**: Director

---

### Test Engineer (AGT-010)

**Use when**:
- Designing test strategies
- Writing comprehensive test suites
- Maintaining test infrastructure

**Capabilities**: V-01, V-02, I-01, X-05

**Escalates to**: Orchestrator

---

## Multi-Role Workflows

### Standard Implementation Flow
1. **Orchestrator** → Scope and sequence tasks
2. **Researcher** → Gather context (if needed)
3. **Architect** → Validate design (if architecture change)
4. **Implementer** → Execute implementation
5. **QA** → Verify outcomes
6. **Reviewer** → Review if risk triggers apply
7. **Documentation** → Update docs

### Risk-Triggered Flow
1. **Orchestrator** → Identify risk triggers
2. **Security/Architect** → Pre-implementation review
3. **Implementer** → Execute with constraints
4. **Reviewer** → Post-implementation review
5. **QA** → Verify with security tests

---

## Capability Reference

See `core/orchestrator/AGENT_REGISTRY.md` for full capability taxonomy:
- **P-xx**: Planning & Coordination
- **I-xx**: Implementation
- **V-xx**: Verification
- **R-xx**: Review
- **X-xx**: Research
