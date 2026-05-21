# ADR-001: Task Run Evidence Ledger

Date: 2026-05-05

## Decision

Introduce a tenant-scoped ledger contract around `Task -> Run -> RunEvent ->
Evidence` so later Operations result pages, Doctor Center, and proof surfaces
have a common substrate.

## Compatibility

- Existing spawner/workflow/session identifiers can map into `Run.source_id`.
- Existing operations events can append `RunEvent` records without changing
  current Operations Hub polling.
- Existing artifact/review surfaces can link to `Evidence.uri` until a durable
  artifact repository is connected.

## Current Scope

This slice adds the typed model, in-memory repository, read route, and focused
tenant-scoping tests. Durable persistence and producer integration are reserved
for follow-up slices.
