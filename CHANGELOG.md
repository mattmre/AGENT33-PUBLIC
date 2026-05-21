# Changelog

All notable changes to AGENT-33 are recorded in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_No changes yet._

## [2.1.0] — 2026-05-21

Initial public release of AGENT-33 under the Apache License 2.0.

### Added

- **Engine** (`engine/`) — FastAPI service with lifespan-wired subsystems and
  an Alembic-managed PostgreSQL schema.
- **Frontend** (`frontend/`) — React/TypeScript operator console.
- **CLI** (`agent33`) — installable via `pip install -e ".[dev]"`. Commands
  include `status`, `sessions`, `bench`, `packs`, and config introspection.
- **Docker Compose stack** — single-command spin-up of Postgres, Redis, NATS,
  Ollama, and the engine.
- **Kubernetes manifests** (`deploy/k8s/`) — base configuration and a
  production overlay with HPA wiring.
- **Multi-tenant security model** — JWT and API-key authentication, tenant
  isolation enforced through `tenant_id` propagation across persistence and
  service layers.
- **Agent subsystem** (`engine/src/agent33/agents/`) — agent registry, JSON
  definitions auto-loaded from `engine/agent-definitions/`, capability
  taxonomy, agent runtime with iterative and streaming invocation.
- **Workflow engine** (`engine/src/agent33/workflows/`) — DAG executor with
  retries, timeouts, parallel groups, conditional branches, expression
  evaluator, and checkpoint persistence.
- **Skill registry** (`engine/src/agent33/skills/`) — SKILL.md and YAML
  loaders, progressive disclosure (L0/L1/L2), runtime injection into the
  agent prompt context.
- **Pack registry** (`engine/src/agent33/packs/`) — local registry, optional
  PackHub client, signature verification through integrity hashing.
- **Tool framework** (`engine/src/agent33/tools/`) — JSON Schema validated
  tool execution, governance allowlists, builtin tools for shell, file
  operations, HTTP fetch, and headless browser.
- **Messaging** (`engine/src/agent33/messaging/`) — adapters for Telegram,
  Discord, Slack, and WhatsApp; per-channel health checks; NATS event bus.
- **Code execution** (`engine/src/agent33/execution/`) — sandbox contracts,
  input validation, CLI adapter via subprocess, progressive disclosure of
  results.
- **Observability** (`engine/src/agent33/observability/`) — structured logs,
  metrics, lineage, replay, alerting, and a trace pipeline with failure
  taxonomy and retention policies.
- **Evaluation** (`engine/src/agent33/evaluation/`) — golden tasks and cases,
  metrics calculator, regression gates, evaluation service and API.
- **Autonomy budgets** (`engine/src/agent33/autonomy/`) — budget lifecycle
  state machine, preflight checks, runtime enforcement for file, command,
  and network scopes.
- **Release automation** (`engine/src/agent33/release/`) — release lifecycle
  states (planned → frozen → rc → validating → released → rolled_back),
  pre-release checklist, sync engine, rollback manager.
- **Continuous improvement** (`engine/src/agent33/improvement/`) — research
  intake lifecycle, lessons learned tracking, improvement checklists,
  roadmap refresh records.
- **Candidate ingestion** (`engine/src/agent33/ingestion/`) — governed
  candidate → validated → published → revoked lifecycle for external assets
  with confidence/trust labels.
- **Knowledge ingestion** (`engine/src/agent33/knowledge/`) — RSS, GitHub,
  web, and folder adapters with APScheduler cron support.
- **MCP integration** (`engine/src/agent33/mcp_server/`) — hosted MCP server
  surface plus client integration with circuit-breaker proxy semantics.
- **Memory** (`engine/src/agent33/memory/`) — short-term buffer, pgvector
  long-term store, hybrid RAG pipeline (BM25 + vector via RRF), token-aware
  chunking, session state.
- **LLM router** (`engine/src/agent33/llm/`) — provider abstraction with
  Ollama and OpenAI-compatible adapters plus a model router and a provider
  catalog auto-registered from environment variables.
- **SkillsBench integration** (`engine/src/agent33/benchmarks/skillsbench/`)
  — runner, adapter, task loader, CTRF reporting, smoke and full tiers.

### Documentation

- README, QUICKSTART, INSTALL, ARCHITECTURE at the repo root.
- Operator manual, configuration reference, CLI reference, API reference,
  troubleshooting guide, upgrade guide, use cases, and walkthroughs in
  `docs/`.
- Architecture deep-dive with mermaid diagrams in `docs/architecture/`.
- Operator runbooks in `docs/operators/` and `docs/runbooks/`.
- Contribution standard, concepts, glossary, testing, releasing, and
  examples documents.

### Known limitations

- Single-instance default Kubernetes manifest. Multi-replica deployment is
  supported by the production overlay but requires operator review of
  state-boundary assumptions in `engine/src/agent33/lifespan/`.
- Pack signing uses SHA-256 integrity. Asymmetric signing (Sigstore cosign)
  is on the near-term roadmap.
- Some authenticated routes are not yet scoped per-tenant; see
  `docs/architecture/api-surface.md` for the current scope matrix.

[Unreleased]: https://github.com/mattmre/AGENT33-PUBLIC/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/mattmre/AGENT33-PUBLIC/releases/tag/v2.1.0
