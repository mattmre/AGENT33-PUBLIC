# Worker Rules (Model-Agnostic)

## Default Output Format
1) Plan (3-6 bullets max)
2) Commands to run
3) Unified diff (or explicit file edits)
4) Verification results (tests/build) + short status

## Boundaries
- Do NOT rewrite unrelated files.
- Do NOT reformat the whole codebase.
- Keep diffs tight and scoped to the task.

## When blocked
Write:
- BLOCKED: <why>
- NEED: <what is required>
- NEXT: <specific next action>

## Git
- Always use a branch per task: ask/T#-short-name
- Commit messages: T#: <summary>
- Update orchestrator/handoff/TASKS.md after each milestone.

---

## Code Tool Usage (Qwen Code Integration)

Reference: `core/orchestrator/QWEN_CODE_TOOL_PROTOCOL.md`

### Invocation Rules

1. **Warmup first** - Ensure model is warmed up before generation tasks
2. **Scope requests** - One code generation task per invocation
3. **Provide context** - Include relevant files, language, and constraints
4. **Set limits** - Always specify max_tokens and timeout

### Output Validation Requirements

Before integrating any generated code:

| Check | Requirement | Action on Failure |
|-------|-------------|-------------------|
| **Syntax** | Must parse without errors | Reject and regenerate |
| **Lint** | Must pass project linter | Fix or regenerate |
| **Security** | No known vulnerabilities | Block and review |
| **Scope** | Changes only what's requested | Trim excess |
| **Tests** | Existing tests pass | Debug or revert |

### Validation Workflow

```
1. Receive generated code
2. Run syntax check (language-specific parser)
3. Run linter (eslint, pylint, etc.)
4. Run security scan (if configured)
5. Review diff for scope compliance
6. Run existing tests
7. If all pass → integrate
8. If any fail → log, retry, or escalate
```

### Error Handling Patterns

| Error Type | Pattern | Recovery |
|------------|---------|----------|
| **Model timeout** | QC-003 | Retry with extended timeout |
| **Generation failure** | QC-001, QC-004 | Simplify prompt, retry |
| **Validation failure** | QC-006 | Review error, refine prompt |
| **Security issue** | QC-007 | Escalate immediately |
| **Rate limit** | QC-005 | Backoff (1s, 2s, 4s...) |

### Required Evidence

Every code tool invocation must capture:
- Invocation ID and timestamp
- Input prompt (sanitized)
- Generated output
- Validation results
- Integration outcome

Store in: `core/logs/qwen-invocations/`
