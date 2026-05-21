# Skills Framework

Purpose: Define reusable workflow patterns and domain knowledge that agents can apply across tasks.

Related docs:
- `core/workflows/commands/COMMAND_REGISTRY.md` (commands that invoke skills)
- `core/ORCHESTRATION_INDEX.md` (main orchestration index)

## What Are Skills?

Skills are structured workflow definitions and domain knowledge modules that:

- **Workflow Definitions**: Step-by-step processes for common development patterns (TDD, code review, refactoring)
- **Domain Knowledge**: Best practices, patterns, and heuristics for specific domains (security, testing, performance)
- **Integration Points**: Hooks into AGENT-33's orchestration, evidence capture, and verification systems

## How Skills Integrate with Orchestration

Skills operate within the AGENT-33 orchestration framework:

1. **Task Assignment**: Orchestrator assigns tasks that may reference one or more skills
2. **Skill Activation**: Agent loads relevant skill definitions for the task type
3. **Evidence Capture**: Each skill stage logs evidence per `EVIDENCE.md` requirements
4. **Verification**: Skill outputs feed into `verification-log.md` for audit trail
5. **Handoff**: Skill completion triggers handoff artifacts per `SESSION_WRAP.md`

### Skill-Orchestrator Contract

| Skill Phase | Orchestrator Action | Evidence Required |
|-------------|---------------------|-------------------|
| Start | Log skill activation in session | Skill name, task ID |
| Execute | Monitor progress, enforce autonomy budget | Commands, outputs |
| Complete | Verify acceptance criteria met | Pass/fail, artifacts |
| Handoff | Update task status, capture learnings | Session log entry |

---

## Available Skills

| Skill | File | Purpose | Invoked By |
|-------|------|---------|------------|
| TDD Workflow | `tdd-workflow.md` | Test-driven development with RED/GREEN/REFACTOR stages | /tdd command |
| Security Review | `security-review.md` | Comprehensive security checklist | Manual, pre-merge hooks |
| Coding Standards | `coding-standards.md` | Coding standards and best practices | /refactor command |
| Backend Patterns | `backend-patterns.md` | Backend development patterns | Manual |

---

## Skill Index

### Security & Quality

- **[security-review](./security-review.md)** - Security review checklist
  - Input validation patterns
  - Authentication/authorization checks
  - Common vulnerability patterns (injection, XSS, CSRF)
  - Secrets management

- **[coding-standards](./coding-standards.md)** - Coding standards skill
  - File organization principles
  - Naming conventions
  - Error handling patterns
  - Code review checklist

### Development Patterns

- **[backend-patterns](./backend-patterns.md)** - Backend patterns skill
  - API design patterns (REST, error responses)
  - Database access patterns (repository pattern)
  - Caching strategies
  - Authentication patterns

### Workflows

- **[tdd-workflow](./tdd-workflow.md)** - TDD workflow skill
  - RED/GREEN/REFACTOR cycle
  - Evidence capture per stage

---

## Skill Conventions

### Signature Format
```
invoke: <skill-name>
inputs: <comma-separated inputs>
outputs: <comma-separated outputs>
```

### Integration with Evidence
All skills should integrate with evidence capture:
1. Document scope of skill application
2. Capture results/findings
3. Note compliance status

---

## Creating New Skills

New skills should follow this structure:

```markdown
# <skill-name> Skill

Purpose: <one-line description>

Related docs:
- <related-file-1>
- <related-file-2>

---

## Purpose
Brief description of what the skill accomplishes.

## Skill Signature
How to invoke this skill.

## Stages
Ordered list of stages with clear entry/exit criteria.

## Checklist/Patterns
Domain-specific checks or patterns.

## Evidence Requirements
What evidence must be captured at each stage.

## Integration Points
References to AGENT-33 orchestration documents.

## Examples
Concrete examples of skill application.
```

---

## Adding New Skills

1. Create `<skill-name>.md` in this directory
2. Follow the skill template structure above
3. Add entry to this README
4. Update ORCHESTRATION_INDEX.md if applicable

## Cross-References

- Evidence requirements: `core/packs/policy-pack-v1/EVIDENCE.md`
- Verification logging: `core/arch/verification-log.md`
- Test selection: `core/arch/test-matrix.md`
- Session handoff: `core/orchestrator/handoff/SESSION_WRAP.md`
- Autonomy constraints: `core/orchestrator/handoff/AUTONOMY_BUDGET.md`
