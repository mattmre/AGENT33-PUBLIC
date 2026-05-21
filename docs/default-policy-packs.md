# Connector Boundary Policy Packs

AGENT-33 connector boundaries now support policy-pack presets via `CONNECTOR_POLICY_PACK`.

## Available packs

- `default` (default): no connector/operation blocks. Behavior matches legacy defaults.
- `strict-web`: blocks outbound web connector surfaces:
  - connectors: `tool:web_fetch`, `workflow:http_request`, `search:searxng`, `tool:reader`
- `mcp-readonly`: blocks MCP tool invocation calls (all `tools/call` operations, including read-only and mutation tools):
  - operations: `tools/call`

## How packs combine with explicit blocklists

Policy-pack blocks are **unioned** with:

- `CONNECTOR_GOVERNANCE_BLOCKED_CONNECTORS`
- `CONNECTOR_GOVERNANCE_BLOCKED_OPERATIONS`

So explicit blocklists still work exactly as before.

## Middleware order

The shipped connector boundary follows this logical order when each middleware
is enabled:

1. governance
2. timeout
3. retry
   Active only when a caller explicitly uses `retry_attempts > 1`.
4. circuit breaker
   Active only when `CONNECTOR_CIRCUIT_BREAKER_ENABLED=true`.
5. metrics

The `agent33://policy-pack` MCP resource publishes both:

- `logical_middleware_order` for the canonical ordering contract
- `active_middleware_order` for the current settings-driven chain shape

## Retry policy

- the retry middleware is only inserted when a caller explicitly passes
  `retry_attempts > 1`
- the default adopted connector stance on `main` is `retry_attempts = 1`
- governance denials are not retried
- open-circuit rejections are not retried

In practice, this means there is no automatic retry unless the caller opts into
it.

## Circuit breaker policy

When `CONNECTOR_CIRCUIT_BREAKER_ENABLED=true`, the boundary uses:

- `CONNECTOR_CIRCUIT_FAILURE_THRESHOLD`
- `CONNECTOR_CIRCUIT_RECOVERY_SECONDS`
- `CONNECTOR_CIRCUIT_HALF_OPEN_SUCCESSES`
- `CONNECTOR_CIRCUIT_MAX_RECOVERY_SECONDS`

Recovery uses progressive capped backoff:

`effective_recovery_timeout = min(base_recovery_timeout * 2^(total_trips - 1), max_recovery_timeout_seconds)`

Use [`operators/connector-boundary-runbook.md`](operators/connector-boundary-runbook.md)
for the operator workflow around `/v1/connectors` snapshots and breaker event
history.

## Stable inspection surface

The MCP resource `agent33://policy-pack` is the stable inspection surface for:

- configured policy pack
- configured and effective governance blocklists
- logical and active middleware order
- retry policy
- circuit breaker policy

## Notes

- Packs only apply when `CONNECTOR_BOUNDARY_ENABLED=true`.
- Routes/services can opt into a specific pack by passing `policy_pack` when constructing a connector boundary executor.
