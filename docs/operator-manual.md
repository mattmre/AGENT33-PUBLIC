# AGENT-33 operator manual

This manual is the reference for day-2 operations: starting the engine, watching
agents and workflows, managing API keys and tenants, governing tools, approving
packs, enforcing autonomy budgets, working with review queues, gating releases,
and handling the most common operational tasks.

It assumes you have an AGENT-33 deployment running already. If not, follow
[../INSTALL.md](../INSTALL.md) first.

---

## Starting and stopping the engine

### Docker Compose

```bash
cd engine
docker compose up -d         # start
docker compose ps            # status
docker compose logs -f api   # follow API logs
docker compose restart api   # restart only the API service
docker compose down          # stop, keep volumes
docker compose down -v       # stop and delete volumes (data loss)
```

### Bare metal

```bash
agent33 start \
  --profile production \
  --host 0.0.0.0 \
  --port 8000
```

`agent33 start` exec's into `uvicorn` after applying the profile. For multiple
workers behind a reverse proxy, run multiple `uvicorn` processes; the engine
keeps no in-process global state aside from caches that rehydrate from Postgres
on startup.

### Kubernetes

```bash
kubectl -n agent33 get pods            # what is running
kubectl -n agent33 rollout restart deploy/api
kubectl -n agent33 logs -f deploy/api
kubectl -n agent33 scale deploy/api --replicas=3
```

The base manifests set up an HPA on CPU; you can switch it to a custom metric
(token throughput, request rate) once you have your observability stack wired.

## Health checks

Three endpoints serve different consumers:

| Endpoint        | Audience                  | What it does                                                          |
|-----------------|---------------------------|-----------------------------------------------------------------------|
| `/healthz`      | Liveness probes           | Returns `{"status": "healthy"}` if the process is alive               |
| `/readyz`       | Readiness probes          | 200 if every *required* dependency answers, 503 otherwise             |
| `/health`       | Operators                 | Full snapshot of every probe, including optional integrations         |

For Kubernetes:

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8000
readinessProbe:
  httpGet:
    path: /readyz
    port: 8000
```

`required_services` in `/health` derives from your active configuration. If you
disable Ollama (`EMBEDDING_PROVIDER=jina`, `DEFAULT_MODEL=gpt-4o-mini`), Ollama
drops out of the required set; the engine never marks `degraded` on services it
does not depend on.

## Observing agents and workflows

### Live status from the API

```bash
# Aggregate dashboard payload
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/dashboard/snapshot

# All workflow runs in the in-memory window
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/workflows/runs

# Per-run replay events
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/workflows/runs/$RUN_ID/events
```

For long-running monitoring, point your dashboard at the metrics endpoint
(Prometheus-format exposition is enabled in the `enterprise` profile).

### Streaming events

Two streaming transports are supported on workflow runs:

- **WebSocket**: `ws://host:8000/v1/workflows/runs/$RUN_ID/ws` — bidirectional,
  preferred for tool use.
- **SSE**: `http://host:8000/v1/workflows/runs/$RUN_ID/sse` — fallback for
  environments that block WebSockets.

The transport preference is controlled by `WORKFLOW_TRANSPORT_PREFERRED` (`auto`,
`websocket`, or `sse`).

### Traces

`/v1/traces` returns the structured trace log. Each entry has a failure
taxonomy (`llm_error`, `tool_error`, `validation_error`, `timeout`,
`auth_error`, `budget_exceeded`, etc.) and the upstream/downstream context.
Useful filters:

- `?status=failed` — only failed traces.
- `?category=llm_error` — only LLM-layer failures.
- `?since=<ISO timestamp>` — recent activity.

### Frontend

The control plane's "Operations" tab surfaces:

- Active runs with DAG previews.
- Trace timeline with failure-category coloring.
- Review queue.
- Pack health.
- Effort routing decisions and cost estimates.

## Managing API keys and tenants

### Mint a token

```bash
curl -X POST http://localhost:8000/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<rotated-password>"}'
```

The returned JWT carries the user's scopes and expires after `JWT_EXPIRE_MINUTES`
(default 60). For service accounts, prefer long-lived API keys.

### Create an API key

```bash
curl -X POST http://localhost:8000/v1/auth/api-keys \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "subject": "ci-runner",
    "scopes": ["agents:invoke","workflows:execute"]
  }'
```

You see the secret value **once**. Store it in your secret manager; the engine
only retains a hash.

### Revoke an API key

```bash
curl -X DELETE \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:8000/v1/auth/api-keys/<key_id>
```

Admins can revoke any key; non-admins can only revoke their own.

### Scopes

The scopes the engine recognises:

| Scope                | Allows                                                                 |
|----------------------|------------------------------------------------------------------------|
| `admin`              | Everything; required to manage API keys, run release gates             |
| `agents:read`        | List and inspect agents                                                |
| `agents:write`       | Register, update, deactivate agents                                    |
| `agents:invoke`      | Run agent invocations                                                  |
| `workflows:read`     | List, inspect, fetch runs                                              |
| `workflows:write`    | Register and edit workflow definitions                                 |
| `workflows:execute`  | Submit workflow runs and manage schedules                              |
| `tools:execute`      | Call tools directly (rarely needed; usually flows through agents)      |

Following least-privilege: give CI a token with `agents:invoke` +
`workflows:execute` and nothing else.

### Tenants

Every API request is tenant-scoped. Tenant ID is derived from the authenticated
principal (`tenant_id` field on the user record) or from the explicit
`X-Tenant-ID` header on admin tokens. Data segregation:

- Workflow runs include `tenant_id` and are filtered by it.
- Packs are installed per tenant.
- Rate limits are per-tenant.
- Outcomes and trace events are tagged with `tenant_id`.

To create a new tenant in practice, create a new user under that tenant and
hand the owner an API key. The `tenant_id` field is just a string; there is no
separate "tenant" object to create.

## Tool governance

Tools are the deterministic capabilities AGENT-33 agents can call (shell,
file_ops, web_fetch, browser, jupyter, code_interpreter, MCP-exposed tools,
custom). Three policy levers control them.

### Tool use mode

`TOOL_USE_MODE` global setting:

| Mode        | Behavior                                                                     |
|-------------|------------------------------------------------------------------------------|
| `audit`     | Default. Tools execute, results are logged.                                  |
| `dry-run`   | Tools are introspected but never executed. Returns a synthetic preview.     |
| `approved`  | Tools execute only if their call carries a valid approval token.            |

Switching modes is hot — the change applies on the next request.

### Tool catalog and approvals

```bash
# What tools are available
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/tool-catalog

# Approve a tool by name (writes to ~/.agent33/approved-tools.json)
agent33 tools approve shell --reason "trusted operator only"

# Search the catalog
agent33 tools search "browse a website"
```

The `~/.agent33/approved-tools.json` file is loaded at startup; deletions also
require an engine restart.

### Risk tiers and approval tokens

When `TOOL_USE_MODE=approved` (or when a tool is marked
`approval_required`), AGENT-33 will refuse to run it without an approval token.
Mint one from the API:

```bash
curl -X POST http://localhost:8000/v1/tool-approvals \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_id": "shell",
    "risk_tier": "high",
    "ttl_seconds": 300,
    "one_time": true
  }'
```

Pass the returned `token` in the `X-Approval-Token` header on the next request.
Default TTL is 5 minutes; default one-time use (configurable per token).

## Pack approval

Packs are installable bundles. The default trust posture treats them as
untrusted until approved.

```bash
# List installed packs
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/packs

# Inspect detail
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/packs/<pack_name>

# Validate a local pack before applying
agent33 packs validate ./my-pack/

# Install from a registry
agent33 packs install acme/observability-pack --version 1.2.0

# Trust a pack signer
curl -X POST http://localhost:8000/v1/packs/<pack_name>/trust \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"trusted": true, "reason": "signed by Acme release key"}'
```

Pack curation is enabled with `PACK_CURATION_ENABLED=true`, which gates the
public catalog behind a quality threshold (`PACK_MIN_QUALITY_SCORE`) and an
explicit human review per listing.

For pack provenance and signing, see
[default-policy-packs.md](default-policy-packs.md) and
[operators/security-audit-checklist.md](operators/security-audit-checklist.md).

## Autonomy budgets

Autonomy budgets are per-task limits that the runtime enforces before a tool
call executes. They have a state machine: `DRAFT → PENDING_APPROVAL → ACTIVE →
COMPLETED` (with `SUSPENDED` and `REJECTED` side states).

### Create a budget

```bash
curl -X POST http://localhost:8000/v1/autonomy/budgets \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "incident-2026-001",
    "agent_id": "code-worker",
    "in_scope": ["src/services/email/**", "tests/services/email/**"],
    "out_of_scope": ["src/services/billing/**"],
    "default_escalation_target": "platform-team"
  }'
```

### Run preflight, activate, run

```bash
BUDGET=$(curl -s -X POST ... | jq -r .budget_id)

# What would this budget allow?
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/autonomy/budgets/$BUDGET/preflight

# Move it from DRAFT to ACTIVE
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/autonomy/budgets/$BUDGET/activate

# Create the runtime enforcer
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/autonomy/budgets/$BUDGET/enforcer

# Now invocations with this budget_id check every action against the budget
```

### Default autonomy levels

`AUTONOMY_DEFAULT_LEVEL` sets the default tier (0=supervised, 1=read-auto, 2=
auto-no-destructive, 3=full). Per-tenant overrides are honored on the request
header `X-Autonomy-Level`.

## Review queues

Risky actions can be sent to a human review queue rather than executed
immediately. The reviewer assigns approval or rejection; on approval, the
original request resumes.

```bash
# What is waiting for review
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/reviews/queue

# Detail
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/reviews/<review_id>

# Approve
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/reviews/<review_id>/approve \
  -d '{"reviewer":"alice","reason":"low risk, clear evidence"}'

# Reject
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/reviews/<review_id>/reject \
  -d '{"reviewer":"alice","reason":"changes scope"}'
```

Reviewer assignment can be automated by tenant or by risk category; see
[operators/operator-verification-runbook.md](operators/operator-verification-runbook.md).

## Release gates

The release subsystem manages a lifecycle (`PLANNED → FROZEN → RC → VALIDATING
→ RELEASED → ROLLED_BACK`) over groups of artifacts. Each transition can be
gated by:

- **Evaluation regressions** — `evaluations` must show no metric regression
  beyond a threshold.
- **Outcomes data** — at least N successful runs in the canary window.
- **Pre-release checklist** — eight items (`RL-01` to `RL-08`).

```bash
# Plan a release
curl -X POST http://localhost:8000/v1/releases \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name":"2026.05","artifacts":["pack/observability","workflow/incident"]}'

# Run the checklist
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/releases/<id>/checklist

# Transition states
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v1/releases/<id>/transition \
  -d '{"to_state":"RC"}'
```

The rollback manager records both the artifact state and the conditions that
triggered the rollback; on rollback, packs revert from the rollback archive in
`var/pack-rollback-archive/`.

## Day-2 task index

Common operational tasks and where they live:

| Task                                              | Document or command                                         |
|---------------------------------------------------|-------------------------------------------------------------|
| Add a tenant                                      | Create user/API key with `tenant_id`                        |
| Rotate JWT secret                                 | [runbooks/secret-rotation.md](runbooks/secret-rotation.md)  |
| Snapshot Postgres                                 | `docker exec postgres pg_dump -U agent33 agent33 > snap.sql`|
| Restore Postgres                                  | Standard `psql` restore; see upgrade-guide                  |
| Add a custom tool                                 | Drop `tool-definitions/<name>.yml`, restart                 |
| Install a community pack                          | `agent33 packs install <name>`                              |
| Disable a misbehaving pack                        | `curl -X POST .../v1/packs/<n>/disable`                     |
| Inspect ingestion failures                        | `var/ingestion_journal.db`, `/v1/ingestion/runs?status=failed` |
| Find a missing skill                              | `agent33 skills search <query>`                             |
| Tail traces in real time                          | `curl -N http://localhost:8000/v1/traces/stream`            |
| Snapshot configuration                            | `agent33 diagnose --json > config-snapshot.json`            |
| Reset rate limits                                 | `docker compose restart redis` (last resort)                |
| Migrate database                                  | `alembic upgrade head`                                      |

## Capacity guidance

The reference numbers from the bundled Compose stack on a 4-core / 8-GB host:

- **Sustained agent invocations**: ~5–10/s with a small local model (limited by
  Ollama). Cloud LLM throughput depends on your provider quota.
- **Workflow runs in flight**: tested to ~250 concurrent; bottlenecks above are
  Postgres connection pool and Redis throughput, not the engine.
- **Tool calls per minute per tenant**: capped by `RATE_LIMIT_PER_MINUTE`
  (default 60) plus `RATE_LIMIT_BURST` (default 10).
- **Postgres connections**: `DB_POOL_SIZE=10` + `DB_MAX_OVERFLOW=20` is enough
  for a single replica; multiply by replica count.

For high-throughput deployments see
[operators/horizontal-scaling-architecture.md](operators/horizontal-scaling-architecture.md).

## When in doubt

The reliable diagnostic command for any operational issue is:

```bash
agent33 diagnose --json
```

It probes Python version, environment, disk, ports, Ollama, the LLM provider,
Postgres, Redis, and NATS, then prints a structured report. With `--fix` it
will auto-repair safe issues (mostly missing directories and placeholder secret
warnings in lite mode).

If diagnose reports green and you still have a problem, walk
[troubleshooting.md](troubleshooting.md) end to end. If a specific failure
category hits you frequently, capture the trace ID
(`X-Trace-ID` response header) and open an issue against
[the public repository](https://github.com/mattmre/AGENT33-PUBLIC/issues).
