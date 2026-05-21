# Session Wrap Template

Use this at the end of an orchestration session.

## Session Summary
- Date:
- Objectives:
- Work completed:

## Handoff Metadata
- Session owner:
- Review required (yes/no):
- Evidence captured (yes/no):

## Files Touched
- 

## Decisions
- 

## Risks / Issues
- 

## Next Steps
- 

## Handoff Checklist
- [ ] TASKS updated with current status
- [ ] Evidence capture recorded for completed tasks (use `EVIDENCE_CAPTURE.md` template)
- [ ] Review capture recorded if risk triggers applied
- [ ] Decisions logged if scope or architecture changed
- [ ] Verification log updated (`core/arch/verification-log.md`)
- [ ] Next-session narrative updated if priorities changed

## Review Handoff Summary
- Reviewed by:
- Required fixes:
- Follow-ups:

## Verification Evidence Example
See `EVIDENCE_CAPTURE.md` for full template. Quick reference:

### Primary Verification
| Command | Output Summary | Exit Code |
|---------|---------------|-----------|
| `pytest tests/ -q` | 120 passed, 0 failed | 0 |

### Diff Summary
| Files Changed | Lines Added | Lines Removed | Rationale |
|---------------|-------------|---------------|-----------|
| `<file>` | +N | -N | `<why>` |
