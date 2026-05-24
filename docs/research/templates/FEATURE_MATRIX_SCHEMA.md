# Feature Matrix Columns (Canonical)

Use these columns for a cross-repo comparison.

## Identity
- Repo
- Primary language
- License
- Primary interfaces (CLI / SDK / server / web UI)

## Orchestration
- Orchestration primitive (graph / workflow / crew / chat loop)
- Planning / spec workflow support
- Multi-agent coordination (roles, delegation, routing)
- Concurrency (parallel steps, queueing)

## State & Memory
- State representation (explicit struct, message list, event log)
- Persistence (threads, checkpointers, snapshots)
- Resumability (crash recovery, pause/resume)

## Safety & Governance
- Approval model (auto/ask/always)
- Sandboxing/isolation (Docker, VM, E2B, etc.)
- Network controls (allowlist/denylist)
- Prompt-injection mitigations

## Tooling
- Tool protocol (function calling, MCP, JSON-RPC)
- Tool discovery/registry
- Extensibility/plugin model

## Observability & QA
- Tracing/telemetry
- Logs/events
- Evaluation harness/benchmarks
- CI integration patterns

## Productization
- Deployment targets
- Configuration surface
- Enterprise controls (RBAC, secrets, audit)
