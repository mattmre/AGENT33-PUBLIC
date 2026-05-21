# Modular Rules Index

Purpose: Provide a modular, customizable rule set for agent behavior governance.

Related docs:
- `core/packs/policy-pack-v1/AGENTS.md` (agent principles)
- `core/packs/policy-pack-v1/ORCHESTRATION.md` (workflow protocol)
- `core/ORCHESTRATION_INDEX.md` (main orchestration index)

## Overview

Rules in this directory define specific behavioral constraints and requirements for agents operating under Policy Pack v1. Each rule file focuses on a single domain, enabling:

- **Selective adoption**: Projects can adopt rules incrementally
- **Easy customization**: Override or extend rules per project needs
- **Clear ownership**: Each domain has defined scope and maintainer
- **Audit trail**: Changes to rules are tracked and versioned

## Rule Files

| File | Domain | Description |
|------|--------|-------------|
| `security.md` | Security | Secrets handling, input validation, injection prevention |
| `testing.md` | Testing | TDD workflow, coverage requirements, verification evidence |
| `git-workflow.md` | Git | Commits, branches, PRs, reviews |
| `coding-style.md` | Code Style | File organization, immutability, documentation |
| `agents.md` | Agent Ops | Agent delegation and coordination |
| `patterns.md` | Patterns | Common code and API patterns |
| `performance.md` | Efficiency | Context management, scope creep prevention |

---

## Rule Index

### Core Rules

- **[security](./security.md)** - Security rules
  - Secrets handling, input validation, injection prevention

- **[testing](./testing.md)** - Testing rules
  - TDD workflow, coverage requirements, verification evidence

- **[git-workflow](./git-workflow.md)** - Git workflow rules
  - Commits, branches, PRs, reviews

- **[coding-style](./coding-style.md)** - Coding style rules
  - File organization, immutability, documentation

### Agent Operations

- **[agents](./agents.md)** - Agent delegation rules
  - When to delegate to subagents
  - Agent selection criteria
  - Parallel execution guidelines
  - Escalation patterns

### Code Standards

- **[patterns](./patterns.md)** - Common patterns rules
  - API response format standards
  - Error handling conventions
  - Logging patterns
  - Configuration management

### Efficiency

- **[performance](./performance.md)** - Performance rules
  - Context management (keep focused)
  - Efficient tool usage
  - Avoid redundant operations
  - Scope creep prevention

---

## How Rules Apply

### Default Behavior

All rules in this directory apply by default when Policy Pack v1 is active. Agents should:

1. Load all rule files at session start
2. Apply rules throughout task execution
3. Document any rule deviations with rationale

### Per-Project Customization

Projects can customize rules by:

1. **Override file**: Create `.agent-33/rules-override.md` in project root
2. **Selective disable**: List rules to skip with justification
3. **Extensions**: Add project-specific rules that augment defaults

Example override file:
```markdown
# Rules Override

## Disabled Rules
- `coding-style.md#3-file-size-limits` - Legacy codebase with large files

## Extended Rules
- Require TypeScript strict mode for all new files
```

### Rule Precedence

1. Project-specific overrides (highest)
2. Policy Pack rules (this directory)
3. Task-specific constraints (in TASKS.md)
4. AGENT-33 core principles (lowest, always apply)

### Enforcement
- Rules are guidance, not hard blocks
- Document deviations with rationale
- Escalate if rule conflicts with task

## Rule Structure

Each rule file follows this structure:

```markdown
# [Domain] Rules

Purpose: <one-line description>

Related docs:
- <related-file-1>
- <related-file-2>

---

## Purpose
Why these rules exist.

## Rules
Numbered list of specific rules.

## Enforcement
How agents should enforce these rules.

## Exceptions
Valid reasons to deviate (with documentation requirements).

## Evidence Capture
What to log when applying these rules.

## Cross-References
Links to related AGENT-33 documents.
```

## Adding New Rules

1. Create new `.md` file in this directory
2. Follow the rule structure template above
3. Update this index with the new rule file
4. Document in `AGENTS.md` reference section
5. Update ORCHESTRATION_INDEX.md if applicable

## Cross-References

- Parent policy: `core/packs/policy-pack-v1/AGENTS.md`
- Evidence requirements: `core/packs/policy-pack-v1/EVIDENCE.md`
- Risk triggers: `core/packs/policy-pack-v1/RISK_TRIGGERS.md`
- Acceptance checks: `core/packs/policy-pack-v1/ACCEPTANCE_CHECKS.md`
