# agent33.ingestion

Governed candidate lifecycle for external and community assets.

## Purpose

This module manages assets that originate outside the AGENT33 first-party pack
tree — community submissions, externally sourced skills, workflows, and tools.
It implements the lifecycle defined in architectural decision #18, plus the
operator-facing history and notification surfaces needed to review assets:

```
candidate -> validated -> published -> revoked
```

External assets enter at `CANDIDATE` status with `LOW` confidence and cannot
be executed until an operator explicitly promotes them through validation and
publication gates.

## Clean-Room Restriction

No code in this module may originate from the EvoMap/Evolver project. See the
design contract for the full legal and architectural rationale:

- `docs/research/evolver-clean-room-guardrails.md`

## Governing Decisions

- Decision #17 — Evolver ingestion boundary (concept-only clean-room adaptation)
- Decision #18 — Imported-asset lifecycle with confidence/trust labels

Both decisions are in `docs/phases/PHASE-PLAN-POST-P72-2026.md`.

## Module Contents

| Module | Status | Sprint | Description |
|--------|--------|--------|-------------|
| `models.py` | Active | 0 | `CandidateAsset` Pydantic type model |
| `service.py` | Active | 1 | lifecycle mutations, review queue, per-asset history |
| `journal.py` | Active | 4 | append-only timeline for transitions and review events |
| `mailbox.py` | Active | 5 | mailbox intake entrypoint and heartbeat |
| `metrics.py` | Active | 5 | persisted task metrics and recent history queries |
| `notifications.py` | Active | operator UX depth | webhook-style notification hooks for review/quarantine and approve/reject events |

## Operator UX surfaces

- `GET /v1/ingestion/candidates/{asset_id}/history` returns the current asset plus
  its timeline history.
- `GET|POST|PATCH /v1/ingestion/notification-hooks...` manages webhook-style
  notification hooks for operator-relevant ingestion events.
- Timeline entries now include non-transition events such as `ingested`,
  `review_required`, `quarantined`, `approved`, and `rejected`.
