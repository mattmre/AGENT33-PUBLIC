# Operator Verification Runbook

## Purpose

Run the shortest honest verification path for the current operator control
plane and the adjacent high-risk operator surfaces already shipped on `main`.

Use this runbook with:

- [`production-deployment-runbook.md`](production-deployment-runbook.md)
- [`incident-response-playbooks.md`](incident-response-playbooks.md)
- [`process-registry-runbook.md`](process-registry-runbook.md)
- [`../../engine/src/agent33/api/routes/operator.py`](../../engine/src/agent33/api/routes/operator.py)
- [`../../engine/src/agent33/api/routes/backups.py`](../../engine/src/agent33/api/routes/backups.py)

This runbook does not define new dashboards or new automation. It does define
the manual, gated restore execution path that must follow restore planning.

## Required Scopes

Use a read-only verification token with:

- `operator:read`
- `processes:read`

Use a separate elevated reset token with:

- `operator:write`
- `admin`

Use a restore execution token with:

- `operator:write`

Keep the first verification pass on the read-only token. Only use the elevated
token if you have already captured `status` and `doctor` and a bounded reset is
actually justified.

## Canonical Verification Order

Use the authenticated checks in this order:

1. `GET /v1/operator/status`
2. `GET /v1/operator/doctor`
3. `GET /v1/processes?limit=50`
4. `GET /v1/backups`
5. If a backup exists, `POST /v1/backups/{backup_id}/verify`
6. If restore safety must be inspected, `POST /v1/backups/{backup_id}/restore-plan`
7. If restore execution is required, `POST /v1/backups/{backup_id}/restore`
   with `confirm=true` after reviewing the plan
8. If you are planning a fresh backup, `GET /v1/backups/inventory`

This order keeps the first pass read-only and short.

## Operator Control Plane Check

1. Capture the status snapshot.

```bash
curl "http://127.0.0.1:8000/v1/operator/status" \
  -H "Authorization: Bearer $READ_TOKEN"
```

Use it to confirm:

- overall authenticated operator reachability
- subsystem inventory counts
- dependency-aware health states already surfaced by `/health`

2. Capture the diagnostic snapshot.

```bash
curl "http://127.0.0.1:8000/v1/operator/doctor" \
  -H "Authorization: Bearer $READ_TOKEN"
```

Use it to confirm:

- whether the failure is a warning or an error
- the first remediation text for the failing subsystem
- whether a bounded reset is justified

## Process Registry Check

Use the canonical process inventory command from the dedicated process runbook:

```bash
curl "http://127.0.0.1:8000/v1/processes?limit=50" \
  -H "Authorization: Bearer $READ_TOKEN"
```

If any process needs deeper inspection or recovery, continue in
[`process-registry-runbook.md`](process-registry-runbook.md).

## Backup Verification Check

1. List existing archives.

```bash
curl "http://127.0.0.1:8000/v1/backups" \
  -H "Authorization: Bearer $READ_TOKEN"
```

2. Verify one archive.

```bash
curl -X POST "http://127.0.0.1:8000/v1/backups/$BACKUP_ID/verify" \
  -H "Authorization: Bearer $READ_TOKEN"
```

3. Inspect the inventory for a potential new backup.

```bash
curl "http://127.0.0.1:8000/v1/backups/inventory" \
  -H "Authorization: Bearer $READ_TOKEN"
```

4. If you need a read-only safety check before restore work, generate a restore
   preview.

```bash
curl -X POST "http://127.0.0.1:8000/v1/backups/$BACKUP_ID/restore-plan" \
  -H "Authorization: Bearer $READ_TOKEN"
```

Use restore preview only to inspect conflicts and planned actions. This slice
does not mutate state.

5. Execute restore only after the plan has been reviewed and the target state is
   understood.

```bash
curl -X POST "http://127.0.0.1:8000/v1/backups/$BACKUP_ID/restore" \
  -H "Authorization: Bearer $RESTORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"confirm":true,"allow_overwrite":false}'
```

If the restore plan reports overwrite conflicts, rerun only after deciding that
the live files may be replaced:

```bash
curl -X POST "http://127.0.0.1:8000/v1/backups/$BACKUP_ID/restore" \
  -H "Authorization: Bearer $RESTORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"confirm":true,"allow_overwrite":true}'
```

Never call restore without first saving the restore-plan output with the
incident or maintenance record. A restore without `confirm=true` is rejected,
and overwrite conflicts are rejected unless `allow_overwrite=true`.

## Bounded Reset Path

Use `/v1/operator/reset` only after `status` and `doctor` have been captured.

Registry-only reset:

```bash
curl -X POST "http://127.0.0.1:8000/v1/operator/reset" \
  -H "Authorization: Bearer $RESET_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"targets":["registries"]}'
```

Cache-only reset:

```bash
curl -X POST "http://127.0.0.1:8000/v1/operator/reset" \
  -H "Authorization: Bearer $RESET_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"targets":["caches"]}'
```

Use reset when the doctor output points to stale cache or discovery state. Do
not use it as a substitute for dependency recovery, rollout rollback, or backup
restore execution.

## Component Security Dashboard

This section covers the in-app security scanning system introduced in Phase 28.
It is separate from the GitHub Actions CI scans documented in
[`security-audit-checklist.md`](security-audit-checklist.md).

### Required Scopes

- Read: `component-security:read`
- Write (create/cancel/delete runs): `component-security:write`

### Starting a Scan

Create a run and execute it immediately (quick profile, two seconds):

```bash
curl -X POST "http://127.0.0.1:8000/v1/component-security/runs" \
  -H "Authorization: Bearer $WRITE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target":{"repository_path":"/path/to/repo"},"profile":"quick"}'
```

Available profiles:

| Profile    | Tools                                  |
|------------|----------------------------------------|
| `quick`    | bandit, gitleaks                       |
| `standard` | bandit, gitleaks, pip-audit            |
| `deep`     | bandit, gitleaks, pip-audit, semgrep   |

To create a run without executing it immediately, set `"execute_now": false` and
then trigger execution separately:

```bash
# Create pending run
RUN_ID=$(curl -s -X POST "http://127.0.0.1:8000/v1/component-security/runs" \
  -H "Authorization: Bearer $WRITE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target":{"repository_path":"/path/to/repo"},"profile":"standard","execute_now":false}' \
  | jq -r '.id')

# Launch it
curl -X POST "http://127.0.0.1:8000/v1/component-security/runs/$RUN_ID/launch" \
  -H "Authorization: Bearer $WRITE_TOKEN"
```

### Reading Findings

List all findings for a run (optionally filter by minimum severity):

```bash
# All findings
curl "http://127.0.0.1:8000/v1/component-security/runs/$RUN_ID/findings" \
  -H "Authorization: Bearer $READ_TOKEN"

# High and above only
curl "http://127.0.0.1:8000/v1/component-security/runs/$RUN_ID/findings?min_severity=high" \
  -H "Authorization: Bearer $READ_TOKEN"
```

Each finding contains: `severity`, `category`, `title`, `description`, `tool`,
`file_path`, `line_number`, `remediation`, and `cwe_id`.

### Exporting SARIF

SARIF 2.1.0 export for integration with GitHub Advanced Security or other SAST
consumers:

```bash
curl "http://127.0.0.1:8000/v1/component-security/runs/$RUN_ID/sarif" \
  -H "Authorization: Bearer $READ_TOKEN" \
  -o findings.sarif.json
```

### Registering MCP Security Servers

MCP security servers (Semgrep MCP, Trivy MCP, Snyk MCP, or custom) can be
registered as additional scan providers. After registration, every subsequent
`launch_scan()` call will invoke the server and merge its findings into the run.

Register a STDIO-transport server:

```bash
curl -X POST "http://127.0.0.1:8000/v1/component-security/mcp-servers" \
  -H "Authorization: Bearer $WRITE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "semgrep-mcp",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@semgrep/mcp"],
    "scan_tool_name": "scan"
  }'
```

Register an SSE-transport server:

```bash
curl -X POST "http://127.0.0.1:8000/v1/component-security/mcp-servers" \
  -H "Authorization: Bearer $WRITE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "trivy-remote",
    "transport": "sse",
    "url": "http://trivy-mcp-server:8080/sse",
    "scan_tool_name": "scan"
  }'
```

List registered servers:

```bash
curl "http://127.0.0.1:8000/v1/component-security/mcp-servers" \
  -H "Authorization: Bearer $READ_TOKEN"
```

Unregister a server:

```bash
curl -X DELETE "http://127.0.0.1:8000/v1/component-security/mcp-servers/semgrep-mcp" \
  -H "Authorization: Bearer $WRITE_TOKEN"
```

MCP server failures are non-fatal: if a server call fails, the run continues
and a warning is recorded in `metadata.tool_warnings`.

### Release Security Gate (RL-06)

When `start_validation()` is called on a release, AGENT-33 automatically
evaluates the security gate using the most recent completed scan run. The gate
checks:

- No critical findings (configurable via `block_on_critical`)
- High findings within the configured threshold (default: 0 allowed)
- Medium findings within the configured threshold (default: 10 allowed)

The result updates the RL-06 checklist item on the release. A FAIL decision
blocks publishing (`publish()`) because RL-06 is a required check.

To evaluate the gate manually for a specific run and apply it to a release:

```bash
curl -X POST "http://127.0.0.1:8000/v1/releases/$RELEASE_ID/security-gate" \
  -H "Authorization: Bearer $WRITE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"run_id":"'$RUN_ID'","policy":{"block_on_critical":true,"max_high":0,"max_medium":10}}'
```

If no completed scan run exists when `start_validation()` is called, RL-06 is
set to FAIL with the message "no completed scan run found for this release".
Run a scan and re-trigger validation to clear it.

### Service Health

```bash
curl "http://127.0.0.1:8000/v1/component-security/health" \
  -H "Authorization: Bearer $READ_TOKEN"
```

If `initialized` is `false`, the service failed to open its SQLite store. Check
`reason` in the response and ensure the configured `SECURITY_SCAN_DB_PATH` is
writable.

## Escalate When

- `/v1/operator/status` or `/v1/operator/doctor` returns `503`
- the doctor reports repeated `error` checks after one bounded reset
- process-registry inspection suggests lost ownership or unsafe tenant leakage
- backup verification or restore preview reports conflicts that do not match the
  expected on-disk state
