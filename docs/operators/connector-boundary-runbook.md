# Connector Boundary Runbook

## Purpose

Explain the shipped connector boundary contract for operators who need to
inspect connector retries, circuit-breaker cooldowns, and recovery behavior on
the current `main` baseline.

Use this document with:

- [`production-deployment-runbook.md`](production-deployment-runbook.md)
- [`service-level-objectives.md`](service-level-objectives.md)
- [`incident-response-playbooks.md`](incident-response-playbooks.md)

## Middleware Order

The default connector boundary executor is built in
`engine/src/agent33/connectors/boundary.py` with this logical order:

1. governance
2. timeout
3. retry
   Active only when a caller explicitly uses `retry_attempts > 1`.
4. circuit breaker
   Active only when `CONNECTOR_CIRCUIT_BREAKER_ENABLED=true`.
5. metrics

In other words, the call path is:

`governance -> timeout -> [retry if enabled] -> [circuit breaker if enabled] -> metrics`

This order is intentional:

- governance denies before any outbound work
- timeout and retry, when enabled, wrap the downstream call path
- the circuit breaker, when enabled, records terminal failures and blocks open circuits
- metrics record the final success/failure outcome and latency

## Current Breaker Policy

The breaker settings shipped on `main` are:

- `connector_circuit_failure_threshold=3`
- `connector_circuit_recovery_seconds=30.0`
- `connector_circuit_half_open_successes=2`
- `connector_circuit_max_recovery_seconds=300.0`

Recovery uses progressive backoff:

`effective_recovery_timeout = min(base_recovery_timeout * 2^(total_trips - 1), max_recovery_timeout_seconds)`

The connector API snapshot exposes the live breaker policy through:

- `failure_threshold`
- `recovery_timeout_seconds`
- `half_open_success_threshold`
- `max_recovery_timeout_seconds`
- `effective_recovery_timeout_seconds`
- `cooldown_remaining_seconds`

## Retry Semantics

Retry behavior is intentionally narrow:

- downstream exceptions are retried up to the configured attempt count
- governance denials are not retried
- open-circuit rejections are not retried

This means there is no automatic retry unless a caller opts into
`retry_attempts > 1`, and there are no hidden retries for blocked or
already-open connectors.

## Verification Steps

Keep the API port-forwarded or otherwise reachable, then inspect the connector
surfaces in this order:

1. Fleet summary:

```bash
curl http://127.0.0.1:8000/v1/connectors \
  -H "Authorization: Bearer $TOKEN"
```

2. Single connector detail:

```bash
curl http://127.0.0.1:8000/v1/connectors/evokore \
  -H "Authorization: Bearer $TOKEN"
```

3. Breaker transition history:

```bash
curl "http://127.0.0.1:8000/v1/connectors/evokore/events?limit=20" \
  -H "Authorization: Bearer $TOKEN"
```

`/v1/connectors*` requires `admin` or the normal authenticated operator token
path already used for the wider operator surfaces.

## How To Read Open Circuits

When a connector snapshot shows `state="open"`:

1. check `total_trips` to confirm whether repeated failures are escalating the
   cooldown
2. compare `recovery_timeout_seconds` to
   `effective_recovery_timeout_seconds`
3. use `cooldown_remaining_seconds` to see how long remains before the breaker
   can move to `half_open`
4. inspect `/v1/connectors/{connector_id}/events` for rapid oscillation

Repeated `closed -> open -> half_open -> open` transitions indicate the
upstream is still unstable and the progressive timeout is still growing toward
`max_recovery_timeout_seconds`.

## Recovery Guidance

If connector-related alerts or `/health` indicate degraded connector behavior:

1. confirm the failing connector ID in `/v1/connectors`
2. inspect recent transitions in `/v1/connectors/{connector_id}/events`
3. check the upstream dependency before forcing any restart workflow
4. wait for `cooldown_remaining_seconds` to drain if the breaker is behaving as
   designed
5. use [`incident-response-playbooks.md`](incident-response-playbooks.md) if the
   connector issue is causing a wider service incident

This runbook does not add manual breaker mutation commands. The supported
operator path is observation, upstream repair, and natural breaker recovery.
