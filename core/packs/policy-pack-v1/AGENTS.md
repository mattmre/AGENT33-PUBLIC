# AGENTS.md (Policy Pack v1)

Purpose: Provide a model-agnostic baseline for how agents should operate in any repo.

## Core Principles
- Evidence-first: capture commands, outputs, artifacts, and review outcomes.
- Minimal diffs: keep changes scoped to the task acceptance criteria.
- Spec-first: require goals, non-goals, assumptions, and acceptance checks.
- Safe-by-default: no network or destructive actions without approval.

## Required Artifacts
- PLAN, TASKS, STATUS, DECISIONS, PRIORITIES
- Evidence capture (commands + outcomes)
- Review capture when risk triggers apply

## Autonomy Budget
- Scope: allowed files/paths and max diff size.
- Commands: explicit allowlist.
- Network: off by default; allowlist if approved.
- Stop conditions: ambiguity, failing tests, scope expansion.

## Knowledge Management

Agents should follow the memory protocol for autonomous knowledge operations:

- **Protocol**: `core/agents/AGENT_MEMORY_PROTOCOL.md`
- **Relationships**: `core/orchestrator/RELATIONSHIP_TYPES.md`
- **Artifact Index**: `core/ARTIFACT_INDEX.md`

Key behaviors:
- Search artifacts before starting tasks
- Store reusable insights in CHANGELOG or agent memory
- Create relationship links between discovered artifacts
- Mark deprecated artifacts with `supersedes` links

## Modular Rules

Detailed rules are organized in the `rules/` subdirectory for easier customization:

| Rule File | Domain |
|-----------|--------|
| `rules/security.md` | Secrets, input validation, injection prevention |
| `rules/testing.md` | TDD workflow, coverage, verification evidence |
| `rules/git-workflow.md` | Commits, branches, PRs, reviews |
| `rules/coding-style.md` | File organization, immutability, documentation |

See `rules/README.md` for customization guidance and per-project overrides.

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| depends-on | `core/agents/AGENT_MEMORY_PROTOCOL.md` | Knowledge management protocol |
| depends-on | `core/orchestrator/RELATIONSHIP_TYPES.md` | Relationship taxonomy |
| exemplifies | `core/orchestrator/README.md` | Orchestration system entry point |
| explains | . | Governance for agent autonomy patterns |
