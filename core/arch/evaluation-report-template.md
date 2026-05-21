# Evaluation Report Template

Purpose: Standardized reporting for baseline evaluation runs and regression tracking.

Related docs:
- `core/arch/evaluation-harness.md` (golden tasks and metrics definitions)
- `core/orchestrator/handoff/EVIDENCE_CAPTURE.md` (evidence capture patterns)
- `core/arch/verification-log.md` (verification evidence storage)

---

## Header

| Field | Value |
|-------|-------|
| Date | YYYY-MM-DD |
| Evaluator | (agent name or human reviewer) |
| Scope | (phase, task range, or full suite) |
| Baseline Reference | (commit hash, tag, or prior report ID) |
| Branch/PR | (current branch or PR number) |
| Run ID | (unique identifier for this evaluation run) |

---

## Metrics Summary

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| M-01: Success Rate | X / Y (Z%) | >= 80% | PASS / FAIL |
| M-02: Time-to-Green | Xm Ys | < 15m | PASS / FAIL |
| M-03: Rework Rate | X / Y (Z%) | < 20% | PASS / FAIL |
| M-04: Diff Size (avg) | +X / -Y lines | < 500 lines | PASS / FAIL |
| M-05: Scope Adherence | X / Y (Z%) | = 100% | PASS / FAIL |

### Metric Definitions

- **Success Rate**: Proportion of golden tasks that pass on first attempt (tasks passed / tasks attempted).
- **Time-to-Green**: Elapsed time from task start to all acceptance checks passing.
- **Rework Rate**: Proportion of tasks requiring revision after initial submission (tasks revised / tasks submitted).
- **Diff Size**: Average lines changed per task (additions + deletions).
- **Scope Adherence**: Percentage of tasks completed without scope violations or creep.

---

## Golden Task Results

| Task ID | Description | Expected Outcome | Actual Outcome | Pass/Fail | Notes |
|---------|-------------|------------------|----------------|-----------|-------|
| GT-001 | (task description) | (expected result) | (actual result) | PASS | (any notes) |
| GT-002 | (task description) | (expected result) | (actual result) | FAIL | (failure reason) |
| GT-003 | (task description) | (expected result) | (actual result) | PASS | (any notes) |

### Example Entries

| Task ID | Description | Expected Outcome | Actual Outcome | Pass/Fail | Notes |
|---------|-------------|------------------|----------------|-----------|-------|
| GT-001 | Create README with sections | README.md exists with Overview, Usage, Install sections | README.md created with all sections | PASS | Clean first attempt |
| GT-002 | Add CI workflow | .github/workflows/ci.yml with lint + test jobs | Missing test job in workflow | FAIL | Rework required: added test job |
| GT-003 | Document API endpoint | Endpoint doc with params, response, examples | All elements present and accurate | PASS | Minor formatting adjustment |

---

## Golden PR/Issue Results

| Case ID | Description | Acceptance Check | Result | Pass/Fail | Notes |
|---------|-------------|------------------|--------|-----------|-------|
| GC-001 | (case description) | (acceptance criteria) | (actual result) | PASS | (any notes) |
| GC-002 | (case description) | (acceptance criteria) | (actual result) | FAIL | (failure reason) |

### Example Entries

| Case ID | Description | Acceptance Check | Result | Pass/Fail | Notes |
|---------|-------------|------------------|--------|-----------|-------|
| GC-001 | PR review cycle | Review feedback addressed in 1 iteration | Addressed in 1 iteration | PASS | No rework needed |
| GC-002 | Issue triage | Correct labels and priority assigned | Missing priority label | FAIL | Manual correction applied |
| GC-003 | Merge conflict resolution | Clean merge with no manual intervention | Merged cleanly | PASS | Rebased before merge |

---

## Evidence Links

| Category | Artifact | Path/URL |
|----------|----------|----------|
| Session Log | (run session log) | `docs/session-logs/SESSION-YYYY-MM-DD_<description>.md` |
| Verification Log | (verification entry) | `core/arch/verification-log.md` |
| Diff Capture | (PR or commit diff) | (link or path) |
| Test Output | (test run results) | (link or path) |
| Artifacts | (other supporting files) | (link or path) |

### Artifact Retention

- Session logs: Retain indefinitely for audit trail.
- Test outputs: Retain for at least 2 release cycles.
- Diff captures: Retain until baseline is superseded.

---

## Outcome Summary

| Field | Value |
|-------|-------|
| Overall Result | PASS / FAIL / PARTIAL |
| Tasks Passed | X / Y |
| Cases Passed | X / Y |
| Blocking Issues | (count and brief description) |
| Non-Blocking Issues | (count and brief description) |

### Notes

- (Summary of significant findings)
- (Patterns observed across tasks)
- (Unexpected behaviors or edge cases)

### Recommendations

- (Suggested improvements or follow-ups)
- (Process changes if applicable)
- (Tasks to add to backlog if needed)

---

## Baseline Comparison

| Metric | Current Run | Previous Baseline | Delta | Trend |
|--------|-------------|-------------------|-------|-------|
| Success Rate | X% | Y% | +/-Z% | UP / DOWN / STABLE |
| Time-to-Green | Xm | Ym | +/-Zm | UP / DOWN / STABLE |
| Rework Rate | X% | Y% | +/-Z% | UP / DOWN / STABLE |
| Diff Size (avg) | X lines | Y lines | +/-Z lines | UP / DOWN / STABLE |

### Regression Analysis

- **Regressions Detected**: (list any metrics that worsened beyond threshold)
- **Improvements Noted**: (list any metrics that improved)
- **Root Cause**: (brief analysis if regression detected)
- **Action Items**: (required follow-ups for regressions)

### Baseline Update

- [ ] Current run qualifies as new baseline (all targets met)
- [ ] Previous baseline retained (regressions detected)
- [ ] New baseline pending review (partial pass)

---

## Checklist

- [ ] All golden tasks executed
- [ ] All golden cases evaluated
- [ ] Metrics calculated and recorded
- [ ] Evidence links verified and accessible
- [ ] Baseline comparison completed
- [ ] Outcome summary reviewed
- [ ] Recommendations documented
- [ ] Report reviewed by second evaluator (if required)

---

## Revision History

| Date | Evaluator | Change |
|------|-----------|--------|
| YYYY-MM-DD | (name) | Initial report |
| YYYY-MM-DD | (name) | (description of update) |
