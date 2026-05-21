# Runtime Architecture Map

This is the terse runtime layer contract for `engine/src/agent33`.

## Layers

### 1. App shell

- `main.py`
- `api/`
- `cli/`
- `mcp_server/`

Role:
- construct the FastAPI app and request adapters
- wire subsystems onto `app.state`
- expose HTTP, CLI, and MCP entry points

### 2. Core runtime

- `agents/`
- `workflows/`
- `tools/`
- `llm/`
- `memory/`
- `security/`
- `execution/`
- `skills/`

Role:
- implement agent execution, tool loops, workflow orchestration, model access,
  context handling, security, and code execution primitives

### 3. Platform services and stateful subsystems

- `services/`
- `processes/`
- `sessions/`
- `release/`
- `review/`
- `evaluation/`
- `improvement/`
- `autonomy/`
- `observability/`
- `training/`

Role:
- provide reusable service objects, lifecycle managers, persistence-backed
  orchestration, and operator-facing state

### 4. Integration and domain edges

- `automation/`
- `connectors/`
- `messaging/`
- `voice/`
- `plugins/`
- `packs/`
- `web_research/`
- `component_security/`
- `operator/`
- `ops/`

Role:
- connect AGENT-33 to external systems, operational surfaces, and domain-specific
  extension points

## Directional Rules

1. Core runtime packages do not import the app shell (`api`, `cli`, `mcp_server`, `main.py`).
2. Service modules do not import `api.routes`; routes should adapt request state into services.
3. Route modules do not import `main.py`; dependencies should come from request/app state or explicit getters.
4. `main.py` is the composition root and may wire any subsystem.

## Temporary Allowlisted Exceptions

- `agent33.services.operations_hub`
  Reason: currently reaches route getters for trace, autonomy, improvement, and workflow history.
- `agent33.api.routes.training`
  Reason: currently imports `agent33.main.app` directly for route-local training access.

These exceptions are intentionally narrow and should be removed by later hardening slices, not expanded casually.
