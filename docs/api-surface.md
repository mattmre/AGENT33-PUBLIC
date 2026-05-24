# API Surface

Source of truth:
- Route modules in `engine/src/agent33/api/routes/`
- Auth middleware in `engine/src/agent33/security/middleware.py`
- Scope checks in `engine/src/agent33/security/permissions.py`

Current access-layer scope:
- This document is the curated P22 frontend access-layer map, not an exhaustive
  post-P22 route dump. Later phases mounted additional routers in
  `engine/src/agent33/main.py`; complete runtime inventory should be generated
  from `app.routes`.
- P22 drift reconciliation on 2026-05-24 checked every operation exported from
  `frontend/src/data/domains/*.ts` against mounted FastAPI routes. Result:
  183 frontend domain endpoints, 0 missing backend route matches after trailing
  slash normalization.

## 1. Authentication Rules

Public (no auth required):
- `GET /health`
- `GET /health/channels`
- `GET /healthz`
- `GET /readyz`
- `GET /metrics`
- `POST /v1/auth/token`
- `GET /v1/dashboard/`
- `GET /v1/dashboard/metrics`
- `GET /v1/dashboard/alerts`
- `GET /v1/dashboard/lineage/{workflow_id}`
- `/docs`, `/redoc`, `/openapi.json`

All other endpoints require authentication (`Bearer` JWT or `X-API-Key`).

Defined scopes:
- `admin`
- `agents:read`
- `agents:write`
- `agents:invoke`
- `workflows:read`
- `workflows:write`
- `workflows:execute`
- `workspaces:read`
- `workspaces:write`
- `sessions:read`
- `sessions:write`
- `tools:execute`
- `plugins:read`
- `plugins:write`
- `operator:read`
- `operator:write`
- `multimodal:read`
- `multimodal:write`
- `outcomes:read`
- `outcomes:write`

## 2. Endpoint Map by Domain

### Health

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/health` | Public |
| GET | `/health/channels` | Public |
| GET | `/healthz` | Public |
| GET | `/readyz` | Public |
| GET | `/metrics` | Public |

### Auth

| Method | Path | Scope |
| --- | --- | --- |
| POST | `/v1/auth/token` | Public |
| POST | `/v1/auth/api-keys` | `admin` |
| DELETE | `/v1/auth/api-keys/{key_id}` | Authenticated (ownership/admin logic in handler) |

### Users

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/v1/users/` | `admin` |
| POST | `/v1/users/` | `admin` plus route approval |
| GET | `/v1/users/{username}` | `admin` |
| PATCH | `/v1/users/{username}` | `admin` plus route approval |
| POST | `/v1/users/{username}/disable` | `admin` plus route approval |
| POST | `/v1/users/{username}/enable` | `admin` plus route approval |
| POST | `/v1/users/{username}/roles` | `admin` plus route approval |
| POST | `/v1/users/{username}/tenant` | `admin` plus route approval |
| DELETE | `/v1/users/{username}` | `admin` plus route approval |

### Chat

| Method | Path | Scope |
| --- | --- | --- |
| POST | `/v1/chat/completions` | Authenticated |

### Agents

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/v1/agents/capabilities/catalog` | Authenticated |
| GET | `/v1/agents/search` | `agents:read` |
| GET | `/v1/agents/by-id/{agent_id}` | `agents:read` |
| GET | `/v1/agents/tool-loop/scores` | `agents:read` |
| GET | `/v1/agents/profiling/summaries` | `agents:read` |
| GET | `/v1/agents/profiling/bottlenecks` | `agents:read` |
| GET | `/v1/agents/profiling/hot-paths` | `agents:read` |
| GET | `/v1/agents/profiling/profiles` | `agents:read` |
| GET | `/v1/agents/profiling/{agent_name}` | `agents:read` |
| POST | `/v1/agents/preview-prompt` | `agents:read` |
| POST | `/v1/agents/validate` | Authenticated |
| GET | `/v1/agents/` | `agents:read` |
| GET | `/v1/agents/{name}` | `agents:read` |
| PUT | `/v1/agents/{name}` | `agents:write` |
| DELETE | `/v1/agents/{name}` | `agents:write` |
| POST | `/v1/agents/` | `agents:write` |
| POST | `/v1/agents/{name}/invoke` | `agents:invoke` |
| POST | `/v1/agents/{name}/invoke-iterative` | `agents:invoke` |
| POST | `/v1/agents/{name}/invoke-iterative/stream` | `agents:invoke` |
| GET | `/v1/agents/{name}/context-budget` | `agents:read` |

### Workflows

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/v1/workflows/` | `workflows:read` |
| GET | `/v1/workflows/{name}` | `workflows:read` |
| GET | `/v1/workflows/{name}/dag` | `workflows:read` |
| POST | `/v1/workflows/` | `workflows:write` |
| POST | `/v1/workflows/{name}/execute` | `workflows:execute` |
| POST | `/v1/workflows/{name}/schedule` | `workflows:execute` |
| GET | `/v1/workflows/schedules` | `workflows:read` |
| DELETE | `/v1/workflows/schedules/{job_id}` | `workflows:execute` |
| GET | `/v1/workflows/{name}/history` | `workflows:read` |
| GET | `/v1/workflows/runs/{run_id}` | `workflows:read` |
| GET | `/v1/workflows/runs/{run_id}/dag` | `workflows:read` |
| GET | `/v1/workflows/runs/{run_id}/events` | `workflows:read` |
| GET | `/v1/workflows/runs/{run_id}/artifacts` | `workflows:read` |
| GET | `/v1/workflows/runs/{run_id}/artifacts/{artifact_path:path}` | `workflows:read` |
| POST | `/v1/workflows/{run_id}/resume` | `workflows:execute` |
| GET | `/v1/workflows/{run_id}/events` | `workflows:read` |
| GET | `/v1/workflows/{run_id}/artifacts` | `operator:read` |
| POST | `/v1/workflows/{run_id}/steps/{step_id}/retry` | `operator:write` |
| GET | `/v1/workflows/{run_id}/checkpoints` | `workflows:read` |
| GET | `/v1/workflows/{run_id}/replay` | `workflows:read` |
| GET | `/v1/visualizations/workflows/{workflow_id}/graph` | `workflows:read` |

### Explanations

| Method | Path | Scope |
| --- | --- | --- |
| POST | `/v1/explanations/` | `workflows:write` |
| GET | `/v1/explanations/` | `workflows:read` |
| GET | `/v1/explanations/{explanation_id}` | `workflows:read` |
| DELETE | `/v1/explanations/{explanation_id}` | `workflows:write` |
| POST | `/v1/explanations/{explanation_id}/fact-check` | `workflows:write` |
| GET | `/v1/explanations/{explanation_id}/claims` | `workflows:read` |
| POST | `/v1/explanations/diff-review` | `workflows:write` |
| POST | `/v1/explanations/plan-review` | `workflows:write` |
| POST | `/v1/explanations/project-recap` | `workflows:write` |

### Workspaces

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/v1/workspaces/` | `workspaces:read` |
| POST | `/v1/workspaces/` | `workspaces:write` plus route approval |
| GET | `/v1/workspaces/{workspace_id}` | `workspaces:read` |
| PATCH | `/v1/workspaces/{workspace_id}` | `workspaces:write` plus route approval |
| DELETE | `/v1/workspaces/{workspace_id}` | `workspaces:write` plus route approval |
| GET | `/v1/workspaces/{workspace_id}/projects` | `workspaces:read` |
| POST | `/v1/workspaces/{workspace_id}/projects` | `workspaces:write` plus route approval |
| PATCH | `/v1/workspaces/{workspace_id}/projects/{project_id}` | `workspaces:write` plus route approval |
| DELETE | `/v1/workspaces/{workspace_id}/projects/{project_id}` | `workspaces:write` plus route approval |
| GET | `/v1/workspaces/{workspace_id}/recovery` | `workspaces:read` |

### Memory

| Method | Path | Scope |
| --- | --- | --- |
| POST | `/v1/memory/search` | `agents:read` |
| GET | `/v1/memory/sessions/{session_id}/observations` | `agents:read` |
| POST | `/v1/memory/sessions/{session_id}/summarize` | `agents:write` |

### Reviews

| Method | Path | Scope |
| --- | --- | --- |
| POST | `/v1/reviews/` | `workflows:write` |
| GET | `/v1/reviews/` | `workflows:read` |
| GET | `/v1/reviews/{review_id}` | `workflows:read` |
| DELETE | `/v1/reviews/{review_id}` | `workflows:write` |
| POST | `/v1/reviews/{review_id}/assess` | `workflows:write` |
| POST | `/v1/reviews/{review_id}/ready` | `workflows:write` |
| POST | `/v1/reviews/{review_id}/assign-l1` | `workflows:write` |
| POST | `/v1/reviews/{review_id}/l1` | `workflows:write` |
| POST | `/v1/reviews/{review_id}/assign-l2` | `workflows:write` |
| POST | `/v1/reviews/{review_id}/l2` | `workflows:write` |
| POST | `/v1/reviews/{review_id}/approve` | `workflows:write` |
| POST | `/v1/reviews/{review_id}/merge` | `workflows:write` |

### Traces

| Method | Path | Scope |
| --- | --- | --- |
| POST | `/v1/traces/` | `tools:execute` |
| GET | `/v1/traces/` | `workflows:read` |
| GET | `/v1/traces/{trace_id}` | `workflows:read` |
| POST | `/v1/traces/{trace_id}/actions` | `tools:execute` |
| POST | `/v1/traces/{trace_id}/complete` | `tools:execute` |
| POST | `/v1/traces/{trace_id}/failures` | `tools:execute` |
| GET | `/v1/traces/{trace_id}/failures` | `workflows:read` |

### Evaluations

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/v1/evaluations/golden-tasks` | `workflows:read` |
| GET | `/v1/evaluations/golden-cases` | `workflows:read` |
| GET | `/v1/evaluations/gates/{gate}/tasks` | `workflows:read` |
| POST | `/v1/evaluations/runs` | `tools:execute` |
| GET | `/v1/evaluations/runs` | `workflows:read` |
| GET | `/v1/evaluations/runs/{run_id}` | `workflows:read` |
| POST | `/v1/evaluations/runs/{run_id}/results` | `tools:execute` |
| POST | `/v1/evaluations/runs/{run_id}/baseline` | `tools:execute` |
| GET | `/v1/evaluations/baselines` | `workflows:read` |
| GET | `/v1/evaluations/regressions` | `workflows:read` |
| PATCH | `/v1/evaluations/regressions/{regression_id}/triage` | `tools:execute` |
| POST | `/v1/evaluations/regressions/{regression_id}/resolve` | `tools:execute` |

### Scheduled Gates

| Method | Path | Scope |
| --- | --- | --- |
| POST | `/v1/evaluations/schedules` | `tools:execute` |
| GET | `/v1/evaluations/schedules` | `workflows:read` |
| GET | `/v1/evaluations/schedules/{schedule_id}` | `workflows:read` |
| DELETE | `/v1/evaluations/schedules/{schedule_id}` | `tools:execute` |
| POST | `/v1/evaluations/schedules/{schedule_id}/trigger` | `tools:execute` |
| GET | `/v1/evaluations/schedules/{schedule_id}/history` | `workflows:read` |

### Autonomy

| Method | Path | Scope |
| --- | --- | --- |
| POST | `/v1/autonomy/budgets` | `tools:execute` |
| GET | `/v1/autonomy/budgets` | `workflows:read` |
| GET | `/v1/autonomy/budgets/{budget_id}` | `workflows:read` |
| DELETE | `/v1/autonomy/budgets/{budget_id}` | `tools:execute` |
| POST | `/v1/autonomy/budgets/{budget_id}/transition` | `tools:execute` |
| POST | `/v1/autonomy/budgets/{budget_id}/activate` | `tools:execute` |
| POST | `/v1/autonomy/budgets/{budget_id}/suspend` | `tools:execute` |
| POST | `/v1/autonomy/budgets/{budget_id}/complete` | `tools:execute` |
| GET | `/v1/autonomy/budgets/{budget_id}/preflight` | `workflows:read` |
| POST | `/v1/autonomy/budgets/{budget_id}/enforcer` | `tools:execute` |
| POST | `/v1/autonomy/budgets/{budget_id}/enforce/file` | `tools:execute` |
| POST | `/v1/autonomy/budgets/{budget_id}/enforce/command` | `tools:execute` |
| POST | `/v1/autonomy/budgets/{budget_id}/enforce/network` | `tools:execute` |
| GET | `/v1/autonomy/escalations` | `workflows:read` |
| POST | `/v1/autonomy/budgets/{budget_id}/escalate` | `tools:execute` |
| POST | `/v1/autonomy/escalations/{escalation_id}/acknowledge` | `tools:execute` |
| POST | `/v1/autonomy/escalations/{escalation_id}/resolve` | `tools:execute` |

### Releases

| Method | Path | Scope |
| --- | --- | --- |
| POST | `/v1/releases` | `tools:execute` |
| GET | `/v1/releases` | `workflows:read` |
| GET | `/v1/releases/{release_id}` | `workflows:read` |
| POST | `/v1/releases/{release_id}/freeze` | `tools:execute` |
| POST | `/v1/releases/{release_id}/rc` | `tools:execute` |
| POST | `/v1/releases/{release_id}/validate` | `tools:execute` |
| POST | `/v1/releases/{release_id}/publish` | `tools:execute` |
| GET | `/v1/releases/{release_id}/checklist` | `workflows:read` |
| PATCH | `/v1/releases/{release_id}/checklist` | `tools:execute` |
| POST | `/v1/releases/sync/rules` | `tools:execute` |
| GET | `/v1/releases/sync/rules` | `workflows:read` |
| POST | `/v1/releases/sync/rules/{rule_id}/dry-run` | `tools:execute` |
| POST | `/v1/releases/sync/rules/{rule_id}/execute` | `tools:execute` |
| POST | `/v1/releases/{release_id}/rollback` | `tools:execute` |
| GET | `/v1/releases/rollbacks` | `workflows:read` |
| POST | `/v1/releases/rollback/recommend` | `workflows:read` |

### Improvements

| Method | Path | Scope |
| --- | --- | --- |
| POST | `/v1/improvements/intakes` | Authenticated |
| GET | `/v1/improvements/intakes` | Authenticated |
| GET | `/v1/improvements/intakes/{intake_id}` | Authenticated |
| POST | `/v1/improvements/intakes/{intake_id}/transition` | Authenticated |
| POST | `/v1/improvements/lessons` | Authenticated |
| GET | `/v1/improvements/lessons` | Authenticated |
| GET | `/v1/improvements/lessons/{lesson_id}` | Authenticated |
| POST | `/v1/improvements/lessons/{lesson_id}/complete-action` | Authenticated |
| POST | `/v1/improvements/lessons/{lesson_id}/verify` | Authenticated |
| POST | `/v1/improvements/checklists` | Authenticated |
| GET | `/v1/improvements/checklists` | Authenticated |
| GET | `/v1/improvements/checklists/{checklist_id}` | Authenticated |
| POST | `/v1/improvements/checklists/{checklist_id}/complete` | Authenticated |
| GET | `/v1/improvements/checklists/{checklist_id}/evaluate` | Authenticated |
| GET | `/v1/improvements/metrics` | Authenticated |
| GET | `/v1/improvements/metrics/history` | Authenticated |
| POST | `/v1/improvements/metrics/snapshot` | Authenticated |
| POST | `/v1/improvements/metrics/default-snapshot` | Authenticated |
| GET | `/v1/improvements/metrics/trend/{metric_id}` | Authenticated |
| POST | `/v1/improvements/refreshes` | Authenticated |
| GET | `/v1/improvements/refreshes` | Authenticated |
| GET | `/v1/improvements/refreshes/{refresh_id}` | Authenticated |
| POST | `/v1/improvements/refreshes/{refresh_id}/complete` | Authenticated |

### Operator

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/v1/operator/status` | `operator:read` |
| GET | `/v1/operator/config` | `operator:read` |
| GET | `/v1/operator/doctor` | `operator:read` |
| POST | `/v1/operator/reset` | `operator:write` |
| GET | `/v1/operator/tools/summary` | `operator:read` |
| GET | `/v1/operator/sessions` | `operator:read` |
| GET | `/v1/operator/backups` | `operator:read` |
| GET | `/v1/operator/onboarding` | `operator:read` |

### Backups

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/v1/backups` | `operator:read` |
| POST | `/v1/backups` | `operator:write` |
| GET | `/v1/backups/inventory` | `operator:read` |
| GET | `/v1/backups/{backup_id}` | `operator:read` |
| POST | `/v1/backups/{backup_id}/verify` | `operator:read` |
| POST | `/v1/backups/{backup_id}/restore-plan` | `operator:read` |
| POST | `/v1/backups/{backup_id}/restore` | `operator:write` |

Restore execution is gated by request body: `confirm=true` is required, and
`allow_overwrite=true` is additionally required when the restore plan reports
overwrite conflicts.

### Dashboard

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/metrics` | Public |
| GET | `/v1/dashboard/` | Public |
| GET | `/v1/dashboard/metrics` | Public |
| GET | `/v1/dashboard/alerts` | Public |
| GET | `/v1/dashboard/lineage/{workflow_id}` | Public |

### Training

| Method | Path | Scope |
| --- | --- | --- |
| POST | `/v1/training/{agent}/rollout` | Authenticated |
| POST | `/v1/training/{agent}/optimize` | Authenticated |
| GET | `/v1/training/{agent}/rollouts` | Authenticated |
| GET | `/v1/training/{agent}/metrics` | Authenticated |
| POST | `/v1/training/{agent}/revert` | Authenticated |

### Multimodal

| Method | Path | Scope |
| --- | --- | --- |
| POST | `/v1/multimodal/requests` | `multimodal:write` |
| GET | `/v1/multimodal/requests` | `multimodal:read` |
| GET | `/v1/multimodal/requests/{request_id}` | `multimodal:read` |
| POST | `/v1/multimodal/requests/{request_id}/execute` | `multimodal:write` |
| GET | `/v1/multimodal/requests/{request_id}/result` | `multimodal:read` |
| POST | `/v1/multimodal/requests/{request_id}/cancel` | `multimodal:write` |
| POST | `/v1/multimodal/voice/sessions` | `multimodal:write` |
| GET | `/v1/multimodal/voice/sessions` | `multimodal:read` |
| GET | `/v1/multimodal/voice/sessions/{session_id}` | `multimodal:read` |
| GET | `/v1/multimodal/voice/sessions/{session_id}/health` | `multimodal:read` |
| POST | `/v1/multimodal/voice/sessions/{session_id}/stop` | `multimodal:write` |
| POST | `/v1/multimodal/tenants/{tenant_id}/policy` | `multimodal:write` |
| GET | `/v1/voice/health` | Public |

### Outcomes

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/v1/outcomes/health` | Public |
| POST | `/v1/outcomes/events` | `outcomes:write` |
| GET | `/v1/outcomes/events` | `outcomes:read` |
| GET | `/v1/outcomes/trends/{metric_type}` | `outcomes:read` |
| GET | `/v1/outcomes/dashboard` | `outcomes:read` |
| POST | `/v1/outcomes/roi` | `outcomes:read` |
| POST | `/v1/outcomes/launch/evaluate` | `outcomes:read` |
| POST | `/v1/outcomes/launch/guide` | `outcomes:read` |
| GET | `/v1/outcomes/pack-impact` | `outcomes:read` |
| POST | `/v1/outcomes/ppack-v3/assignments` | `outcomes:write` |
| GET | `/v1/outcomes/ppack-v3/assignments/{session_id}` | `outcomes:read` |
| POST | `/v1/outcomes/ppack-v3/report` | `outcomes:write` |
| GET | `/v1/outcomes/ppack-v3/reports/{report_id}` | `outcomes:read` |

### Skills

| Method | Path | Scope |
| --- | --- | --- |
| POST | `/v1/skills/match` | `agents:read` |
| GET | `/v1/skills/match/thresholds` | `agents:read` |
| PUT | `/v1/skills/match/thresholds` | `admin` |
| POST | `/v1/skills/match/diagnostics` | `agents:read` |
| POST | `/v1/skills/match/calibrate` | `admin` |
| POST | `/v1/skills/match/compare` | `admin` |
| POST | `/v1/skills/authoring/drafts` | `agents:write` |
| POST | `/v1/skills/authoring/{name}/promotion` | `agents:write` |
| GET | `/v1/skills/authoring/{name}/lineage` | `agents:read` |

### Phase 24 Ecosystem Inventory

The generated Phase 24 plugin, pack marketplace, installed-pack support, and
workflow marketplace route inventory is recorded in
[`docs/validation/phase-24-route-inventory-2026-05-24.md`](validation/phase-24-route-inventory-2026-05-24.md).
That inventory was generated from `agent33.main.app.routes` and found 81
ecosystem routes:

| Family | Count | Primary scope pattern |
| --- | ---: | --- |
| `/v1/plugins` | 17 | `plugins:read`, `plugins:write`, `admin` |
| `/v1/marketplace` | 21 | `agents:read`, `agents:write`, `admin` |
| `/v1/packs` | 36 | Pack lifecycle/trust/recovery scopes in `routes/packs.py` |
| `/v1/workflow-marketplace` | 7 | `workflows:read`, `workflows:write` |

### Webhooks

| Method | Path | Scope |
| --- | --- | --- |
| POST | `/v1/webhooks/telegram` | Authenticated |
| POST | `/v1/webhooks/discord` | Authenticated |
| POST | `/v1/webhooks/slack` | Authenticated |
| GET | `/v1/webhooks/whatsapp` | Authenticated |
| POST | `/v1/webhooks/whatsapp` | Authenticated |

### Webhook Delivery

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/v1/webhooks/deliveries` | `admin` |
| GET | `/v1/webhooks/deliveries/stats` | `admin` |
| GET | `/v1/webhooks/deliveries/dead-letters` | `admin` |
| GET | `/v1/webhooks/deliveries/{delivery_id}` | `admin` |
| POST | `/v1/webhooks/deliveries/{delivery_id}/retry` | `admin` |
| DELETE | `/v1/webhooks/deliveries/purge` | `admin` |

## 3. Notes

- A route being "Authenticated" without scope checks means middleware auth is required, but endpoint-level role/scope enforcement is not currently added.
- The API key delete route enforces ownership/admin logic in handler code rather than route dependency scope.
