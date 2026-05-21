# Testing Rules

Purpose: Define testing requirements, workflow standards, and verification evidence for agent-executed tasks.

## Rules

### 1. TDD as Default Workflow

**Requirement**: Use Test-Driven Development (TDD) as the default workflow for new feature implementation.

**Applies To**:
- New features with clear acceptance criteria
- Bug fixes (write failing test first)
- Refactoring with behavior changes

**Exceptions**:
- Exploratory/spike work (document as such)
- Documentation-only changes
- Configuration changes without logic

**Reference**: See `core/workflows/skills/tdd-workflow.md` for detailed TDD skill guidance.

### 2. Coverage Requirements

**Requirement**: Maintain minimum test coverage for changes.

| Change Type | Minimum Coverage | Measurement |
|-------------|------------------|-------------|
| New feature | 80% line coverage | New code only |
| Bug fix | 100% of fix path | Regression test required |
| Refactor | No decrease | Compare before/after |
| Security fix | 100% of security path | Security-specific tests |

**Enforcement**:
- Run coverage tool as part of test execution
- Include coverage report in evidence capture
- Flag coverage decreases for review

**Reference**: Coverage linked to acceptance criteria per `tdd-workflow.md#coverage-requirements`.

### 3. Verification Evidence Requirements

**Requirement**: Capture and log verification evidence for all test executions.

**Minimum Evidence**:
- Exact command executed
- Exit code and pass/fail count
- Timestamp of execution
- Link to full output (if verbose)

**Evidence Format**:
```markdown
## Test Evidence
- Command: `pytest tests/ -v`
- Result: 47 passed, 0 failed
- Exit code: 0
- Timestamp: 2026-01-16T14:30:00Z
- Coverage: 85% (new code)
```

**Storage**:
- Session log for immediate capture
- Verification log for audit trail
- Link from task/PR for traceability

**Reference**: Evidence requirements per `core/packs/policy-pack-v1/EVIDENCE.md`.

### 4. Test Selection Guidance

**Requirement**: Select appropriate tests based on change scope.

**Selection Matrix**:
| Change Scope | Minimum Tests | Extended Tests |
|--------------|---------------|----------------|
| Single function | Unit tests for function | Related unit tests |
| Module | All module unit tests | Integration tests |
| Cross-module | Affected module tests | Full unit suite |
| API change | API tests + consumers | Full integration suite |
| Database schema | Migration tests | Full E2E suite |

**Reference**: Detailed guidance in `core/arch/test-matrix.md`.

### 5. Regression Prevention

**Requirement**: Ensure changes do not break existing functionality.

**Process**:
1. Run existing test suite before making changes (baseline)
2. Make changes incrementally
3. Run relevant tests after each significant change
4. Run full suite before final commit
5. Document any new test failures with analysis

**Flaky Test Handling**:
- Note any flaky tests observed
- Do not hide failures as "flaky" without investigation
- Report persistent flaky tests for team attention

### 6. Test Isolation

**Requirement**: Tests must be independent and isolated.

**Principles**:
- No shared mutable state between tests
- Each test sets up its own preconditions
- Tests can run in any order
- Tests can run in parallel (where supported)

**Anti-Patterns**:
- Tests depending on execution order
- Tests modifying global state
- Tests requiring specific environment not documented

## Enforcement Checklist

Before completing a task with code changes:

- [ ] TDD workflow followed (or exception documented)
- [ ] Coverage meets requirements for change type
- [ ] Test evidence captured in session log
- [ ] Verification log updated with entry
- [ ] No regressions in existing tests
- [ ] Test selection rationale documented

## Partial Test Execution

When full test suite cannot run:

1. **Document reason**: Environment issue, missing deps, time constraint
2. **Run minimum set**: Smoke tests or affected-module tests
3. **Record partial evidence**: What ran, what skipped, why
4. **Flag follow-up**: Note in session log if full run needed

**Reference**: Partial run guidance in `core/arch/test-matrix.md#partial-run-guidance`.

## Cross-References

- TDD workflow skill: `core/workflows/skills/tdd-workflow.md`
- Test matrix: `core/arch/test-matrix.md`
- Evidence requirements: `core/packs/policy-pack-v1/EVIDENCE.md`
- Verification log: `core/arch/verification-log.md`
- Regression gates: `core/arch/REGRESSION_GATES.md`
