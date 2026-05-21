# Review Capture Template

Use this template when a task triggers reviewer requirements.

Related docs:
- `core/orchestrator/TWO_LAYER_REVIEW.md` (two-layer review workflow)
- `core/orchestrator/handoff/REVIEW_CHECKLIST.md` (review checklist)
- `core/packs/policy-pack-v1/RISK_TRIGGERS.md` (risk triggers)

## Task
- ID:
- Owner:
- Branch/PR:

## Risk Assessment
- Risk level: [none|low|medium|high|critical]
- Triggers identified:
- L1 required: [yes|no]
- L2 required: [yes|no]

## L1 Review
- Reviewer:
- Date:
- Decision: [approved|changes_requested|escalated]
- Checklist results:
  - Code quality: [pass|fail|na]
  - Correctness: [pass|fail|na]
  - Testing: [pass|fail|na]
  - Scope: [pass|fail|na]

## L2 Review (if required)
- Reviewer:
- Date:
- Decision: [approved|changes_requested|escalated]
- Checklist results:
  - Architecture: [pass|fail|na]
  - Security: [pass|fail|na]
  - Compliance: [pass|fail|na]
  - Impact: [pass|fail|na]

## Review Summary
- Required issues (must fix):
- Suggested improvements:
- Test suggestions:

## Resolution
- Fixed items:
- Deferred items:
- Follow-up tasks:

## Final Signoff
- Approved by:
- Approved at:
- Conditions:

## Evidence
- Verification log ref:
- Evidence capture ref:

## Example Summary
- Required issues: add null-check on input parser.
- Suggested improvements: document new CLI flag.
- Test suggestions: run unit and integration tests for parser module.
