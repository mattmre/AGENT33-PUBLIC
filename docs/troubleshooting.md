# Troubleshooting

When something goes sideways in AGENT-33, the answer is almost always in one of
four places: `/health`, container logs, `/v1/traces`, or `var/`. This page
indexes the failures you are most likely to see and points at the fix.

The first thing to run, every time, is:

```bash
agent33 diagnose
```

It probes every subsystem and reports concrete remediations. The output is
also a useful artifact to attach to bug reports.

## Quick diagnostic commands

```bash
# Engine reachable?
curl http://localhost:8000/healthz

# All dependencies healthy?
curl http://localhost:8000/health | jq

# Per-channel messaging health
curl http://localhost:8000/health/channels | jq

# What is in the trace log?
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/v1/traces | jq

# Container-level view (Docker)
docker compose ps
docker compose logs --tail 200 api

# Local process logs (bare metal)
journalctl -u agent33 -n 200 --no-pager
```

## Common failures and fixes

### `/health` reports `degraded` for Postgres

Symptoms: `agent33 status` shows `"database": "unavailable"` or queries 503.

Causes and fixes:

1. **Container not ready.** Postgres can take 20-30s on first boot. Wait and
   re-check, or watch `docker compose logs postgres`.
2. **`pgvector` extension missing.** Required for embeddings. Run:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
3. **Credentials mismatch.** Verify `DATABASE_URL` (or
   `POSTGRES_USER/PASSWORD/DB`) match what the Postgres image was created
   with. Recreating the engine container without recreating the database
   leaves stale credentials.
4. **Schema drift.** Run `alembic upgrade head` from `engine/`.

### `/health` reports `degraded` for Redis or NATS

Symptoms: rate-limit data not persisting, messaging adapters offline.

Fixes:

- `docker compose logs redis nats` — check for OOM or auth issues.
- Confirm `REDIS_URL` and `NATS_URL` resolve from the API container's
  network namespace (not localhost on the host).
- For NATS JetStream, the storage path needs to be writable; check the
  volume mount.

### Agent invocations return 503 from the LLM router

Symptoms: `POST /v1/agents/{name}/invoke` returns
`{ "detail": "No model available" }`.

Fixes:

1. **Ollama not running.** Start it (`ollama serve` on the host), then pull
   a model: `ollama pull llama3.2:3b`. Set `OLLAMA_DEFAULT_MODEL=llama3.2:3b`
   in `.env`.
2. **Ollama on the wrong host.** Inside Docker, set `OLLAMA_BASE_URL` to
   `http://host.docker.internal:11434` (Mac/Windows) or use the gateway IP on
   Linux.
3. **Cloud provider misconfigured.** Set `OPENAI_API_KEY` (or
   `OPENROUTER_API_KEY`) and `DEFAULT_MODEL` to a model the provider supports.
4. **Effort routing has no tier model.** If `AGENT_EFFORT_ROUTING_ENABLED=true`
   but `AGENT_EFFORT_LOW_MODEL`/`MEDIUM`/`HIGH` are unset, the router cannot
   pick a model.

### `401 Unauthorized` on every request

You forgot the bearer token, or the JWT has expired.

```bash
# Re-issue
TOKEN=$(curl -sX POST http://localhost:8000/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | jq -r .access_token)
```

If you changed `JWT_SECRET`, all previously issued JWTs are invalidated. API
keys remain valid across JWT secret rotations.

### `403 Forbidden` with a token

Your token lacks the required scope. Inspect the route's docstring at
`/docs` to see what it needs. Mint a new API key with the right scopes:

```bash
curl -sX POST http://localhost:8000/v1/auth/api-keys \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"subject":"ci","scopes":["agents:invoke","workflows:execute"]}'
```

### `429 Too Many Requests`

You hit the per-tenant rate limit. The response carries `Retry-After` and the
`X-RateLimit-*` headers.

To raise the limit globally, adjust:

```bash
RATE_LIMIT_REQUESTS_PER_MINUTE=120
RATE_LIMIT_BURST=20
```

To inspect or override per-tenant limits, use `/v1/admin/rate-limits/`.

### Engine refuses to start in production mode

Symptoms: process exits immediately with a config error.

Causes (read the stderr line; the validator names the offending field):

- `JWT_SECRET` is at the default ("change-me-in-production" or empty).
- `AUTH_BOOTSTRAP_ADMIN_PASSWORD` is at the default ("admin").
- `API_SECRET_KEY` is missing.
- Database credentials are the default `postgres/postgres`.

Fix by generating fresh values:

```bash
JWT_SECRET=$(openssl rand -base64 48)
API_SECRET_KEY=$(openssl rand -base64 48)
AUTH_BOOTSTRAP_ADMIN_PASSWORD=$(openssl rand -base64 24)
```

Or run `agent33 bootstrap --output engine/.env.local`.

### Frontend cannot reach the API from the browser

Symptoms: control plane loads but every request fails with a CORS error.

Fix: set `CORS_ALLOWED_ORIGINS` to include the frontend origin:

```bash
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

In production, list the exact public origin(s); never use `*` with credentials.

### Frontend builds with the wrong API URL

Symptoms: frontend talks to `http://localhost:8000` even in production.

The API URL is baked into the frontend at build time. Set
`FRONTEND_API_BASE_URL` (or `VITE_API_BASE_URL` in `frontend/.env`) and
rebuild:

```bash
docker compose build frontend
docker compose up -d frontend
```

### Workflow runs hang or never complete

1. **Check the DAG with live status:**
   `GET /v1/workflows/runs/{run_id}/dag`.
2. **Look for a step in `running` state with no events** — likely waiting on
   a tool call or LLM that hung. Check the trace at
   `/v1/traces?run_id=<id>`.
3. **A required human review is open.** Check `/v1/reviews/queue`.
4. **An autonomy budget blocked the step.** Look at
   `/v1/autonomy/budgets/{id}/events`.

To force-cancel a run, terminate it from the UI or use the run-ledger
endpoint.

### Tools refuse to run with `disallowed_tool`

Symptoms: agent log shows `Tool 'X' is not in the allowlist`.

Fixes:

- Approve the tool: `agent33 tools approve <name>`.
- Or set `TOOL_USE_MODE=audit` to log without blocking, while you decide.
- Or extend the allowlist via the tool catalogue: `POST /v1/catalog/...`.

For autonomy-budget restrictions, edit the budget's scope or extend it.

### Packs fail integrity checks during install

Symptoms: `POST /v1/packs/install` returns `sha256 mismatch`.

The pack content does not match the SHA-256 in the registry entry. Either
the registry is stale or the artifact was modified. Re-fetch and re-publish;
do not bypass the check.

To check whether a pack has been revoked:

```bash
agent33 packs revocation-status <name>
```

### Memory and embeddings: empty or slow searches

1. **Embedding provider degraded.** Check `/health` for the embedding key.
2. **BM25 not warmed up.** First search after restart can be slow.
3. **No content yet.** Run a few workflows to populate memory, or load
   documents via `POST /v1/ingestion/...`.

### Browser sessions fail to start

Symptoms: browser-agent invocations return `browser unavailable`.

- Confirm Playwright is installed in the engine container; the Docker image
  ships with it.
- Set `BROWSER_HEADLESS=true` if you have no display server.
- Check `/v1/browser/sessions` for orphaned sessions; clear stuck ones.

### Voice features do not transcribe or speak

- `VOICE_DAEMON_ENABLED=true` is required.
- ElevenLabs and LiveKit each need their own key/secret pair.
- See [operators/voice-daemon-runbook.md](operators/voice-daemon-runbook.md).

### Disk fills up

Likely culprits in `var/`:

- `var/workflow-runs/` — replay archive. Configure retention via
  `REPLAY_RETENTION_DAYS`.
- `var/ingestion.db` and `_journal.db` — bounded by
  `INGESTION_RETENTION_*`.
- `var/pack-rollback-archive/` — purged when packs are uninstalled, but
  large packs leave large archives.

Free space with `agent33 diagnose --fix`, or manually prune the directories
listed above.

### Docker Compose: services keep restarting

```bash
docker compose ps
docker compose logs --tail 200 <service>
```

The most common causes:

- **OOM kill.** Check `docker stats`. Raise the container memory limit.
- **Failed healthcheck.** The healthcheck command itself may be broken; run
  it manually inside the container.
- **Missing environment.** A required variable is unset in `.env`.

### Kubernetes: pod stuck in `CrashLoopBackOff`

```bash
kubectl logs -n agent33 deploy/api --tail 200
kubectl describe pod -n agent33 -l app=api
```

Frequent root causes:

- Secret not mounted (`JWT_SECRET`, `DATABASE_URL`).
- PersistentVolumeClaim not bound; the engine writes to `var/`.
- Wrong image tag; the deployment refers to a tag that does not exist.

## Where to look when in doubt

| Symptom | Look here |
|---------|-----------|
| Process is up but doing nothing | `docker compose logs api`, `/v1/traces` |
| Specific run failed | `/v1/workflows/runs/{id}` and `/events` |
| Auth or rate-limit problem | `/v1/admin/rate-limits/`, `/v1/auth/api-keys` |
| Tool refused | `/v1/approvals/tools`, `/v1/catalog/...` |
| Pack misbehaving | `/v1/packs/{name}/audit`, `/v1/packs/health` |
| LLM model errors | `/v1/model-health` |
| Filesystem filling up | `var/`, `agent33 diagnose --fix` |
| Replay missing | `var/workflow-runs/<run_id>/` |

## Filing a bug report

Include:

1. Output of `agent33 diagnose --json`.
2. The last 200 lines of `docker compose logs api`.
3. The minimal failing request (curl command + response).
4. The `run_id` if it is workflow-related.
5. The git SHA the engine was built from (`/health` includes it).

Open the issue at the project's GitHub repo. Redact secrets and tenant IDs
before posting.

## See also

- [operator-manual.md](operator-manual.md) — day-2 reference.
- [configuration.md](configuration.md) — env var reference.
- [operators/incident-response-playbooks.md](operators/incident-response-playbooks.md) — incident playbooks.
- [runbooks/secret-rotation.md](runbooks/secret-rotation.md) — rotate secrets safely.
