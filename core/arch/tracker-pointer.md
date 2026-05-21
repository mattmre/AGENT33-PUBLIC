# Active Tracker Pointer

Purpose: Keep a single canonical link to the current tracker to reduce context churn.

## Current Tracker
- `docs/refinement-remediation/YYYY-MM-DD_tracker.md`

## Last Updated
- YYYY-MM-DD

## Cycle ID
- AEP-YYYYMMDD-N

Consistency rule:
- Cycle ID must match the cycle-id used in the backlog index and scope lock record.
- Pointer updates are owned by the cycle owner in the tracker index.

## Verification Log Path
- `docs/Architecture & Planning/cycles/YYYY-MM-DD/verification-log.md`

Note:
- Per-cycle logs are default. Use legacy logs only when cycle layout is not used.
