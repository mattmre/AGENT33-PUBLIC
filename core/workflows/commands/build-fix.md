# /build-fix Command

Purpose: Fix build or test failures with minimal, targeted changes.

Related docs:
- `core/packs/policy-pack-v1/EVIDENCE.md` (evidence capture)
- `core/orchestrator/handoff/TASKS.md` (task tracking)

---

## Command Signature

```
/build-fix [error-source]
```

## Workflow

### 1. Capture Error State
- Run build or test command
- Capture full error output
- Identify error type and location

### 2. Analyze Root Cause
- Parse error messages
- Trace to source file and line
- Identify pattern from common errors

### 3. Apply Minimal Fix
- Make smallest change to resolve error
- Avoid scope creep beyond the error
- Document rationale

### 4. Verify Fix
- Re-run build or test
- Confirm error resolved
- Check for regressions

---

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| error-source | No | Specific error output or log file |
| build-command | No | Override default build command |
| test-command | No | Override default test command |

---

## Outputs

| Output | Description |
|--------|-------------|
| Fixed code | Minimal change to resolve error |
| Verification | Build/test pass confirmation |
| TASKS.md update | Fix documented with evidence |

---

## Error Analysis Steps

1. **Identify error type**:
   - Compilation error
   - Test failure
   - Runtime exception
   - Dependency issue
   - Configuration error

2. **Locate source**:
   - File path from stack trace
   - Line number from error message
   - Related files from imports/references

3. **Determine fix pattern**:
   - Missing import/dependency
   - Type mismatch
   - Null/undefined reference
   - Logic error
   - Configuration mismatch

---

## Common Error Patterns

| Pattern | Symptoms | Fix Approach |
|---------|----------|--------------|
| Missing dependency | Module not found | Add to package/project file |
| Type mismatch | Type 'X' not assignable | Correct type or add conversion |
| Null reference | Cannot read property of null | Add null check or initialization |
| Import error | Cannot find module | Fix import path or add export |
| Test assertion | Expected X, got Y | Fix logic or update expectation |
| Config error | Invalid configuration | Correct config value/format |

---

## Evidence Capture

```markdown
## Build Fix Evidence

### Error Captured
- Command: `<build-command>`
- Error: `<error-message>`
- Location: `<file:line>`

### Fix Applied
- File: `<fixed-file>`
- Change: `<description>`
- Rationale: `<why-this-fix>`

### Verification
- Command: `<verify-command>`
- Result: PASS/FAIL
- Regression check: No new failures
```

---

## Example Usage

```
/build-fix
```

Flow:
1. Run project build command
2. Capture "Cannot find module './utils'" error
3. Identify missing export in utils.ts
4. Add missing export statement
5. Re-run build, confirm success
6. Update TASKS.md with evidence
