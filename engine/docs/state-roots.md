# State Roots

This document is the source of truth for where AGENT-33 durable filesystem state belongs.

## Approved Roots

| Root | Purpose | Examples |
| --- | --- | --- |
| `app_root/` | Repo-local config and approved repo-local artifacts | `agent-definitions/`, `workflow-definitions/`, `skills/`, `packs/`, `plugins/`, `trajectories/` |
| `app_root/var/` | Repo-local mutable runtime state | `var/process-manager/`, `var/backups/`, `var/plugin_lifecycle_state.json`, `var/synthetic_environment_bundles.json` |
| `~/.agent33/` | User-local durable state that should survive repo replacement | `~/.agent33/sessions/`, `~/.agent33/hooks/` |

## Contract

- Relative durable paths resolve from the repository root.
- New runtime code must use `agent33.state_paths.RuntimeStatePaths` to resolve or validate write targets.
- Paths outside the approved roots are invalid for runtime-owned durable state.
- Repo-local mutable state should prefer `var/` unless there is a strong reason to keep an artifact elsewhere in the repo root.

## Current Defaults

| Setting / surface | Canonical root |
| --- | --- |
| `orchestration_state_store_path` | `app_root/` or `app_root/var/` |
| `process_manager_log_dir` | `app_root/var/` |
| `backup_dir` | `app_root/var/` |
| `plugin_state_store_path` | `app_root/var/` |
| `operator_session_base_dir` | `~/.agent33/sessions/` when unset |
| script hook user dir | `~/.agent33/hooks/` when unset |
| `trajectory_output_dir` | `app_root/` |
