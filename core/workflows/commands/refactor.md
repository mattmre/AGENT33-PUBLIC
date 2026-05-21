# /refactor Command

Purpose: Clean up dead code or refactor for maintainability without changing behavior.

Related docs:
- `core/packs/policy-pack-v1/EVIDENCE.md` (evidence capture)
- `core/workflows/skills/coding-standards.md` (coding standards)

---

## Command Signature

```
/refactor [target] [type]
```

Types: `cleanup`, `extract`, `rename`, `simplify`, `dead-code`

## Workflow

### 1. Identify Candidates
- Analyze code for refactoring opportunities
- Check for dead code, duplication, complexity
- Prioritize by impact and risk

### 2. Verify Baseline
- Run existing tests
- Capture current behavior
- Document starting state

### 3. Apply Refactoring
- Make incremental changes
- Keep each change small and reversible
- Maintain test coverage

### 4. Verify No Behavior Change
- Re-run all tests
- Confirm identical behavior
- Capture evidence

---

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| target | No | File or directory to refactor |
| type | No | Type of refactoring to apply |
| scope | No | Limit changes (e.g., max files) |

---

## Outputs

| Output | Description |
|--------|-------------|
| Refactored code | Improved code structure |
| Test results | Verification of unchanged behavior |
| Evidence | Before/after comparison |
| TASKS.md update | Refactoring logged |

---

## Refactoring Types

| Type | Description | When to Use |
|------|-------------|-------------|
| cleanup | Remove unused code, fix formatting | Code review feedback |
| extract | Extract methods/functions | Long functions, duplication |
| rename | Improve naming clarity | Unclear or misleading names |
| simplify | Reduce complexity | High cyclomatic complexity |
| dead-code | Remove unreachable code | After feature removal |

---

## Dead Code Detection

Look for:
- Unreachable code paths
- Unused variables and functions
- Commented-out code blocks
- Deprecated feature code
- Orphaned test files

---

## Safety Checklist

Before refactoring:
- [ ] Tests exist and pass
- [ ] Behavior is documented
- [ ] Change scope is limited
- [ ] Rollback plan exists

After refactoring:
- [ ] All tests still pass
- [ ] No new warnings
- [ ] Code review if risk triggers apply
- [ ] Documentation updated if needed

---

## Evidence Capture

```markdown
## Refactoring Evidence

### Target
- Files: `<file-list>`
- Type: <refactoring-type>
- Scope: <description>

### Baseline
- Tests: X passing
- Coverage: Y%

### Changes Applied
- <change-description>
- <change-description>

### Verification
- Tests: X passing (unchanged)
- Coverage: Y% (unchanged or improved)
- Behavior: No changes detected
```

---

## Common Patterns

### Extract Method
```
Before: Long function with embedded logic
After: Helper method extracted, main function simplified
```

### Remove Dead Code
```
Before: Function never called
After: Function and related code removed
```

### Simplify Conditional
```
Before: Nested if-else chains
After: Guard clauses or switch statement
```

---

## Example Usage

```
/refactor src/utils dead-code
```

Flow:
1. Analyze src/utils for dead code
2. Run tests to establish baseline
3. Identify unused functions
4. Remove dead code
5. Re-run tests, verify pass
6. Capture evidence
