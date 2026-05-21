# Evaluation Harness

Purpose: Define golden tasks, golden PR/issue cases, metrics, and an evaluation playbook for measuring orchestration quality and agent performance.

Related docs:
- `core/arch/REGRESSION_GATES.md` (gating thresholds, triage playbook)
- `core/orchestrator/handoff/EVIDENCE_CAPTURE.md` (evidence capture template)
- `core/arch/test-matrix.md` (test selection and partial run guidance)
- `core/arch/verification-log.md` (verification evidence storage)
- `core/packs/policy-pack-v1/ACCEPTANCE_CHECKS.md` (acceptance check patterns)

## Design Principles

1. **Model-Agnostic**: Tasks and metrics apply to any LLM or human agent.
2. **Repo-Agnostic**: Evaluation patterns are portable across projects.
3. **Deterministic**: Golden tasks have stable, verifiable expected outcomes.
4. **Evidence-Based**: Every evaluation run produces auditable artifacts.

---

## Golden Tasks

Golden tasks are reference scenarios with known expected outcomes. Use these to validate orchestration protocol adherence and agent behavior consistency.

### GT-01: Documentation-Only Task

**Description**: Create or update a markdown file with specified content structure.

**Input**:
- Task: "Add a glossary entry for 'golden task' to `core/arch/glossary.md`"
- Constraints: No code changes, single file edit, minimal diff

**Expected Outcome**:
| Check | Pass Criteria |
|-------|---------------|
| File modified | `core/arch/glossary.md` contains new entry |
| Entry format | Follows existing glossary term format |
| Diff size | < 20 lines added |
| Other files | No other files modified |

**Pass/Fail Criteria**:
- PASS: All checks satisfied; entry is accurate and formatted correctly.
- FAIL: Missing entry, incorrect format, extraneous changes, or wrong file.

---

### GT-02: Task Queue Update

**Description**: Add a new task to TASKS.md following the minimum task payload template.

**Input**:
- Task: "Add T99 to TASKS.md: 'Update README with project badges'"
- Constraints: Follow minimum task payload format, assign to Documentation Agent

**Expected Outcome**:
| Check | Pass Criteria |
|-------|---------------|
| Task added | T99 appears in TASKS.md queue section |
| Payload complete | ID, title, owner, acceptance criteria, verification steps present |
| Format correct | Matches existing task entry structure |
| No side effects | No changes outside TASKS.md |

**Pass/Fail Criteria**:
- PASS: Task entry is complete, correctly formatted, and placed in queue.
- FAIL: Missing fields, incorrect format, or unrelated changes.

---

### GT-03: Cross-Reference Validation

**Description**: Verify and fix broken cross-references between documents.

**Input**:
- Task: "Audit `core/orchestrator/README.md` for broken links and fix any found"
- Constraints: Report findings, fix only confirmed broken links

**Expected Outcome**:
| Check | Pass Criteria |
|-------|---------------|
| Audit complete | All links in target file checked |
| Report generated | List of links checked with status (valid/broken) |
| Fixes applied | Broken links corrected or flagged as external/missing |
| Evidence recorded | Audit results captured in session log |

**Pass/Fail Criteria**:
- PASS: All links audited, broken links fixed or documented, no false fixes.
- FAIL: Incomplete audit, incorrect fixes, or undocumented findings.

---

### GT-04: Template Instantiation

**Description**: Create a new document using an existing template.

**Input**:
- Task: "Create a risk memo for finding F-001 using `core/arch/risk-memo-template.md`"
- Constraints: All template sections completed, no placeholders left

**Expected Outcome**:
| Check | Pass Criteria |
|-------|---------------|
| File created | `core/arch/risk-memos/risk-memo-F-001.md` exists |
| Template followed | All sections from template present |
| Placeholders filled | No `<placeholder>` or `TBD` markers remain |
| Content accurate | Finding ID and severity match input |

**Pass/Fail Criteria**:
- PASS: File created, all sections filled, content accurate.
- FAIL: Missing file, unfilled sections, or content errors.

---

### GT-05: Scope Lock Enforcement

**Description**: Reject an out-of-scope request and document the escalation.

**Input**:
- Task: "Implement a new CLI command for data export"
- Scope lock: "Documentation updates only; no code changes"

**Expected Outcome**:
| Check | Pass Criteria |
|-------|---------------|
| Request rejected | No code files created or modified |
| Escalation documented | Scope violation noted in session log or DECISIONS.md |
| Rationale provided | Clear explanation of why request is out of scope |
| Alternative offered | Suggestion to create follow-up task or re-scope |

**Pass/Fail Criteria**:
- PASS: Request correctly rejected, escalation documented, rationale clear.
- FAIL: Code changes made, no escalation, or unclear rationale.

---

### GT-06: Evidence Capture Workflow

**Description**: Complete a task and produce compliant evidence capture.

**Input**:
- Task: "Update the phase-planning.md to add Phase 8 link"
- Constraints: Must use EVIDENCE_CAPTURE.md template

**Expected Outcome**:
| Check | Pass Criteria |
|-------|---------------|
| Task completed | Phase 8 link added to phase-planning.md |
| Evidence captured | EVIDENCE_CAPTURE.md sections filled |
| Commands recorded | At least one verification command with output |
| Diff summary present | Files changed, lines added/removed documented |

**Pass/Fail Criteria**:
- PASS: Task complete with fully populated evidence capture.
- FAIL: Incomplete evidence, missing commands, or no diff summary.

---

### GT-07: Multi-File Coordinated Update

**Description**: Update multiple related files while maintaining consistency.

**Input**:
- Task: "Add new agent role 'Validator' to routing map and agent prompts"
- Files: `core/orchestrator/AGENT_ROUTING_MAP.md`, `core/orchestrator/agents/validator.md`

**Expected Outcome**:
| Check | Pass Criteria |
|-------|---------------|
| Routing map updated | Validator role appears with task types |
| Agent prompt created | `validator.md` exists with role definition |
| Cross-references valid | Routing map links to agent file |
| Consistency maintained | Role name and capabilities match across files |

**Pass/Fail Criteria**:
- PASS: Both files updated consistently, cross-references valid.
- FAIL: Inconsistent updates, broken links, or missing file.

---

## Golden PR/Issue Cases

Golden PR/issue cases validate review quality, diff assessment, and acceptance check enforcement.

### GC-01: Clean Single-File PR

**Description**: A PR with a single, well-scoped documentation change.

**Input PR**:
- Title: "Add evaluation metrics section to phase-planning.md"
- Files changed: 1
- Lines added: 15
- Lines removed: 0

**Acceptance Checks**:
| Check | Expected Result |
|-------|-----------------|
| Scope assessment | Single file, documentation only |
| Diff size | Small (< 50 lines) |
| Risk triggers | None (docs-only) |
| Required reviewers | No (low risk) |
| Merge readiness | Ready after lint check |

**Pass/Fail Criteria**:
- PASS: PR correctly assessed as low-risk, no unnecessary reviewer required.
- FAIL: Over-escalation or missed scope issues.

---

### GC-02: Multi-File Consistency PR

**Description**: A PR updating multiple related documents that must remain consistent.

**Input PR**:
- Title: "Add new phase 9 to phase planning and index"
- Files changed: 3 (`core/arch/phase-planning.md`, `core/INDEX.md`, `core/ORCHESTRATION_INDEX.md`)
- Lines added: 25
- Lines removed: 0

**Acceptance Checks**:
| Check | Expected Result |
|-------|-----------------|
| Consistency check | Phase 9 referenced identically across files |
| Cross-reference audit | All new links resolve correctly |
| Diff size | Medium (25-100 lines) |
| Risk triggers | Architecture change (requires review) |
| Required reviewers | Yes (architecture alignment) |

**Pass/Fail Criteria**:
- PASS: Consistency verified, architecture review triggered.
- FAIL: Inconsistency missed or review not required when needed.

---

### GC-03: Out-of-Scope PR Rejection

**Description**: A PR that violates scope lock and should be rejected or revised.

**Input PR**:
- Title: "Add CLI implementation for export command"
- Files changed: 2 (`src/cli/export.py`, `tests/test_export.py`)
- Scope lock: "Documentation updates only"

**Acceptance Checks**:
| Check | Expected Result |
|-------|-----------------|
| Scope violation detected | Yes (code files in docs-only scope) |
| Rejection rationale | Clear reference to scope lock |
| Suggested action | Split PR or defer to next scope |
| Merge readiness | Not ready (scope violation) |

**Pass/Fail Criteria**:
- PASS: Scope violation detected, clear rejection with rationale.
- FAIL: PR accepted despite scope violation.

---

### GC-04: Rework-Required PR

**Description**: A PR with issues that require revision before merge.

**Input PR**:
- Title: "Update glossary with new terms"
- Files changed: 1
- Issues: Duplicate term, inconsistent formatting, missing cross-reference

**Acceptance Checks**:
| Check | Expected Result |
|-------|-----------------|
| Issues identified | Duplicate term flagged |
| Format check | Inconsistent formatting noted |
| Cross-reference audit | Missing link identified |
| Rework items | 3 specific items listed |
| Merge readiness | Not ready (rework required) |

**Pass/Fail Criteria**:
- PASS: All issues identified with specific rework items.
- FAIL: Issues missed or vague rework request.

---

## Metrics Definitions

### M-01: Success Rate

**Definition**: Percentage of tasks that meet all acceptance criteria on first attempt.

**Formula**: `(tasks_passed_first_attempt / total_tasks_attempted) * 100`

**Measurement**:
- Count tasks where all acceptance checks pass without revision.
- Exclude tasks blocked by external dependencies.

**Target Baseline**: Establish initial baseline; track trend over time.

**Evidence Source**: TASKS.md status, session logs, verification-log.md entries.

---

### M-02: Time-to-Green

**Definition**: Elapsed time from task start to all acceptance criteria passing.

**Formula**: `task_completion_timestamp - task_start_timestamp`

**Measurement**:
- Record start time when task moves to "In Progress".
- Record completion time when task moves to "Done" with passing verification.
- Exclude blocked time if documented.

**Target Baseline**: Establish per-task-type baselines (small/medium/large).

**Evidence Source**: TASKS.md timestamps, session log timestamps.

---

### M-03: Rework Rate

**Definition**: Percentage of tasks requiring revision after initial completion attempt.

**Formula**: `(tasks_requiring_rework / total_tasks_completed) * 100`

**Measurement**:
- Count tasks where reviewer feedback required changes.
- Count tasks where acceptance criteria failed on first verification.

**Target Baseline**: Lower is better; track trend over time.

**Evidence Source**: REVIEW_CAPTURE.md entries, TASKS.md revision history.

---

### M-04: Diff Size

**Definition**: Total lines changed (added + removed) per task or PR.

**Formula**: `lines_added + lines_removed`

**Measurement**:
- Capture from git diff or PR summary.
- Record in EVIDENCE_CAPTURE.md diff summary section.

**Target Baseline**: Smaller is generally better for focused tasks; establish per-task-type norms.

**Evidence Source**: EVIDENCE_CAPTURE.md diff summary, git log.

---

### M-05: Scope Adherence

**Definition**: Percentage of tasks completed without scope violations or creep.

**Formula**: `(tasks_within_scope / total_tasks_attempted) * 100`

**Measurement**:
- Count tasks where no files outside scope were modified.
- Count tasks where no escalation for scope violation occurred.

**Target Baseline**: 100% is ideal; track violations as improvement opportunities.

**Evidence Source**: TASKS.md, session logs, DECISIONS.md escalations.

---

## Evaluation Playbook

### Step 1: Prepare Evaluation Environment

1. Confirm clean repository state (no uncommitted changes).
2. Record environment details:
   - Repository path
   - Branch name
   - Commit hash (HEAD)
   - Date and time
3. Create evaluation session log: `docs/session-logs/SESSION-YYYY-MM-DD_EVAL-<run-id>.md`

### Step 2: Select Golden Tasks

1. Choose golden tasks to run based on evaluation goals:
   - Full regression: Run all GT-01 through GT-07.
   - Targeted validation: Select specific tasks (e.g., GT-05 for scope enforcement).
2. Record selected tasks in session log.

### Step 3: Execute Golden Tasks

For each selected golden task:

1. Read the task input and constraints.
2. Execute the task following standard orchestration protocol.
3. Capture evidence using `core/orchestrator/handoff/EVIDENCE_CAPTURE.md` template.
4. Record pass/fail against each check in the expected outcome table.
5. Note any deviations or unexpected behaviors.

### Step 4: Execute Golden PR/Issue Cases (if applicable)

For each selected golden case:

1. Create or simulate the PR scenario.
2. Perform acceptance checks as documented.
3. Record assessment results.
4. Compare to expected results in the case definition.

### Step 5: Capture Baseline Metrics

1. Calculate metrics M-01 through M-05 for the evaluation run.
2. Record in the evaluation session log:
   ```
   ## Baseline Metrics
   - Success Rate (M-01): X%
   - Time-to-Green (M-02): [per-task times]
   - Rework Rate (M-03): X%
   - Diff Size (M-04): [per-task sizes]
   - Scope Adherence (M-05): X%
   ```

### Step 6: Generate Evaluation Report

1. Summarize pass/fail counts for golden tasks.
2. Summarize acceptance check results for golden cases.
3. Document any anomalies or improvement opportunities.
4. Store report in session log and reference from verification-log.md.

### Step 7: Archive Artifacts

1. Commit evaluation session log.
2. Update `core/arch/verification-log.md` with evaluation entry:
   ```
   - YYYY-MM-DD - eval-<run-id> - <branch> - golden task evaluation - X/Y passed - see session log
   ```
3. Store any generated artifacts (screenshots, exports) in documented location.

---

## Baseline Run Protocol

Before any optimization or change to orchestration protocols:

1. **Record Current State**: Document the orchestration version/commit being evaluated.
2. **Run Full Golden Suite**: Execute all GT-01 through GT-07 and GC-01 through GC-04.
3. **Capture All Metrics**: Record M-01 through M-05.
4. **Store as Baseline**: Mark this evaluation run as the baseline in the session log header.
5. **Reference in Changes**: Any subsequent change to orchestration should reference this baseline and show delta.

### Baseline Evidence Format

```markdown
## Baseline Run: YYYY-MM-DD

### Environment
- Repository: [path]
- Branch: [name]
- Commit: [hash]
- Orchestration version: [version or commit]

### Golden Task Results
| Task | Result | Notes |
|------|--------|-------|
| GT-01 | PASS/FAIL | [notes] |
| GT-02 | PASS/FAIL | [notes] |
| ... | ... | ... |

### Golden Case Results
| Case | Result | Notes |
|------|--------|-------|
| GC-01 | PASS/FAIL | [notes] |
| GC-02 | PASS/FAIL | [notes] |
| ... | ... | ... |

### Metrics
| Metric | Value |
|--------|-------|
| M-01 Success Rate | X% |
| M-02 Time-to-Green | [avg] |
| M-03 Rework Rate | X% |
| M-04 Diff Size | [avg] |
| M-05 Scope Adherence | X% |

### Artifacts
- Session log: [path]
- Evidence captures: [paths]
```

---

## References

- Evidence capture template: `core/orchestrator/handoff/EVIDENCE_CAPTURE.md`
- Test matrix and partial run guidance: `core/arch/test-matrix.md`
- Verification log format: `core/arch/verification-log.md`
- Acceptance checks policy: `core/packs/policy-pack-v1/ACCEPTANCE_CHECKS.md`
- Definition of done: `core/orchestrator/handoff/DEFINITION_OF_DONE.md`
