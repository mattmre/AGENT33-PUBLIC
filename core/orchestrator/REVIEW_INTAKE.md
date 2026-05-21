# Review Intake and Backlog Refinement

This document defines how PR review inputs (human + AI) are captured and converted
into actionable backlog items across the orchestration workflow.

## Goals
- Make review inputs tool-agnostic and durable.
- Preserve reviewer intent with minimal paraphrasing.
- Convert accepted findings into measurable tasks.
- Keep evidence and rationale linked to the PR and session logs.

## Inputs
- PR review comments (human and AI).
- Static checks and test results.
- Security or compliance notes.
- Reviewer summaries or review plans.

## Process
1) **Collect**: gather review comments and label by severity.
2) **Triage**: identify duplicates, scope, and acceptance criteria.
3) **Decide**: accept, defer, or reject with rationale.
4) **Convert**: create backlog items with acceptance checks.
5) **Execute**: implement fixes in small diffs with evidence capture.
6) **Close**: respond in PR with resolution and verification evidence.

## Severity Tags
- blocker: must fix before merge.
- major: high impact correctness or security risk.
- minor: low risk but recommended improvements.
- nit: optional style or clarity tweaks.

## Backlog Entry Template
- PR/Issue link:
- Finding summary:
- Severity:
- Decision (accept/defer/reject):
- Acceptance criteria:
- Verification steps:
- Owner:

## Evidence Capture
- Link to PR comment(s).
- Commands executed and outcomes.
- Artifacts or logs updated.

## Integration Points
- `core/orchestrator/handoff/TASKS.md` for task tracking.
- `core/orchestrator/handoff/REVIEW_CAPTURE.md` for review records.
- `core/arch/verification-log.md` for test evidence.
