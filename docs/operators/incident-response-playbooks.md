# Incident Response Playbooks

## Purpose

Handle the first production incidents for the current AGENT-33 single-instance
Kubernetes baseline without assuming extra infrastructure beyond what is
already shipped in this repo.

Use this document with:

- [`production-deployment-runbook.md`](production-deployment-runbook.md)
- [`operator-verification-runbook.md`](operator-verification-runbook.md)
- [`process-registry-runbook.md`](process-registry-runbook.md)
- [`../../deploy/k8s/overlays/production/README.md`](../../deploy/k8s/overlays/production/README.md)
- [`../../deploy/monitoring/README.md`](../../deploy/monitoring/README.md)
- [`../../deploy/monitoring/prometheus/agent33-alerts.rules.yaml`](../../deploy/monitoring/prometheus/agent33-alerts.rules.yaml)

This playbook does not define new SLI thresholds or new monitoring assets.
Formal objective policy lives in `service-level-objectives.md`, and evaluation
plus webhook incidents remain manual because the repo does not export
Prometheus-backed thresholds for them yet.

The current objective and error-budget baseline now lives in:

- [`service-level-objectives.md`](service-level-objectives.md)

## Severity Model

| Severity | Meaning | Initial Response |
| --- | --- | --- |
| `SEV1` | API unavailable or major customer-facing outage | immediately |
| `SEV2` | core dependency degraded or repeated failed automation | within 30 minutes |
| `SEV3` | localized failure with workaround | within 2 hours |
| `SEV4` | low-impact issue or operator-only drift | next business day |

Escalate immediately when:

- `/healthz` is unavailable
- `/readyz` stays `503` after dependency recovery attempts
- webhook dead letters continue growing after retry
- evaluation regressions block a release or indicate a fresh production defect

## Shared Triage Workflow

1. Port-forward the API service.

```bash
kubectl port-forward svc/agent33-api -n agent33 8000:8000
```

2. Capture the public health and alert snapshot.

```bash
curl -i http://127.0.0.1:8000/healthz
curl -i http://127.0.0.1:8000/readyz
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/metrics
curl http://127.0.0.1:8000/v1/dashboard/alerts
```

3. If auth still works, collect the operator diagnostic state.

```bash
curl http://127.0.0.1:8000/v1/operator/status \
  -H "Authorization: Bearer $TOKEN"
curl http://127.0.0.1:8000/v1/operator/doctor \
  -H "Authorization: Bearer $TOKEN"
```

4. Record the current rollout state before changing anything.

```bash
kubectl get pods -n agent33
kubectl rollout status deployment/agent33-api -n agent33 --timeout=180s
kubectl describe deployment agent33-api -n agent33
kubectl logs deployment/agent33-api -n agent33 --tail=200
```

## Incident Matrix

| Incident | Primary Signals | First Auth Surface | First Cluster Check |
| --- | --- | --- | --- |
| API service down | `/healthz` fails, rollout not healthy | `/v1/operator/status` | `kubectl get pods -n agent33` |
| Degraded dependencies | `/readyz` returns `503`, `/health` degraded | `/v1/operator/doctor` | dependency pod state and API logs |
| Evaluation regression | `/v1/evaluations/regressions` non-empty, scheduled gate failures | `/v1/evaluations/schedules` and regression routes | recent deploy image / rollout history |
| Webhook backlog growth | dead letters or retrying deliveries grow | `/v1/webhooks/deliveries/stats` | API logs and target webhook health |

## Playbook 1: API Service Down

### Detection

- `curl -i http://127.0.0.1:8000/healthz` fails or times out
- `kubectl rollout status deployment/agent33-api -n agent33 --timeout=180s` does not settle
- Prometheus scrape for `/metrics` fails because the API is unreachable

### Initial Triage

```bash
kubectl get pods -n agent33
kubectl describe deployment agent33-api -n agent33
kubectl logs deployment/agent33-api -n agent33 --tail=200
curl -i http://127.0.0.1:8000/healthz
curl -i http://127.0.0.1:8000/readyz
```

### Mitigation

If the incident started immediately after a rollout, use the deployment
rollback path from the deployment runbook:

```bash
kubectl rollout undo deployment/agent33-api -n agent33
kubectl rollout status deployment/agent33-api -n agent33 --timeout=180s
```

If the deployment revision is not the issue, re-apply the pinned production
overlay and re-check readiness:

```bash
kubectl apply -k deploy/k8s/overlays/production
curl -i http://127.0.0.1:8000/healthz
curl -i http://127.0.0.1:8000/readyz
```

### Exit Criteria

- `/healthz` returns success
- `agent33-api` rollout is complete
- `/metrics` responds again

## Playbook 2: Degraded Dependencies / Readiness Failure

### Detection

- `curl -i http://127.0.0.1:8000/readyz` returns `503`
- `curl http://127.0.0.1:8000/health` shows degraded services
- `GET /v1/operator/doctor` returns warning or error checks

### Initial Triage

```bash
curl -i http://127.0.0.1:8000/readyz
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/v1/operator/doctor \
  -H "Authorization: Bearer $TOKEN"
kubectl get pods -n agent33
kubectl logs deployment/agent33-api -n agent33 --tail=200
```

The current repo-owned readiness path is expected to validate:

- `postgres`
- `redis`
- `nats`
- `ollama`

`SearXNG` is part of the deployed topology, but it is not currently part of the
blocking `/readyz` contract.

### Mitigation

Recover the failed dependency first, then re-check `/readyz`. For the current
baseline that usually means fixing the dependency pod, secret, or upstream
reachability rather than changing the API deployment.

If the API is healthy but operator inventory or registry state is stale, use the
bounded operator reset path:

```bash
curl -X POST http://127.0.0.1:8000/v1/operator/reset \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"targets":["registries"]}'
```

If the degraded dependency is Ollama model availability, restore the pinned
model:

```bash
kubectl exec -n agent33 deploy/ollama -- ollama pull llama3.2:3b
```

### Exit Criteria

- `/readyz` returns success
- `/v1/operator/doctor` no longer reports the blocking dependency error
- `/v1/operator/status` returns `healthy` or the known non-blocking degraded state

## Playbook 3: Evaluation Regression / Scheduled-Gate Failure

### Detection

- `GET /v1/evaluations/regressions` returns active regression records
- scheduled-gate history shows repeated failures or growing `regressions_found`
- a release or operator workflow is blocked by regression evidence

### Initial Triage

```bash
curl http://127.0.0.1:8000/v1/evaluations/regressions \
  -H "Authorization: Bearer $TOKEN"
curl http://127.0.0.1:8000/v1/evaluations/schedules \
  -H "Authorization: Bearer $TOKEN"
curl http://127.0.0.1:8000/v1/evaluations/schedules/$SCHEDULE_ID/history \
  -H "Authorization: Bearer $TOKEN"
```

If you need to confirm the regression against the current baseline, trigger the
configured schedule manually:

```bash
curl -X POST http://127.0.0.1:8000/v1/evaluations/schedules/$SCHEDULE_ID/trigger \
  -H "Authorization: Bearer $TOKEN"
```

### Mitigation

1. Confirm whether the regression started after the current rollout.
2. If it aligns with the current deployment, treat it as a production defect and
   use the deployment rollback from Playbook 1.
3. Triage the regression record before resolving it.

```bash
curl -X PATCH http://127.0.0.1:8000/v1/evaluations/regressions/$REGRESSION_ID/triage \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"investigating","assignee":"platform"}'
```

Only resolve the regression after the underlying problem is fixed and a fresh
run shows recovery.

```bash
curl -X POST http://127.0.0.1:8000/v1/evaluations/regressions/$REGRESSION_ID/resolve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"resolved_by":"platform","fix_commit":"REPLACE_WITH_COMMIT"}'
```

### Exit Criteria

- regression records are triaged with current notes
- follow-up schedule or evaluation run no longer reproduces the regression
- if a rollout caused the regression, the deployment has been reverted or fixed

## Playbook 4: Webhook Delivery Backlog Growth / Dead Letters

### Detection

There is no Prometheus-backed threshold for this incident yet. Use the admin
delivery endpoints directly:

```bash
curl http://127.0.0.1:8000/v1/webhooks/deliveries/stats \
  -H "Authorization: Bearer $TOKEN"
curl http://127.0.0.1:8000/v1/webhooks/deliveries/dead-letters \
  -H "Authorization: Bearer $TOKEN"
```

Escalate when:

- `dead_lettered` is non-zero
- `retrying` keeps increasing across repeated checks
- one downstream webhook destination is consistently failing

### Initial Triage

```bash
curl http://127.0.0.1:8000/v1/webhooks/deliveries/stats \
  -H "Authorization: Bearer $TOKEN"
curl http://127.0.0.1:8000/v1/webhooks/deliveries/dead-letters \
  -H "Authorization: Bearer $TOKEN"
kubectl logs deployment/agent33-api -n agent33 --tail=200
```

Check whether the failure is:

- a bad downstream URL or auth secret
- a transient target outage
- a repeated permanent payload or contract failure

### Mitigation

Retry dead-lettered deliveries only after the downstream target is healthy:

```bash
curl -X POST http://127.0.0.1:8000/v1/webhooks/deliveries/$DELIVERY_ID/retry \
  -H "Authorization: Bearer $TOKEN"
```

If delivered records are masking the signal, purge only old successful history:

```bash
curl -X DELETE "http://127.0.0.1:8000/v1/webhooks/deliveries/purge?older_than_hours=24" \
  -H "Authorization: Bearer $TOKEN"
```

Do not treat purge as remediation for live dead letters. Purge only reduces
retained delivered history.

### Exit Criteria

- `dead_lettered` returns to zero or a known accepted level
- `retrying` stabilizes instead of growing
- the downstream webhook target is healthy again

## Dependency Map

| Scenario | Public Checks | Authenticated Checks | Repo Assets |
| --- | --- | --- | --- |
| API service down | `/healthz`, `/readyz`, `/metrics` | `/v1/operator/status` | `deploy/k8s/overlays/production/`, `production-deployment-runbook.md` |
| Degraded dependencies | `/readyz`, `/health` | `/v1/operator/doctor`, `/v1/operator/reset` | `deploy/k8s/base/`, `deploy/k8s/overlays/production/` |
| Evaluation regression | `/v1/dashboard/alerts` for context only | `/v1/evaluations/regressions`, `/v1/evaluations/schedules/*` | `deploy/monitoring/prometheus/agent33-alerts.rules.yaml` |
| Webhook backlog growth | none beyond base health | `/v1/webhooks/deliveries/stats`, `/dead-letters`, `/{delivery_id}/retry` | API logs and admin webhook-delivery routes |

## Notes

- The production Prometheus rule file currently covers effort-routing telemetry
  export reliability, routing mix, and persistent cost lifetime-average
  elevation only.
- These playbooks intentionally rely on the repo's current operator and admin
  APIs for regression and webhook incidents.
- Evaluation, webhook, dependency, and request-level objectives require new
  Prometheus metrics before they can move beyond manual/operator procedures.
