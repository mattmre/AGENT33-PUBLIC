# /tdd Command

Purpose: Direct entry point for Test-Driven Development workflow.

Related docs:
- `core/workflows/skills/tdd-workflow.md` (TDD skill definition)
- `core/packs/policy-pack-v1/EVIDENCE.md` (evidence capture requirements)

---

## Command Signature

```
/tdd <feature-description>
```

## Workflow

### 1. Invoke TDD Skill
- Load `core/workflows/skills/tdd-workflow.md`
- Parse feature description into testable requirements

### 2. RED Phase
- Write failing test(s) for the feature
- Verify test fails for the right reason
- Capture: test file path, failure output

### 3. GREEN Phase
- Write minimal implementation to pass test
- Run test suite to verify pass
- Capture: implementation file path, pass output

### 4. REFACTOR Phase
- Identify code smells or duplication
- Refactor while keeping tests green
- Capture: refactored files, final test output

---

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| feature-description | Yes | Clear description of feature to implement |
| target-path | No | Directory or file to target |
| test-framework | No | Override default test framework |

---

## Outputs

| Output | Description |
|--------|-------------|
| Test files | New or updated test file(s) |
| Implementation | Minimal code to pass tests |
| Evidence | RED/GREEN/REFACTOR stage captures |
| TASKS.md update | Progress logged in handoff docs |

---

## Stage Tracking

Track current stage in STATUS.md:
```
## TDD Progress
- [x] RED: test written, fails correctly
- [x] GREEN: implementation passes
- [ ] REFACTOR: cleanup complete
```

---

## Evidence Capture

Minimum evidence per stage:
- **RED**: Test code + failure message
- **GREEN**: Implementation code + pass confirmation
- **REFACTOR**: Diff summary + all tests still pass

---

## Example Usage

```
/tdd "Add user authentication with JWT tokens"
```

Expected flow:
1. Write test for authentication endpoint
2. Verify test fails (no auth implemented)
3. Implement minimal JWT auth
4. Verify test passes
5. Refactor for clarity and security
6. Capture evidence at each stage
