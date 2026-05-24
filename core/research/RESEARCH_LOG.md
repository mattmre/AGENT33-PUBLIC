# Research Tracking Log

Purpose: durable index for Phase 20 research intake, roadmap refresh, and lessons-learned evidence. Detailed research briefs can live under `docs/research/`; this log is the stable governance-facing pointer named by `core/orchestrator/CONTINUOUS_IMPROVEMENT.md`.

## Active Research

| ID | Title | Type | Status | Owner | Target | Evidence |
|----|-------|------|--------|-------|--------|----------|
| RI-2026-020-001 | BHS v3.7.1 Phase 20 remediation | internal | accepted | Worker P20 | PR #653 | `docs/architecture/reviews/phase-20-continuous-improvement-closeout-2026-05-24.md` |

## Completed Research

| ID | Title | Outcome | Closed | Evidence |
|----|-------|---------|--------|----------|
| RI-2026-020-000 | Continuous-improvement baseline inventory | Identified missing criteria artifact, missing research log path, in-memory P20 core workflows, mixed phase scope, uneven route access, and thin frontend acceptance coverage. | 2026-05-24 | `docs/architecture/reviews/bhs-roadmap-phase-scorecard-2026-05-23.md` |

## Deferred Research

| ID | Title | Reason | Date | Next Review |
|----|-------|--------|------|-------------|
| RI-2026-020-D01 | Learning-signal automation as Phase 20 evidence | Learning signals, analytics, tuning loops, and proposal sandbox routes are later-phase enhancements and must not be counted as Phase 20 completion evidence. | 2026-05-24 | Later-phase BHS remediation |

## Rejected Research

| ID | Title | Reason | Date |
|----|-------|--------|------|
| RI-2026-020-R01 | Treat route presence as completion evidence | Rejected because BHS v3.7.1 requires current criteria, durable state, access control, tests, and evidence, not endpoint inventory alone. | 2026-05-24 |

## Intake Cadence

| Cadence | Owner | Required Action | Evidence Location |
|---------|-------|-----------------|-------------------|
| Weekly micro refresh | Orchestrator | Review submitted and triaged research intakes, update status, and link backlog references. | This log plus `/v1/improvements/intakes` |
| Monthly minor refresh | Phase lead | Review lessons, checklist state, metrics snapshots, and deferred research. | `/v1/improvements/lessons`, `/v1/improvements/checklists`, `/v1/improvements/metrics/history` |
| Quarterly major refresh | Product and engineering leads | Reconcile research backlog with roadmap, governance artifacts, and release priorities. | `core/orchestrator/CONTINUOUS_IMPROVEMENT.md` and roadmap docs |

## Evidence Ledger

| Artifact | Purpose |
|----------|---------|
| `docs/architecture/reviews/phase-criteria/phase-20.yaml` | Compiler-readable Phase 20 criteria artifact. |
| `engine/tests/test_phase20_improvements.py` | Backend P20 model, service, route, persistence, access-control, and tenant coverage. |
| `frontend/src/data/domains/improvements.test.ts` | Frontend Phase 20 core operation inventory and scope-boundary coverage. |
| `core/orchestrator/CONTINUOUS_IMPROVEMENT.md` | Governance source for intake template, refresh cadence, lessons template, and update workflow. |
