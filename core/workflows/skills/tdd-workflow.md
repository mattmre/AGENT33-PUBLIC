# TDD Workflow Skill

Purpose: Define a structured test-driven development workflow with evidence capture at each stage.

## Overview

Test-Driven Development (TDD) follows a disciplined cycle: write a failing test, implement minimal code to pass, then refactor. This skill integrates TDD with AGENT-33's verification and evidence requirements.

## Stages

### Stage 1: RED (Write Failing Tests)

**Objective**: Create tests that define the expected behavior before implementation.

**Entry Criteria**:
- Clear acceptance criteria from task specification
- Test harness operational (verified per `core/arch/test-matrix.md`)
- Understanding of API/interface being tested

**Actions**:
1. Analyze acceptance criteria to derive test cases
2. Write test(s) that exercise the expected behavior
3. Run tests to confirm they fail for the right reason
4. Document the failure reason (not just "test failed")

**Exit Criteria**:
- Test(s) written and committed (or staged)
- Tests fail with expected failure mode
- Failure reason documented

**Evidence Capture**:
```markdown
## RED Stage Evidence
- Task ID: [task-id]
- Test file(s): [paths]
- Command: [exact test command]
- Result: FAIL (expected)
- Failure reason: [why it fails - missing implementation, etc.]
- Timestamp: [ISO 8601]
```

### Stage 2: GREEN (Minimal Implementation)

**Objective**: Write the minimum code necessary to make tests pass.

**Entry Criteria**:
- RED stage complete with failing tests
- Clear understanding of what behavior to implement

**Actions**:
1. Implement only what is needed to pass the failing test(s)
2. Avoid over-engineering or adding unrequested features
3. Run tests to confirm they pass
4. If tests still fail, iterate minimally

**Exit Criteria**:
- All new tests pass
- Existing tests still pass (no regressions)
- Implementation is minimal (no gold-plating)

**Evidence Capture**:
```markdown
## GREEN Stage Evidence
- Task ID: [task-id]
- Implementation file(s): [paths]
- Command: [exact test command]
- Result: PASS
- Tests passed: [count]
- Regressions: [none / list any]
- Timestamp: [ISO 8601]
```

### Stage 3: REFACTOR (Improve Code Quality)

**Objective**: Improve code quality while maintaining passing tests.

**Entry Criteria**:
- GREEN stage complete with all tests passing
- Code has identifiable improvement opportunities

**Actions**:
1. Identify refactoring opportunities (duplication, naming, structure)
2. Apply refactoring in small, reversible steps
3. Run tests after each refactoring step
4. Stop refactoring when code is clean and tests pass

**Exit Criteria**:
- All tests still pass
- Code quality improved (documented what changed)
- No new functionality added

**Evidence Capture**:
```markdown
## REFACTOR Stage Evidence
- Task ID: [task-id]
- Refactoring type: [extract method, rename, restructure, etc.]
- Files changed: [paths]
- Command: [exact test command]
- Result: PASS (maintained)
- Improvements: [brief description]
- Timestamp: [ISO 8601]
```

## Test Patterns

### Unit Tests

**Purpose**: Test individual functions/methods in isolation.

**Characteristics**:
- Fast execution (milliseconds)
- No external dependencies (mocked/stubbed)
- High coverage of edge cases
- Run on every code change

**When to Use**:
- Business logic validation
- Pure functions
- Algorithm correctness
- Input validation

### Integration Tests

**Purpose**: Test interaction between components.

**Characteristics**:
- Moderate execution time (seconds)
- May use real dependencies (database, file system)
- Focus on component boundaries
- Run before commits/merges

**When to Use**:
- API endpoint behavior
- Database operations
- File I/O operations
- Service interactions

### End-to-End (E2E) Tests

**Purpose**: Test complete user workflows.

**Characteristics**:
- Slower execution (seconds to minutes)
- Uses production-like environment
- Tests user-facing behavior
- Run before releases

**When to Use**:
- Critical user journeys
- Cross-system workflows
- Deployment verification
- Regression prevention

## Coverage Requirements

Coverage requirements are linked to task acceptance criteria:

| Change Type | Minimum Coverage | Evidence Required |
|-------------|------------------|-------------------|
| New feature | 80% line coverage for new code | Coverage report artifact |
| Bug fix | Test that reproduces bug + fix | Before/after test output |
| Refactor | Maintain existing coverage | Coverage diff (no decrease) |
| Security fix | 100% coverage of security path | Security test evidence |

## Integration with AGENT-33 Verification

### Verification Log Entry

After completing a TDD cycle, log evidence to `verification-log.md`:

```markdown
| date | cycle-id | PR/branch | command | result | rationale link | link |
| YYYY-MM-DD | [task-id] | [branch] | [test command] | [pass/fail + count] | [session-log-path] | [PR-link] |
```

### Session Log Evidence

Each TDD cycle should be documented in the session log with:

1. **RED evidence**: Failing test output
2. **GREEN evidence**: Passing test output
3. **REFACTOR evidence**: Final test output + refactoring summary
4. **Coverage**: Coverage report or summary

### Acceptance Criteria Linkage

Map each acceptance criterion to test(s):

```markdown
## Acceptance Criteria Coverage
| Criterion | Test(s) | Status |
|-----------|---------|--------|
| AC-1: User can login | `test_login_success`, `test_login_failure` | ✅ Covered |
| AC-2: Password validation | `test_password_rules` | ✅ Covered |
```

## Cross-References

- Skills framework: `core/workflows/skills/README.md`
- Test matrix: `core/arch/test-matrix.md`
- Evidence requirements: `core/packs/policy-pack-v1/EVIDENCE.md`
- Verification log: `core/arch/verification-log.md`
- Testing rules: `core/packs/policy-pack-v1/rules/testing.md`
