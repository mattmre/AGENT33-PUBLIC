# Process Registry Runbook

## Purpose

Operate the current managed-process surface safely using the already-shipped
`/v1/processes` API.

Use this runbook with:

- [`operator-verification-runbook.md`](operator-verification-runbook.md)
- [`production-deployment-runbook.md`](production-deployment-runbook.md)
- [`incident-response-playbooks.md`](incident-response-playbooks.md)
- [`../../engine/src/agent33/api/routes/processes.py`](../../engine/src/agent33/api/routes/processes.py)
- [`../../engine/src/agent33/processes/service.py`](../../engine/src/agent33/processes/service.py)

This runbook does not introduce new operator UX, PTY semantics, or process
reattachment behavior.

## Current Contract

The current managed-process surface is:

- `GET /v1/processes`
- `POST /v1/processes`
- `GET /v1/processes/{process_id}`
- `GET /v1/processes/{process_id}/log`
- `POST /v1/processes/{process_id}/write`
- `DELETE /v1/processes/{process_id}`
- `POST /v1/processes/cleanup`

Required scopes:

- `processes:read` for list, detail, and log access
- `processes:manage` for start, stdin write, terminate, and cleanup at the API
  layer
- if tool governance is enabled in the current deployment, process start can
  also be blocked unless `tools:execute` is present because start reuses the
  shell-tool governance preflight

Observed statuses are:

- `running`
- `completed`
- `failed`
- `terminated`
- `interrupted`

Phase 52 contract note:

- process `command`, `last_error`, and `/log` content are redacted before
  persistence and again on readback
- expect masked values such as `***` or `prefix...suffix` instead of raw tokens
  when a command line or subprocess output contains secrets

## Canonical Inventory Command

Use this as the first authenticated process-registry check:

```bash
curl "http://127.0.0.1:8000/v1/processes?limit=50" \
  -H "Authorization: Bearer $TOKEN"
```

Expected use:

- confirm the registry is reachable
- confirm the visible process count for the current tenant
- capture a `process_id` before deeper inspection

## Lifecycle Verification

1. Inspect one process record.

```bash
curl "http://127.0.0.1:8000/v1/processes/$PROCESS_ID" \
  -H "Authorization: Bearer $TOKEN"
```

2. Inspect the recent log tail.

```bash
curl "http://127.0.0.1:8000/v1/processes/$PROCESS_ID/log?tail=100" \
  -H "Authorization: Bearer $TOKEN"
```

3. If the process is waiting on stdin, write one bounded payload.

```bash
curl -X POST "http://127.0.0.1:8000/v1/processes/$PROCESS_ID/write" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"data":"status\n"}'
```

4. If the process is unhealthy and must stop, terminate it explicitly.

```bash
curl -X DELETE "http://127.0.0.1:8000/v1/processes/$PROCESS_ID" \
  -H "Authorization: Bearer $TOKEN"
```

## Recovery After Restart

The process registry persists metadata, but live subprocess handles are not
reattached after an application restart. Any process that was previously
`running` is recovered as `interrupted`.

Use this canonical recovery check first:

```bash
curl "http://127.0.0.1:8000/v1/processes?status_filter=interrupted&limit=50" \
  -H "Authorization: Bearer $TOKEN"
```

Then follow this checklist:

1. Capture each interrupted `process_id`.
2. Inspect `/v1/processes/{process_id}` and `/log` to confirm the last known
   redacted command and failure context.
3. Decide whether the command should be re-run from its owning workflow/session
   instead of assuming the platform can resume it in place.
4. Clean up stale interrupted records only after the owning workflow or operator
   action is understood.

## Bounded Cleanup

Cleanup removes completed, failed, terminated, or interrupted records that are
older than the provided cutoff and no longer have live handles.

Canonical cleanup command:

```bash
curl -X POST "http://127.0.0.1:8000/v1/processes/cleanup" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_age_seconds":3600}'
```

Use cleanup only after:

- the relevant logs have been captured
- any interrupted records have been triaged
- you do not need the registry entry for immediate operator follow-up

## Escalate When

- `GET /v1/processes` returns `503`
- a process is stuck in `running` but the log tail is frozen and terminate fails
- unexpected cross-tenant visibility is observed
- interrupted records grow after routine restarts without a clear owning workflow
