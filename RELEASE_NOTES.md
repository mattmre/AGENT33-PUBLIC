# AGENT-33 v2.1.0 — Initial Public Release

**Release date:** 2026-05-21
**License:** Apache License 2.0
**Container image:** `ghcr.io/mattmre/agent33:2.1.0`

This is the first public release of AGENT-33, a multi-agent orchestration
framework with first-class governance, evidence capture, and multi-tenant
isolation. The project ships as a working FastAPI engine, a React operator
console, an installable CLI, and reference deployment manifests for Docker
Compose and Kubernetes.

## What's in the box

### Engine

A FastAPI service (`engine/`) with a lifespan that wires the full runtime in
a deterministic order: Postgres → Redis → NATS → agent registry → code
executor → model router → embeddings → BM25 → hybrid search → RAG pipeline →
progressive recall → skill registry → workflow bridge → optional AirLLM →
memory → optional training. Each subsystem is stored on `app.state`, and
shutdown unwinds in reverse order.

The schema is Alembic-managed. PostgreSQL is the primary store; pgvector
holds long-term memory embeddings; Redis carries ephemeral state; NATS is
the event bus.

### Frontend

An operator console (`frontend/`) built with React and TypeScript. It is the
human-facing surface for sessions, agents, workflows, packs, traces, and
release operations. Every panel reads from a real backend route — there is
no sample data shipped in production builds.

### CLI

`agent33` is installable via `pip install -e ".[dev]"`. It exposes a small
set of commands tuned for operators: `status`, `sessions`, `bench`, `packs`,
and configuration introspection. The CLI uses the same authentication path
as any HTTP client.

### Deployment

- A single-command Docker Compose stack that spins up Postgres, Redis, NATS,
  Ollama, and the engine for local development.
- Kubernetes base manifests in `deploy/k8s/`, with a production overlay that
  wires Horizontal Pod Autoscaling.

## Design philosophy

AGENT-33 was built around four principles that shape every subsystem.

**Governance first.** Every action in the system has an identity, a tenant,
and an audit trail. Tools are JSON Schema validated. Tool execution is
gated by an allowlist. Code execution runs under a sandbox contract.
Autonomy budgets enforce file, command, and network scope at runtime. The
goal is that an operator can answer "who did what, when, and under what
authority" without leaving the platform.

**Multi-tenant by construction.** Tenant isolation is not a deployment
pattern — it is propagated through the persistence and service layers. JWT
and API-key authentication resolve the tenant on every request, and
`tenant_id` flows into the agent registry, workflow checkpoints, memory
stores, traces, and outcome records.

**Evidence over assertion.** Workflows produce checkpoints. Tool executions
produce traces. Agent runs produce lineage records. Evaluation suites
produce regression artifacts. The trace pipeline carries a failure
taxonomy so that operators can group incidents by category and apply
retention policies that match their compliance posture.

**Open by default.** AGENT-33 is released under Apache License 2.0. The
pack and skill systems are designed so that third-party authors can publish
capabilities through PackHub, and the MCP integration is bidirectional —
the engine both consumes external MCP servers and exposes its own surface
to MCP clients.

## Highlights

- **Agent runtime.** Definitions are JSON files auto-loaded from
  `engine/agent-definitions/`. The runtime supports iterative invocation
  and streaming. Six reference agents ship in the box: orchestrator,
  director, code-worker, qa, researcher, and browser-agent.
- **Workflow engine.** A DAG executor with retries, timeouts, parallel
  groups, conditional branches, a small expression evaluator, and durable
  checkpoint persistence. Actions include agent invocation, command
  execution, validation, transformation, conditional dispatch, parallel
  fan-out, wait, and code execution.
- **Skill and pack ecosystem.** Skills are SKILL.md or YAML documents that
  participate in progressive disclosure (L0 summary, L1 outline, L2 full
  body). Packs bundle skills, agents, and tools as distributable units;
  the local registry verifies SHA-256 integrity, and the optional PackHub
  client adds search, download, and update checks.
- **Tool framework.** Tools are JSON Schema validated at registration and
  again at invocation. Built-in tools include shell, file operations,
  HTTP fetch, and a headless browser. Governance allowlists are
  per-tenant.
- **Messaging.** First-class adapters for Telegram, Discord, Slack, and
  WhatsApp, with per-channel health checks and routing through the NATS
  event bus.
- **Memory.** A short-term buffer plus a pgvector-backed long-term store,
  token-aware chunking, and a hybrid RAG pipeline that combines BM25 and
  vector search using reciprocal rank fusion.
- **LLM router.** A provider abstraction with Ollama and
  OpenAI-compatible adapters plus a provider catalog that auto-registers
  from environment variables.
- **Observability.** Structured logs, metrics, lineage, replay, alerts,
  and a trace pipeline with a 10-category failure taxonomy and configurable
  retention policies.
- **Evaluation.** Golden tasks, golden cases, a metrics calculator, gate
  thresholds, and a regression detector. The evaluation service exposes
  an HTTP API for running gates as part of release validation.
- **Release automation.** A lifecycle state machine (planned → frozen →
  rc → validating → released → rolled_back), a pre-release checklist, a
  sync engine with dry-run support, and a rollback manager with a
  decision matrix.
- **Candidate ingestion.** A governed candidate → validated → published →
  revoked lifecycle for external assets, with confidence and trust
  labels. The mailbox seam lets external operators deposit events for
  asynchronous review.
- **Knowledge ingestion.** RSS, GitHub, web, and folder adapters with
  APScheduler cron support, so operators can keep a tenant's knowledge
  base current without writing custom ingest scripts.
- **MCP integration.** A hosted MCP server surface plus a client
  integration with circuit-breaker proxy semantics.

## Known limitations

These are explicit at launch and on the near-term roadmap.

- The default Kubernetes manifest is single-instance. The production
  overlay supports multi-replica deployment, but operators should review
  the state-boundary assumptions in `engine/src/agent33/lifespan/`
  before scaling out.
- Pack signing uses SHA-256 integrity verification. Asymmetric authorship
  signing (Sigstore cosign, keyless) is on the near-term roadmap.
- A handful of authenticated routes are not yet scoped per-tenant. The
  current scope matrix is documented in
  `docs/architecture/api-surface.md`.

These are tracked, not hidden. Issues and pull requests against any of
them are welcome.

## Getting started

The fastest path to a running engine is the Docker Compose stack:

```bash
git clone https://github.com/mattmre/AGENT33-PUBLIC.git
cd AGENT33-PUBLIC
docker compose up -d
```

For development install, follow `INSTALL.md`. For a guided tour of the
operator console and CLI, follow `QUICKSTART.md`. For the system-level
view, read `ARCHITECTURE.md` and the diagrams in `docs/architecture/`.

## Compatibility

- Python 3.11 or newer (3.12 supported).
- PostgreSQL 14+ with the `vector` extension.
- Redis 6+.
- NATS 2.10+.
- Optional: Ollama for local LLM inference.
- Optional: any OpenAI-compatible API endpoint.

## Contributors

Initial release engineering by the AGENT-33 maintainers. See `CONTRIBUTING.md`
for how to participate.

## Reporting issues

Bugs, security concerns, and feature requests go through GitHub Issues at
[mattmre/AGENT33-PUBLIC](https://github.com/mattmre/AGENT33-PUBLIC/issues).
Security-sensitive reports follow the disclosure process documented in
`SECURITY.md`.

---

Subsequent releases will be cut against the `main` branch on a
time-boxed cadence; see `docs/releasing.md` for the cadence and the full
release lifecycle.
