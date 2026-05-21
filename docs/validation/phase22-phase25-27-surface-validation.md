# Phase 22 Surface Validation for Phases 25-27

**Date:** 2026-03-09  
**Validation branch:** `codex/session60-phase22-docs-validation`  
**Stack under validation:** `codex/session58-phase26-wizard`

## Goal

Validate that the Phase 22 frontend control-plane surface correctly hosts the Phase 25 live workflow transport, the Phase 27 preset-driven workflow flow, and the Phase 26 improvement-cycle review wizard without regressing the operator experience.

## Scope

Validated surfaces:

- Run-scoped workflow live transport
- Workflow graph overlays and refresh behavior
- Canonical improvement-cycle presets and workflow operation wiring
- Improvement-cycle review wizard
- Review artifact linkage and signoff lifecycle

Not claimed by this record:

- Full browser E2E against a live backend/frontend stack
- Manual visual QA across responsive breakpoints
- Merge-readiness of unrelated open PRs outside this stack

> Note
> This validation is intentionally evidence-backed. It uses targeted automated tests that exercise real behavior in the affected components and routes. It is not a placeholder checklist.

## Validation Matrix

| Surface | Evidence | Result |
| --- | --- | --- |
| Workflow WebSocket transport | `engine/tests/test_workflow_ws.py` | Pass |
| Workflow SSE fallback | `engine/tests/test_workflow_sse.py` | Pass |
| Graph overlay with `run_id` | `engine/tests/test_visualizations_api.py` | Pass |
| Review artifact linkage and review state machine | `engine/tests/test_phase15_review.py` | Pass |
| Canonical workflow templates | `engine/tests/test_improvement_cycle_templates.py` | Pass |
| Frontend workflow live transport helper | `frontend/src/lib/workflowLiveTransport.test.ts` | Pass |
| Graph re-render and selected-node refresh | `frontend/src/components/WorkflowGraph.test.ts` | Pass |
| OperationCard live workflow integration | `frontend/src/components/OperationCard.test.tsx` | Pass |
| Preset catalog and workflow domain contract | `frontend/src/features/improvement-cycle/presets.test.ts`, `frontend/src/data/domains/workflows.test.ts` | Pass |
| Improvement-cycle wizard artifact, L2 path, and tool approvals | `frontend/src/features/improvement-cycle/ImprovementCycleWizard.test.tsx` | Pass |

## Commands Executed

Backend:

```powershell
$env:PYTHONPATH='<repo-root>/engine/src'
python -m pytest tests/test_workflow_ws.py tests/test_workflow_sse.py tests/test_visualizations_api.py tests/test_phase15_review.py tests/test_improvement_cycle_templates.py -q --no-cov
```

Result:

- `111 passed in 2.50s`

Frontend:

```powershell
npm ci
npm run lint
npm test -- --run src/lib/workflowLiveTransport.test.ts src/components/WorkflowGraph.test.ts src/components/OperationCard.test.tsx src/features/improvement-cycle/presets.test.ts src/features/improvement-cycle/ImprovementCycleWizard.test.tsx src/data/domains/workflows.test.ts
npm run build
```

Results:

- `npm run lint` passed
- `45 passed` across the targeted Vitest selection
- `npm run build` passed

## What This Confirms

1. The Phase 22 control plane can host a live workflow experience that starts from a single-run execute operation, hydrates a run-scoped graph, and stays synchronized through WS or SSE transport.
2. The canonical improvement-cycle preset catalog is wired into the workflow domain and can drive both workflow creation and execution payloads.
3. The Phase 26 wizard closes the gap between raw explanation/review/approval endpoints by providing a guided artifact -> review -> risk -> signoff -> tool-approval flow.
4. Review records preserve lightweight explanation artifact links, which prevents the flow from collapsing into a client-only transient state.

## Residual Risks

- This record does not replace a true browser-backed E2E run against a live backend/frontend deployment.
- The backend test invocation required a branch-local `PYTHONPATH` because the local Python environment also contains editable installs from other worktrees.
- The frontend validation required `npm ci` inside the fresh worktree because dependencies are not shared automatically across worktrees.

## Recommendation

Treat the Phase 22 extension surface for the Phase 25-27 stack as validated for PR review. If additional confidence is needed before merge, the next step should be one browser-level manual pass on the live control plane, not more shallow unit-only assertions.

