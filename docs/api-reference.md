# API reference

AGENT-33 exposes a versioned REST API at `http://<host>:8000`, prefixed with
`/v1`. Authentication is via bearer token (JWT or API key) carried in the
`Authorization` header, and every route enforces an explicit scope.

This document is an operator's index of the endpoints you will actually call.
For the complete, always-fresh surface (every route, every parameter, every
response model), open the auto-generated Swagger UI:

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`

If you need to feed the spec into another tool (Postman, a code generator),
download `/openapi.json` and use that.

## Authentication

All routes except `/health`, `/healthz`, `/readyz`, and `/v1/auth/token`
require a bearer token. Two token types are accepted, both passed the same
way:

```http
Authorization: Bearer <token>
```

| Type | Issued via | Use for |
|------|-----------|---------|
| JWT  | `POST /v1/auth/token` | Short-lived sessions, UI logins |
| API key | `POST /v1/auth/api-keys` | Long-lived scripted access |

JWTs expire (default 1 hour, configurable via `JWT_EXPIRATION_MINUTES`). API
keys do not expire until revoked.

### Scopes

Every protected route requires one or more scopes. Tokens carry a list; if any
required scope is missing the response is `403 Forbidden`.

| Scope | Permits |
|-------|---------|
| `admin` | Everything; admin-only operations |
| `agents:read` | List, fetch, and search agents and packs |
| `agents:write` | Create, update, delete agents and packs |
| `agents:invoke` | Invoke an agent |
| `workflows:read` | List, fetch, inspect workflows and runs |
| `workflows:write` | Create or modify workflows |
| `workflows:execute` | Trigger workflow execution |
| `tools:execute` | Execute tools and record traces |

The bootstrap admin holds all scopes. API keys you create receive a subset
that you specify.

## Auth (`/v1/auth`)

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| POST   | `/v1/auth/token` | none | Exchange `{username,password}` for a JWT |
| POST   | `/v1/auth/api-keys` | `admin` | Create a long-lived API key |
| DELETE | `/v1/auth/api-keys/{key_id}` | `admin` | Revoke an API key |

Example — mint a JWT:

```bash
curl -sX POST http://localhost:8000/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}'
```

Response:

```json
{ "access_token": "eyJ...", "token_type": "bearer" }
```

Example — create an API key:

```bash
curl -sX POST http://localhost:8000/v1/auth/api-keys \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "subject":"ci-runner",
    "scopes":["agents:invoke","workflows:execute"]
  }'
```

The `key` field in the response is only shown once. Save it.

## Health (`/health`, `/healthz`, `/readyz`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET    | `/health` | none | Full dependency probe (Postgres, Redis, NATS, LLM, etc.) |
| GET    | `/healthz` | none | Liveness only — used for load balancer probes |
| GET    | `/readyz` | none | Readiness for traffic |
| GET    | `/health/channels` | none | Per-messaging-channel health |

Use `/healthz` from load balancers; it does not exercise downstream
services. Use `/health` from monitoring; the response body identifies which
subsystem is degraded.

## Agents (`/v1/agents`)

The agent registry.

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET    | `/v1/agents/` | `agents:read` | List all agents |
| GET    | `/v1/agents/{name}` | `agents:read` | Fetch one agent |
| POST   | `/v1/agents/` | `agents:write` | Register an agent definition |
| PUT    | `/v1/agents/{name}` | `agents:write` | Update an agent definition |
| DELETE | `/v1/agents/{name}` | `agents:write` | Remove an agent |
| GET    | `/v1/agents/search` | `agents:read` | Search by capability |
| GET    | `/v1/agents/capabilities/catalog` | none | Capability taxonomy |
| POST   | `/v1/agents/validate` | none | Validate a definition without saving |
| POST   | `/v1/agents/preview-prompt` | `agents:read` | Preview the rendered prompt |
| POST   | `/v1/agents/{name}/invoke` | `agents:invoke` | Single-turn invocation |
| POST   | `/v1/agents/{name}/invoke-iterative` | `agents:invoke` | Multi-turn tool loop |
| POST   | `/v1/agents/{name}/invoke-iterative/stream` | `agents:invoke` | SSE stream |
| GET    | `/v1/agents/by-id/{agent_id}` | `agents:read` | Fetch by stable ID |
| GET    | `/v1/agents/profiling/{agent_name}` | `agents:read` | Profile data |
| GET    | `/v1/agents/tool-loop/scores` | `agents:read` | Tool-loop quality scores |

Example — invoke an agent:

```bash
curl -sX POST http://localhost:8000/v1/agents/researcher/invoke \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"inputs":{"query":"Summarize attention mechanisms","depth":"brief"}}'
```

Example — stream an iterative invocation (SSE):

```bash
curl -N -sX POST http://localhost:8000/v1/agents/code-worker/invoke-iterative/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"inputs":{"task":"refactor this function"}}'
```

## Workflows (`/v1/workflows`)

DAG workflow registry and runs.

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET    | `/v1/workflows/` | `workflows:read` | List workflows |
| POST   | `/v1/workflows/` | `workflows:write` | Register a workflow |
| GET    | `/v1/workflows/{name}` | `workflows:read` | Fetch one workflow |
| GET    | `/v1/workflows/{name}/dag` | `workflows:read` | Static DAG layout |
| POST   | `/v1/workflows/{name}/execute` | `workflows:execute` | Start a run |
| POST   | `/v1/workflows/{name}/schedule` | `workflows:execute` | Schedule recurring |
| GET    | `/v1/workflows/{name}/history` | `workflows:read` | Recent runs |
| GET    | `/v1/workflows/schedules` | `workflows:read` | List schedules |
| DELETE | `/v1/workflows/schedules/{job_id}` | `workflows:execute` | Cancel schedule |
| GET    | `/v1/workflows/runs/{run_id}` | `workflows:read` | Run metadata |
| GET    | `/v1/workflows/runs/{run_id}/dag` | `workflows:read` | DAG with live status |
| GET    | `/v1/workflows/runs/{run_id}/events` | `workflows:read` | Step events |
| GET    | `/v1/workflows/runs/{run_id}/artifacts` | `workflows:read` | Artifacts |
| POST   | `/v1/workflows/{run_id}/resume` | `workflows:execute` | Resume from checkpoint |

Example — execute:

```bash
curl -sX POST http://localhost:8000/v1/workflows/research-assistant/execute \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"inputs":{"topic":"hybrid retrieval","depth":"standard"}}'
```

Companion routes:

- `GET /v1/workflows/templates/...` — built-in templates index.
- `GET /v1/workflow-marketplace/...` — community marketplace search.
- `WS /v1/workflows/runs/{run_id}/ws` — live event stream (websocket).
- `GET /v1/workflows/runs/{run_id}/stream` — SSE event stream.

## Reviews (`/v1/reviews`)

Two-layer review queue.

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| POST   | `/v1/reviews/` | `workflows:write` | Open a review |
| GET    | `/v1/reviews/` | `workflows:read` | List reviews |
| GET    | `/v1/reviews/{id}` | `workflows:read` | One review |
| DELETE | `/v1/reviews/{id}` | `workflows:write` | Withdraw |
| POST   | `/v1/reviews/{id}/assess` | `workflows:write` | Submit risk assessment |
| POST   | `/v1/reviews/{id}/assign-l1` | `workflows:write` | Assign L1 reviewer |
| POST   | `/v1/reviews/{id}/l1` | `workflows:write` | L1 verdict |
| POST   | `/v1/reviews/{id}/assign-l2` | `workflows:write` | Assign L2 reviewer |
| POST   | `/v1/reviews/{id}/l2` | `workflows:write` | L2 verdict |
| POST   | `/v1/reviews/{id}/approve` | `workflows:write` | Final approval |
| POST   | `/v1/reviews/{id}/merge` | `workflows:write` | Merge into mainline |

## Autonomy (`/v1/autonomy`)

Autonomy budgets and stop conditions.

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| POST   | `/v1/autonomy/budgets` | `workflows:write` | Create a budget |
| GET    | `/v1/autonomy/budgets` | `workflows:read` | List active budgets |
| GET    | `/v1/autonomy/budgets/{id}` | `workflows:read` | One budget |
| DELETE | `/v1/autonomy/budgets/{id}` | `workflows:write` | Cancel budget |
| POST   | `/v1/autonomy/budgets/{id}/approve` | `admin` | Approve a draft |
| POST   | `/v1/autonomy/budgets/{id}/activate` | `admin` | Activate |
| POST   | `/v1/autonomy/budgets/{id}/complete` | `workflows:write` | Mark complete |
| POST   | `/v1/autonomy/budgets/{id}/extend` | `workflows:write` | Extend |
| POST   | `/v1/autonomy/budgets/{id}/escalate` | `workflows:write` | Escalate |
| POST   | `/v1/autonomy/preflight` | `workflows:execute` | Preflight check |

The budget state machine is `DRAFT → PENDING_APPROVAL → ACTIVE → COMPLETED`
(or `EXPIRED`/`CANCELED` from any of the first three states).

## Packs (`/v1/packs`)

Pack lifecycle, registry, and trust.

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET    | `/v1/packs` | `agents:read` | List installed |
| GET    | `/v1/packs/{name}` | `agents:read` | Detail |
| POST   | `/v1/packs/install` | `agents:write` | Install |
| POST   | `/v1/packs/{name}/upgrade` | `agents:write` | Upgrade |
| DELETE | `/v1/packs/{name}` | `agents:write` | Uninstall |
| POST   | `/v1/packs/{name}/enable` | `agents:write` | Enable tenant-wide |
| POST   | `/v1/packs/{name}/disable` | `agents:write` | Disable |
| POST   | `/v1/packs/{name}/enable-session` | `agents:write` | Session overlay |
| POST   | `/v1/packs/{name}/disable-session` | `agents:write` | Remove overlay |
| GET    | `/v1/packs/{name}/dry-run` | `agents:read` | Preview effects |
| GET    | `/v1/packs/health` | `agents:read` | Per-pack health |
| GET    | `/v1/packs/audit` | `agents:read` | Audit log |
| GET    | `/v1/packs/trust/overview` | `agents:read` | Signing posture |
| POST   | `/v1/packs/trust/verify-all` | `admin` | Re-verify signatures |
| GET    | `/v1/packs/hub/search` | `agents:read` | Search registry |
| GET    | `/v1/packs/hub/entry/{name}` | `agents:read` | Registry entry |
| GET    | `/v1/packs/hub/revocation/{name}` | `agents:read` | Revocation status |

## Traces (`/v1/traces`)

Tool-call and agent traces with failure taxonomy.

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| POST   | `/v1/traces/` | `tools:execute` | Create a trace |
| GET    | `/v1/traces/` | `workflows:read` | List traces |
| GET    | `/v1/traces/{id}` | `workflows:read` | One trace |
| POST   | `/v1/traces/{id}/actions` | `tools:execute` | Append an action |
| POST   | `/v1/traces/{id}/complete` | `tools:execute` | Finalize |

## Evaluations (`/v1/evaluations`)

Golden tasks, gates, regressions.

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| POST   | `/v1/evaluations/runs` | `workflows:execute` | Start a run |
| GET    | `/v1/evaluations/runs/{id}` | `workflows:read` | Run detail |
| GET    | `/v1/evaluations/golden-tasks` | `workflows:read` | List tasks |
| GET    | `/v1/evaluations/gates` | `workflows:read` | Gate definitions |
| POST   | `/v1/evaluations/gates/check` | `workflows:execute` | Run gates |
| GET    | `/v1/evaluations/regressions` | `workflows:read` | Regression history |
| GET    | `/v1/evaluations/schedules` | `workflows:read` | Scheduled gates |

## Releases (`/v1/releases`)

Release lifecycle.

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET    | `/v1/releases` | `workflows:read` | List releases |
| POST   | `/v1/releases` | `admin` | Plan a release |
| POST   | `/v1/releases/{id}/freeze` | `admin` | Freeze |
| POST   | `/v1/releases/{id}/rc` | `admin` | Promote to RC |
| POST   | `/v1/releases/{id}/validate` | `admin` | Validate |
| POST   | `/v1/releases/{id}/release` | `admin` | Release |
| POST   | `/v1/releases/{id}/rollback` | `admin` | Roll back |

State machine: `PLANNED → FROZEN → RC → VALIDATING → RELEASED → ROLLED_BACK`.

## Discovery (`/v1/discovery`)

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET    | `/v1/discovery/tools` | `agents:read` | Search tools |
| GET    | `/v1/discovery/skills` | `agents:read` | Search skills |
| GET    | `/v1/discovery/capabilities` | `agents:read` | Capability map |

## Dashboard and observability

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET    | `/v1/dashboard/snapshot` | `workflows:read` | Aggregate UI snapshot |
| GET    | `/v1/dashboard/prometheus` | none | Prometheus metrics |
| GET    | `/v1/insights/...` | `workflows:read` | Outcomes/ROI |
| GET    | `/v1/outcomes/...` | `workflows:read` | Impact tracking |
| GET    | `/v1/model-health` | `workflows:read` | LLM provider health |
| GET    | `/v1/operations/...` | `workflows:read` | Ops hub |
| GET    | `/v1/operator/...` | `workflows:read` | Operator sessions |

## Chat and conversational surfaces

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| POST   | `/v1/chat` | `agents:invoke` | Slash-routed chat |
| GET    | `/v1/sessions` | `workflows:read` | List sessions |
| GET    | `/v1/sessions/{id}` | `workflows:read` | Session detail |
| GET    | `/v1/context/{id}` | `workflows:read` | Context window |

## Provider/admin routes

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET    | `/v1/ollama/...` | `admin` | Ollama proxy and stats |
| GET    | `/v1/openrouter/...` | `admin` | OpenRouter status |
| GET    | `/v1/lm-studio/...` | `admin` | LM Studio status |
| `*`    | `/v1/admin/rate-limits/...` | `admin` | Rate-limit management |
| GET    | `/v1/config/...` | `admin` | Active config view |
| GET    | `/v1/migrations/...` | `admin` | Schema migration status |

## MCP (`/v1/mcp`)

Model Context Protocol surface for inbound and outbound MCP integrations.

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| POST   | `/v1/mcp/...` | varies | MCP server endpoints |
| GET    | `/v1/mcp/proxy/...` | `agents:read` | Outbound proxy status |
| POST   | `/v1/mcp/sync/...` | `agents:write` | Sync skills/tools from MCP |

## Tools and tool catalogue

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET    | `/v1/catalog/...` | `agents:read` | Tool catalogue browsing |
| GET    | `/v1/tools/gateway/...` | `tools:execute` | Tool gateway proxy |
| POST   | `/v1/tools/mutations/...` | `tools:execute` | Pre/post mutations |
| GET    | `/v1/approvals/tools` | `admin` | Pending tool approvals |
| POST   | `/v1/approvals/tools` | `admin` | Approve a tool |

## Other domain routers

| Prefix | Purpose |
|--------|---------|
| `/v1/backups` | Snapshot create/restore |
| `/v1/benchmarks` | SkillsBench results |
| `/v1/browser` | Browser sessions |
| `/v1/capability-packs` | Capability pack management |
| `/v1/checkpoints` | Workflow checkpoints |
| `/v1/commands` | Command palette / CLI mirror |
| `/v1/comparative` | A/B comparative scoring |
| `/v1/compatibility` | Version compatibility checks |
| `/v1/completion-gates` | Completion gates |
| `/v1/component-security` | Component security scans |
| `/v1/connectors` | External connector boundary |
| `/v1/cron` | Cron-style jobs |
| `/v1/delegation` | Inter-agent delegation |
| `/v1/doctor` | In-engine diagnostics |
| `/v1/embeddings` | Embedding swap and rerank |
| `/v1/execution` | Code execution sandboxes |
| `/v1/explanations` | Run/decision explanations |
| `/v1/hooks` | Pre/post hooks |
| `/v1/improvements` | Continuous improvement queue |
| `/v1/ingestion` | Knowledge ingestion |
| `/v1/knowledge` | Knowledge base / RAG |
| `/v1/marketplace` | Skill/pack marketplace |
| `/v1/memory` | Memory search |
| `/v1/moa` | Mixture-of-agents |
| `/v1/multimodal` | Multimodal endpoints (voice/image) |
| `/v1/p69b` | Paused invocations |
| `/v1/planning` | Planning service |
| `/v1/plugins` | Plugin management |
| `/v1/policy` | Policy decisions |
| `/v1/processes` | Process registry |
| `/v1/provenance` | Provenance chain |
| `/v1/rag` | RAG pipeline |
| `/v1/reasoning` | Reasoning steps |
| `/v1/research` | Research intake |
| `/v1/resources` | Resource limits |
| `/v1/run-ledger` | Run ledger |
| `/v1/sandboxing` | Sandbox configuration |
| `/v1/skills` | Skill matching |
| `/v1/skills/authoring` | Skill authoring |
| `/v1/spawner` | Sub-agent spawner |
| `/v1/support` | Support bundles |
| `/v1/synthetic-envs` | Synthetic test environments |
| `/v1/training` | Online training |
| `/v1/visualizations` | Visualization data |
| `/v1/web-research` | Web-research adapter |
| `/v1/webhooks` | Inbound webhooks |
| `/v1/webhooks/deliveries` | Delivery status |

## Error format

All errors follow FastAPI's default envelope:

```json
{ "detail": "explanation here" }
```

| Status | Meaning |
|--------|---------|
| `400` | Bad request — JSON schema or value error |
| `401` | Missing or invalid bearer token |
| `403` | Token missing the required scope |
| `404` | Resource not found |
| `409` | State-machine conflict (e.g., budget already ACTIVE) |
| `422` | Pydantic validation failure with field-level detail |
| `429` | Rate limit exceeded |
| `500` | Internal error — check `/v1/traces` |
| `503` | A dependency (LLM, DB) is unavailable |

`429` responses include `Retry-After` and the relevant rate-limit headers
(`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`).

## Pagination

Listing endpoints accept the conventional `limit` and `offset` query
parameters. The default `limit` is endpoint-specific (commonly 50, capped at
500). Cursor pagination is used on the high-volume endpoints (traces,
events); follow the `next` link in the response when present.

## Versioning

All routes are prefixed with `/v1`. Future breaking changes will ship under
`/v2`; `/v1` will continue to be served alongside it for at least one minor
release cycle. The accept header is not used for versioning.

## See also

- [cli-reference.md](cli-reference.md) — the CLI built on top of these routes.
- [configuration.md](configuration.md) — env vars that affect API behavior.
- [operator-manual.md](operator-manual.md) — how operators use these endpoints in practice.
- [troubleshooting.md](troubleshooting.md) — common HTTP errors and fixes.
