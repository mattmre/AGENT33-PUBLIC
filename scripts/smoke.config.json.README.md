# smoke.config.json — Stage 2 runner configuration

This file lives at your repo root (NOT under `scripts/`). The v3.5 smoke
wrappers (`smoke.sh`, `smoke.ps1`) read it to decide which language-specific
runner under `scripts/smoke_pipeline.*` to dispatch.

## Fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `language` | string | yes | One of `python`, `node`, `shell`. Selects the runner. |
| `production_entry` | string | yes (node, shell) | Path relative to repo root to the production entry file. |
| `production_module` | string | yes (python) | Dotted Python module name (e.g. `myapp.pipeline`). |
| `production_exports` | string[] | optional | Named exports / module-level attributes that must exist. |
| `production_constants` | string[] | optional (python) | Module-level constants that must exist. |
| `ceiling_command` | string[] | optional | argv tokens for the ceiling-tier subprocess (e.g. `["npm", "run", "curate:test"]`). Empty list = floor only. |

## Example: Node repo

```json
{ "language": "node",
  "production_entry": "tools/curate.mjs",
  "production_exports": ["runCuration"],
  "ceiling_command": ["npm", "run", "curate:test"] }
```

## Example: Python repo

```json
{ "language": "python",
  "production_module": "myapp.pipeline",
  "production_constants": ["NUM_WORKERS"],
  "production_exports": ["main"],
  "ceiling_command": [] }
```

## Example: Go server with shell-only floor

```json
{ "language": "shell",
  "production_entry": "bin/myserver",
  "ceiling_command": ["./bin/myserver", "--smoke"] }
```

## Why this file exists at the repo root, not under `scripts/`

`smoke.config.json` is per-repo configuration. The kit ships
runner templates under `scripts/smoke_pipeline.*`; the templates do NOT need
editing in v3.5. All per-repo configuration lives here. When the kit
publishes a new version of a template, an adopter can re-copy the template
without losing their config.
