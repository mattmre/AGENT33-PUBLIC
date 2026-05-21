# Production Deployment Runbook

## Purpose

Operate the current AGENT-33 Kubernetes deployment baseline safely for
single-instance production rollouts.

This runbook is scoped to the repo-owned deployment assets already shipped on
`main`:

- [`deploy/k8s/base/README.md`](../../deploy/k8s/base/README.md)
- [`deploy/k8s/overlays/production/README.md`](../../deploy/k8s/overlays/production/README.md)
- [`deploy/monitoring/README.md`](../../deploy/monitoring/README.md)

It does not cover horizontal scaling, ingress, or managed monitoring
infrastructure.

For broader production incident handling after deployment, use:

- [`incident-response-playbooks.md`](incident-response-playbooks.md)

For authenticated operator verification after rollout, use:

- [`operator-verification-runbook.md`](operator-verification-runbook.md)

For connector fleet inspection, breaker cooldown interpretation, and retry
semantics, use:

- [`connector-boundary-runbook.md`](connector-boundary-runbook.md)

For the replica-safety contract and the ordered pre-work required before
multi-instance rollout, use:

- [`horizontal-scaling-architecture.md`](horizontal-scaling-architecture.md)

## Current Baseline

- Namespace: `agent33`
- API deployment: `agent33-api`
- API service: `agent33-api`
- Production rollout source: `deploy/k8s/overlays/production/`
- Monitoring assets:
  - `deploy/monitoring/grafana/agent33-production-overview.dashboard.json`
  - `deploy/monitoring/prometheus/agent33-alerts.rules.yaml`

Core in-cluster dependencies expected by the current overlay:

- PostgreSQL
- Redis
- NATS
- Ollama
- SearXNG

The production overlay is intentionally single-instance today. Multi-replica
guidance is defined in
[`horizontal-scaling-architecture.md`](horizontal-scaling-architecture.md) and
its `P1.2` follow-up work.

## Pre-Deployment Checklist

1. Build and publish an immutable API image for the target release.
2. Replace the image placeholder in
   `deploy/k8s/overlays/production/api-deployment-patch.yaml`.
3. Create real Kubernetes secrets from:
   - `deploy/k8s/base/api-secret.example.yaml`
   - `deploy/k8s/base/postgres-secret.example.yaml`
4. Confirm bootstrap auth is disabled unless you are intentionally creating the
   first admin:
   - `AUTH_BOOTSTRAP_ENABLED=false`
5. Confirm the Ollama runtime has the required model:
   - `llama3.2:3b`
6. Ensure your monitoring stack is ready to scrape `/metrics` before you rely on
   the checked-in alerting assets.

## Rollout Procedure

1. Prepare real secret manifests outside the repo.

```bash
cp deploy/k8s/base/postgres-secret.example.yaml /tmp/postgres-secret.yaml
cp deploy/k8s/base/api-secret.example.yaml /tmp/api-secret.yaml
```

2. Edit the secret values and the production overlay image tag or digest.
3. Apply the secrets.

```bash
kubectl apply -n agent33 -f /tmp/postgres-secret.yaml
kubectl apply -n agent33 -f /tmp/api-secret.yaml
```

If you prefer embedding the namespace directly in the secret manifests, set
`metadata.namespace: agent33` before applying them.

4. Apply the production overlay.

```bash
kubectl apply -k deploy/k8s/overlays/production
```

5. Wait for the API rollout to complete.

```bash
kubectl rollout status deployment/agent33-api -n agent33 --timeout=180s
```

6. Inspect the current pod set if the rollout does not settle.

```bash
kubectl get pods -n agent33
kubectl describe deployment agent33-api -n agent33
```

## Bootstrap Admin Flow

Bootstrap auth is for first-admin creation only and should not remain enabled
after setup.

1. Temporarily set `AUTH_BOOTSTRAP_ENABLED=true`.
2. Set a strong `AUTH_BOOTSTRAP_ADMIN_PASSWORD` in the API secret.
3. Apply the updated secret and overlay.
4. Port-forward the API service.

```bash
kubectl port-forward svc/agent33-api -n agent33 8000:8000
```

5. Mint the first admin token.

```bash
curl -X POST http://127.0.0.1:8000/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "REPLACE_WITH_STRONG_BOOTSTRAP_PASSWORD"
  }'
```

6. Restore `AUTH_BOOTSTRAP_ENABLED=false` and re-apply the overlay after the
   first admin path is working.

## Health Checks

For local operator checks against the live cluster, keep the API service
port-forwarded:

```bash
kubectl port-forward svc/agent33-api -n agent33 8000:8000
```

Then verify the current health surfaces in this order:

1. Liveness:

```bash
curl http://127.0.0.1:8000/healthz
```

2. Readiness against core dependencies:

```bash
curl -i http://127.0.0.1:8000/readyz
```

3. Aggregated operator health:

```bash
curl http://127.0.0.1:8000/health
```

4. Authenticated operator status summary:

```bash
curl http://127.0.0.1:8000/v1/operator/status \
  -H "Authorization: Bearer $TOKEN"
```

5. Authenticated connector fleet summary:

```bash
curl http://127.0.0.1:8000/v1/connectors \
  -H "Authorization: Bearer $TOKEN"
```

`/v1/operator/status` requires `operator:read` or `admin`.
`/v1/connectors` follows the same authenticated operator path documented in
[`connector-boundary-runbook.md`](connector-boundary-runbook.md).

Expected current checks:

- `/healthz` returns process health only
- `/readyz` validates `ollama`, `redis`, `postgres`, and `nats`
- `/health` includes dependency-aware service states plus `voice_sidecar`,
  `status_line`, and connector fleet summary when configured
- `/v1/operator/status` exposes the richer authenticated operator inventory
- `/v1/connectors` exposes per-connector circuit policy and cooldown state

## Monitoring Checks

1. Verify Prometheus scrape output directly:

```bash
curl http://127.0.0.1:8000/metrics
```

2. Load the checked-in monitoring assets from `deploy/monitoring/` into your
   existing Grafana and Prometheus stack.
3. Use the public dashboard-alert summary for ad hoc validation:

```bash
curl http://127.0.0.1:8000/v1/dashboard/alerts
```

Use `/v1/dashboard/alerts` for operator spot checks only. The production-facing
alerting contract for this slice is the Prometheus rule file, not the in-app
dashboard route.

The bounded objective baseline for this slice lives in
[`service-level-objectives.md`](service-level-objectives.md). The current
Prometheus alert names are:

- `Agent33EffortTelemetryExportFailures`
- `Agent33HighEffortRoutingRatio`
- `Agent33EstimatedCostDrift`

## Rollback

The current rollback path is deployment-manifest based, not the in-app release
rollback API.

If a new API image is unhealthy after rollout:

1. Revert the image reference in
   `deploy/k8s/overlays/production/api-deployment-patch.yaml` to the prior
   immutable tag or digest.
2. Re-apply the production overlay.

```bash
kubectl apply -k deploy/k8s/overlays/production
kubectl rollout status deployment/agent33-api -n agent33 --timeout=180s
```

If the failed rollout already created a Kubernetes deployment revision, you can
also use:

```bash
kubectl rollout undo deployment/agent33-api -n agent33
```

This runbook does not claim automated rollback for PostgreSQL, Redis, NATS,
Ollama, SearXNG, or application-level state. Broader incident procedures belong
in [`incident-response-playbooks.md`](incident-response-playbooks.md).

## Common Recovery Cases

### `/readyz` returns `503`

Cause:

- one or more core dependencies are unavailable

Checks:

```bash
kubectl get pods -n agent33
kubectl logs deployment/agent33-api -n agent33 --tail=200
```

Recovery:

- restore the failed dependency first
- re-check `/readyz` before trusting `/health`

### Ollama is running but the API is still not ready

Cause:

- the required `llama3.2` model is missing

Recovery:

```bash
kubectl exec -n agent33 deploy/ollama -- ollama pull llama3.2
```

### `/metrics` is empty or Grafana panels stay blank

Cause:

- Prometheus is not scraping the API service yet
- the dashboard/rule assets were not imported

Checks:

- confirm `deploy/k8s/base/api-service.yaml` annotations are present
- confirm your Prometheus scrape job sees the `agent33-api` service
- confirm the Grafana datasource is bound to `DS_PROMETHEUS`

### Bootstrap auth was left enabled

Cause:

- `AUTH_BOOTSTRAP_ENABLED=true` remained in the applied config after first-admin
  creation

Recovery:

- set `AUTH_BOOTSTRAP_ENABLED=false`
- re-apply the production overlay
- confirm the bootstrap credentials are no longer accepted

## Docker Compose Smoke Test

A CI workflow validates that the Docker Compose stack boots and serves its core
endpoints.  The same script runs locally:

```bash
# From the repository root
chmod +x scripts/docker-smoke-test.sh
scripts/docker-smoke-test.sh engine/docker-compose.yml
```

The script:

1. Creates a minimal `engine/.env` if one does not already exist.
2. Starts `postgres`, `redis`, `nats`, `searxng`, and `api` via
   `docker compose up`.
3. Polls `/healthz` until the API process is ready (up to 120 seconds).
4. Runs smoke checks against `/healthz`, `/health`, `/readyz`, `/docs`, and
   `/metrics`.
5. Tears down all containers and volumes on exit.

The CI workflow (`.github/workflows/docker-smoke.yml`) triggers on PRs that
touch the Dockerfile, docker-compose file, deployment manifests, or the smoke
script itself.  It can also be triggered manually via `workflow_dispatch`.
