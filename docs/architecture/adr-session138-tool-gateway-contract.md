# ADR: Session 138 Tool Gateway Request Contract

Date: 2026-05-05

## Decision

Introduce a deterministic `ToolRequest` contract before routing mutating work
through the full gateway.

## Context

AGENT33 already has tool governance, approvals, mutation audit records, and
provenance receipts, but callers do not yet share one pre-execution envelope
with stable request hashes and idempotency keys.

## Contract

- `ToolRequest`: tool name, action, tenant, run id, params, dry-run flag,
  idempotency key, and risk class.
- `ToolGatewayResult`: request hash, effective idempotency key, risk class,
  dry-run state, mutation expectation, permission scope, acceptance, and reason.
- `ToolExecutionReceipt`: future execution receipt envelope for evidence and
  mutation references.

## Rollout

This slice adds preview validation at `/v1/tools/gateway/requests/preview`.
Later slices can wire file, shell, workflow, install, and external-write actions
through the gateway without changing the envelope.
