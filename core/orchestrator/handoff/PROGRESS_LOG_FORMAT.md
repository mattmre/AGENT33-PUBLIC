# Progress Log Format + Rotation

Use progress logs for in-flight work. Keep entries short and timestamped.

## Required Fields
- Timestamp (ISO 8601)
- Task ID
- Status (queued/in_progress/review/blocked/done)
- Progress summary
- Blockers
- Next action
- Artifacts/links
- Commands (if run)

## Example Entry

| Timestamp | Task ID | Status | Progress summary | Blockers | Next action | Artifacts/links | Commands (if run) |
|---|---|---|---|---|---|---|---|
| 2026-01-16T16:10:00-05:00 | T4 | in_progress | Drafted spec-first checklist | None | Link in STATUS/PLAN | core/orchestrator/handoff/SPEC_FIRST_CHECKLIST.md | rg -n "SPEC_FIRST" -S core |

## Rotation Guidance
- Create a new progress log per day or per session.
- Store in `docs/session-logs/` with date in filename.
- Archive closed sessions; avoid editing older logs after closure.
