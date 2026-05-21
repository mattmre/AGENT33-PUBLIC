# Run History Authority

This document defines which runtime surface owns workflow execution history identity.

## Canonical Identifier

- Workflow execution history is keyed by `run_id`.
- `run_id` is the authority for:
  - workflow history lookups
  - DAG overlays for completed runs
  - operations-hub workflow process IDs

## History Record Shape

Workflow execution records must include:

- `run_id`
- `workflow_name`
- `trigger_type`
- `status`
- `duration_ms`
- `timestamp`
- optional: `error`, `job_id`, `step_statuses`, `tenant_id`

## Compatibility Rule

- Older in-memory history blobs that predate `run_id` are normalized through `agent33.workflows.history.normalize_execution_record`.
- Legacy records receive a deterministic synthetic identifier in the form `legacy-<workflow_name>-<timestamp_ms>`.
- New code should write canonical records directly and should not emit `workflow:<workflow_name>:<timestamp>` as the primary process identifier.
