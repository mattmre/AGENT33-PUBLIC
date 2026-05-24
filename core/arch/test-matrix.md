# Test Matrix

Purpose: Define baseline and conditional tests for Architecture & Planning remediation PRs.

## Baseline (Always)
- Unit tests (full suite)
- Lint/format checks

## Project Commands (Fill In)
- Lint:
- Unit:
- Integration:
- Build:

## Minimum Smoke Tests
- Define a minimal subset for emergency fixes (must be documented in rationale).

## Project Command Source
- Record final commands here or link to a project-specific doc if maintained elsewhere.

## Conditional
- Parser changes: parser-specific tests + sample fixtures
- IO/file handling: integration tests for read/write paths
- Performance changes: benchmark or perf regression check
- Security changes: relevant security tests or static analysis
- Documentation-only: lint docs links and build docs if available

## Agentic Task Guidance
When tests are executed by AI agents (Planner, Implementer, Tester, etc.):

### Pre-Run Checklist
1. Confirm test harness exists and is operational
2. Record environment (OS, runtime version, dependencies)
3. Capture baseline state (git status, current branch)

### Agent-Specific Test Selection
| Agent Type | Minimum Tests | Extended Tests |
|------------|---------------|----------------|
| Implementer | Unit tests for changed modules | Full suite if touching shared code |
| Debugger | Failing test + related tests | Regression suite for affected area |
| Refactorer | Full unit suite | Integration tests if API changed |
| Tester | N/A (agent creates tests) | Run all new + existing tests |
| Reviewer | Read-only (no execution) | Optional: spot-check critical paths |

### Evidence Requirements for Agents
- Record exact command with flags
- Capture stdout/stderr (summary + full if failures)
- Log exit codes
- Note any flaky tests observed
- Link to session log for audit trail

## Partial Run Guidance
When full test suite cannot execute:

### Valid Reasons for Partial Runs
- Environment missing dependencies (document which)
- Tests require external services unavailable
- Time-boxed fix requires smoke tests only
- Documentation-only changes (no runtime tests)

### Partial Run Protocol
1. **Document Reason**: Explain why full suite skipped
2. **Select Minimum Set**: Choose smoke tests or affected-module tests
3. **Record Selection Rationale**: Link to this matrix + specific justification
4. **Flag for Follow-up**: Note in session log if full run needed later

### Partial Run Evidence Format
| Scope | Commands | Result | Skipped | Reason |
|-------|----------|--------|---------|--------|
| Smoke | `pytest tests/smoke/` | 5 passed | 95 | Time-boxed hotfix |
| Module | `pytest tests/unit/parser/` | 24 passed | 96 | Only parser changed |
| None | N/A | N/A | 120 | Docs-only; no harness |

### Minimal-Diff Verification
Use this check when the change is documentation-only, evidence-only, or a narrow
runtime fix:

1. Run `git diff --check` to catch whitespace and patch-format defects.
2. Run `git diff --stat` and confirm the changed files match the declared scope.
3. Record why broader tests are unnecessary or list the targeted commands that
   cover the touched surface.
4. If a minimal-diff run touches shared code, escalate to the affected-module
   or full-suite guidance above.

### Escalation
If partial run is due to blocked environment, create follow-up task to:
1. Fix environment issue
2. Run full suite
3. Update verification log with complete evidence

## Test Selection Rationale
Format:
- PR/branch:
- selected tests:
- rationale:
- partial run (yes/no):
- follow-up needed (yes/no):
