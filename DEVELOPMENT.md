# Development Guide

This guide is the working reference for anyone developing on AGENT-33. It covers the local dev loop, the engine layout, key conventions, and the gotchas that come up often enough to be worth writing down.

If you are looking for **how to install** AGENT-33 for use, see [`INSTALL.md`](INSTALL.md). If you are looking for **how to contribute changes**, see [`CONTRIBUTING.md`](CONTRIBUTING.md). This document assumes you have both of those open already.

## Table of Contents

1. [Quickstart](#1-quickstart)
2. [Repository Layout](#2-repository-layout)
3. [Production File: engine/src/agent33/main.py](#3-production-file-enginesrcagent33mainpy)
4. [Key Modules](#4-key-modules)
5. [Adding a New Feature](#5-adding-a-new-feature)
6. [Performance Tuning](#6-performance-tuning)
7. [Testing Locally](#7-testing-locally)
8. [Common Gotchas](#8-common-gotchas)
9. [Style and Conventions](#9-style-and-conventions)
10. [Further Reading](#10-further-reading)

---

## 1. Quickstart

```bash
git clone https://github.com/mattmre/AGENT33-PUBLIC.git
cd AGENT33-PUBLIC/engine
cp .env.example .env

python3.11 -m venv .venv
source .venv/bin/activate           # PowerShell: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Bring up the supporting infra (Postgres, Redis, NATS, Ollama)
docker compose up -d postgres redis nats ollama

# Run the test suite
python -m pytest tests/ -q

# Start the API locally against the running infra
uvicorn agent33.main:app --reload --host 0.0.0.0 --port 8000
```

Once the API is up, the CLI talks to it:

```bash
agent33 status
agent33 agents list
```

---

## 2. Repository Layout

```
AGENT33-PUBLIC/
├── engine/                       Python/FastAPI runtime (the actual software)
│   ├── src/agent33/              Engine package (subsystems live here)
│   ├── tests/                    Pytest suite
│   ├── alembic/                  DB migrations
│   ├── agent-definitions/        6 built-in agent JSON definitions
│   ├── pyproject.toml            Package metadata + lint/type config
│   ├── docker-compose.yml        Full local stack (api + infra)
│   └── .env.example              Config template (env-var driven)
├── core/                         Markdown-native specs and templates
│   ├── workflows/                Canonical workflow YAMLs (imported by engine)
│   ├── orchestrator/             Orchestrator rules + agent protocols
│   └── arch/                     Architecture conventions and templates
├── docs/                         Documentation suite
│   ├── architecture/             Component, data-flow, multi-tenancy, MCP, security
│   ├── operators/                Operator runbooks (deploy, scale, incident)
│   ├── runbooks/                 Targeted runbooks (secret rotation, etc.)
│   ├── api-reference.md          REST endpoint reference
│   ├── cli-reference.md          `agent33` CLI command reference
│   ├── configuration.md          Every env var
│   ├── troubleshooting.md        Common deployment + runtime issues
│   └── getting-started.md        First-run walkthrough
├── deploy/                       Deployment artifacts
│   ├── k8s/base/                 Kustomize base for production K8s
│   ├── k8s/overlays/production/  Production overlay
│   └── monitoring/               Prometheus rules + Grafana dashboard
└── .github/                      Issue templates, PR template, CI workflows
```

### Top-Level Files

- `README.md` — Public landing page
- `ARCHITECTURE.md` — Top-level architecture
- `INSTALL.md` — Installation guide
- `QUICKSTART.md` — Short path to a running agent
- `CONTRIBUTING.md` — Contribution guidelines
- `DEVELOPMENT.md` — This file
- `SUPPORT.md` — Help-routing landing page
- `CHANGELOG.md` — Release history
- `RELEASE_NOTES.md` — Current release notes
- `SECURITY.md` — Security disclosure policy
- `CODE_OF_CONDUCT.md` — Community standards
- `LICENSE` — Apache 2.0
- `CITATION.cff` — Citation metadata

---

## 3. Production File: engine/src/agent33/main.py

**`engine/src/agent33/main.py` is the FastAPI entry point.** It defines the `app` instance and the lifespan that initializes every subsystem. Unlike a monolith, AGENT-33 has no single "pipeline file" — instead the lifespan wires a deterministic chain of subsystems onto `app.state`, and routes pull what they need via `Depends`.

### Lifespan Initialization Order

The order is deliberate — each step depends on prior ones being on `app.state`:

```
PostgreSQL
  → Redis
  → NATS
  → AgentRegistry            (auto-discovers JSON defs from agent-definitions/)
  → CodeExecutor             (sandboxed execution adapters)
  → ModelRouter              (provider catalog, 22+ providers)
  → EmbeddingProvider + EmbeddingCache
  → BM25Index
  → HybridSearcher           (vector + BM25 via RRF)
  → RAGPipeline
  → ProgressiveRecall
  → SkillRegistry + SkillInjector
  → Agent-Workflow Bridge    (workflow actions → agent runtime)
  → AirLLM                   (optional, large-model offload)
  → Memory                   (ObservationCapture, SessionSummarizer)
  → Training                 (optional, learning loops)
```

Shutdown is the reverse order. If you add a subsystem, the rule is: **start last, stop first** unless there is a dependency reason to do otherwise.

### When You Need to Modify `main.py`

- **Subsystems live on `app.state`** — routes resolve them via `Depends(get_<subsystem>)`. Never reach across module boundaries to a module-level singleton.
- **The lifespan is the only place that constructs production singletons.** Tests construct their own instances via fixtures.
- **PRs that change lifespan ordering should justify the move.** Out-of-order init has historically caused phantom test failures and "phantom" service unavailability.

---

## 4. Key Modules

The engine is organized by subsystem. Each directory under `engine/src/agent33/` is one bounded context.

### Core Runtime

| Module | Path | Purpose |
|---|---|---|
| Agents | `agents/` | Registry, runtime, archetypes, capabilities, tool loop |
| Workflows | `workflows/` | DAG engine, step executor, actions (invoke_agent, validate, parallel_group, etc.) |
| Skills | `skills/` | SkillDefinition + SKILL.md loader + L0/L1/L2 progressive disclosure injector |
| Packs | `packs/` | Pack loader, registry, hub client, sharing service |
| Tools | `tools/` | Tool framework, JSON Schema validation, governance allowlist, builtins |
| LLM | `llm/` | Provider abstraction (Ollama, OpenAI-compatible), ModelRouter |
| Memory | `memory/` | Short-term + pgvector long-term store, embeddings, BM25, hybrid RAG |
| Execution | `execution/` | Code execution layer, SandboxConfig, CLIAdapter, IV-01..05 validation |

### Operational

| Module | Path | Purpose |
|---|---|---|
| Messaging | `messaging/` | Telegram/Discord/Slack/WhatsApp via NATS, per-channel health checks |
| Observability | `observability/` | Tracing, metrics, lineage, replay, failure taxonomy |
| Evaluation | `evaluation/` | Golden tasks, golden cases, metric calculators, regression gates |
| Autonomy | `autonomy/` | Budget lifecycle, preflight checks (PF-01..PF-10), runtime enforcer |
| Release | `release/` | Release lifecycle, sync engine, rollback manager |
| Knowledge | `knowledge/` | RSS/GitHub/web/folder ingestion + APScheduler cron |
| Review | `review/` | Two-layer review automation, signoff state machine |
| Improvement | `improvement/` | Research intake, lessons learned, improvement checklists |

### Platform

| Module | Path | Purpose |
|---|---|---|
| API | `api/` | FastAPI routes (per-subsystem), middleware, auth |
| Security | `security/` | JWT/API-key auth, AuthMiddleware, encryption, prompt injection detection |
| Automation | `automation/` | APScheduler, webhooks, dead-letter queue, event sensors |
| MCP | `mcp_server/` | Model Context Protocol server + sync |
| CLI | `cli/` | `agent33` command-line interface |
| Outcomes | `outcomes/` | Outcome logging + SQLite persistence (P68-Lite) |
| Plugins | `plugins/` | Plugin loader and lifecycle hooks |

---

## 5. Adding a New Feature

Use this checklist when adding a new feature module.

1. **Pick the subsystem directory.** If it does not fit existing subsystems, propose the new directory in the PR description and link an ADR under `docs/architecture/`.
2. **Add the subsystem in `lifespan`.** Construct in dependency order, attach to `app.state`, register shutdown.
3. **Expose via routes under `api/routes/`.** Use `Depends(get_<subsystem>)` — do not reach into `app.state` directly in route handlers.
4. **Add config knobs to `config.py`.** Pydantic Settings; env-var names map to upper-case field names.
5. **Add Alembic migration** if you introduce a new table — `engine/alembic/versions/`. All tables get `tenant_id`.
6. **Add unit tests** in `tests/test_<feature>.py` that exercise behavior, not just route existence.
7. **Add an integration test** in `tests/test_integration_<feature>.py` that runs the feature against the lifespan-initialized app.
8. **Add an agent definition or workflow** if the feature is user-facing — `engine/agent-definitions/*.json` or `core/workflows/*.yaml`.
9. **Document the feature** in `docs/configuration.md` (env vars), `docs/api-reference.md` (routes), and `docs/cli-reference.md` (CLI commands).
10. **Update the changelog** with the feature under "Added".

### Adding a New Workflow

Workflows are YAML and live in `core/workflows/`. They are imported by the engine via the workflow bridge.

1. Add the YAML to `core/workflows/capability-packs/` (or the appropriate subdirectory).
2. Use only action types registered in `engine/src/agent33/workflows/actions/` (invoke_agent, run_command, validate, transform, conditional, parallel_group, wait, execute_code).
3. Step IDs must use **underscores, not hyphens** — Jinja2 treats hyphens as subtraction and silently breaks template resolution.
4. Add a test in `tests/test_workflow_<name>.py` that loads the YAML and asserts the expected DAG.

### Adding a New Agent Definition

1. Add a JSON file under `engine/agent-definitions/`.
2. Match the schema in `engine/src/agent33/agents/definition.py`.
3. Capabilities must come from the taxonomy in `engine/src/agent33/agents/capabilities.py` (25 entries across P/I/V/R/X categories).
4. The registry auto-discovers at lifespan startup — no manual registration needed.

---

## 6. Performance Tuning

The engine ships with conservative defaults. Tuning is via environment variables (or `.env`):

| Variable | Default | Notes |
|---|---|---|
| `WORKER_CONCURRENCY` | `4` | uvicorn workers for the API |
| `BM25_WARMUP_ENABLED` | `true` | Warm the BM25 index at lifespan startup |
| `EMBEDDING_CACHE_SIZE` | `1024` | LRU entries for the embedding cache |
| `CHUNK_TOKEN_SIZE` | `1200` | Token-aware chunking size for ingestion |
| `RAG_TOP_K` | `8` | Final result count from hybrid retriever |
| `MODEL_ROUTER_TIMEOUT_S` | `60` | Per-provider request timeout |
| `CODE_EXECUTION_TIMEOUT_S` | `30` | Sandbox execution wall-clock timeout |

For pgvector index tuning and DB-level knobs, see `docs/operators/horizontal-scaling-architecture.md`.

For Kubernetes, the same envs are surfaced via the `api-configmap.yaml` under `deploy/k8s/base/`.

---

## 7. Testing Locally

All test commands run from `engine/`.

### Run All Tests

```bash
python -m pytest tests/ -q
```

### Run Targeted Tests

```bash
python -m pytest tests/test_execution_executor.py -q
python -m pytest tests/ -k "test_tool_loop" -q
python -m pytest tests/ -x -q                       # stop on first failure
```

### Lint and Type Check

```bash
python -m ruff check src/ tests/
python -m ruff format --check src/ tests/           # parity check; CI runs both
python -m mypy src --config-file pyproject.toml
```

`ruff check` and `ruff format --check` are not the same — CI runs both. Always run both locally before pushing.

### Smoke the Running Stack

```bash
docker compose up -d
agent33 status
curl http://localhost:8000/healthz
```

### CLI Tests

```bash
python -m pytest tests/cli/ -q
```

---

## 8. Common Gotchas

A curated list of issues you will hit if you do not know about them.

### Gotchas — Python and Build

1. **Python 3.11+ is the floor.** `requires-python = ">=3.11"` in `pyproject.toml`. 3.10 will fail on `match` statements and modern typing syntax.
2. **Editable install drift across worktrees.** If you have multiple git worktrees, an editable `agent33` install can point at the wrong sibling checkout. The fix is a worktree-local venv: `cd engine && python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"`. As a fallback, set `PYTHONPATH=<active-worktree>/engine/src`.
3. **`ruff check` vs `ruff format --check` parity.** CI runs both. `check` is the linter; `format --check` is the formatter dry-run. Run both locally before pushing.

### Gotchas — Infrastructure

4. **pgvector is required.** The default Postgres image is not enough — use `pgvector/pgvector:pg16` (the compose file already does). Long-term memory and RAG will fail at startup without it.
5. **Ollama runs on the Docker network, not localhost.** Inside containers, point at `http://ollama:11434`, not `http://localhost:11434`. The `.env.example` has the right default.
6. **JWT secret rotation is destructive.** Existing tokens are invalidated when `JWT_SECRET` changes. In production, rotate via the documented secret-rotation runbook (`docs/runbooks/secret-rotation.md`), not by editing `.env`.

### Gotchas — Multi-Tenancy

7. **All DB models have `tenant_id`.** Tests that issue raw SQL or skip auth middleware will get rows from "tenant `default`" only — or 401 if auth is enforced. New tables must include `tenant_id` and a tenant-scoped index.
8. **`tenant_id` propagation lives in `AuthMiddleware`.** If you add a new transport (WebSocket, SSE), the tenant must be resolved on connect, not per-message.

### Gotchas — Tests

9. **BM25 warmup can break lifespan fixtures.** Tests that mock `LongTermMemory.initialize()` but not `scan()` will fail in the warmup path with `bm25_warmup_enabled=True`. Either mock `scan` with `AsyncMock(return_value=[])` or set `BM25_WARMUP_ENABLED=false` for the test.
10. **Windows console encoding can mask the real failure.** On a non-UTF-8 code page, `structlog` `exc_info=True` raises `UnicodeEncodeError` and hides the underlying test/runtime problem. Set `PYTHONIOENCODING=utf-8` before running pytest on Windows.
11. **Async test conversion.** If you convert a service method from sync to `async`, tests that call it directly (not via `TestClient`) must also become `async def`. Missing `await` shows up as `RuntimeWarning: coroutine was never awaited` and `AttributeError` on the return value.
12. **Shared `app.state` in async API tests.** `httpx.ASGITransport(app=app)` plus the module-level FastAPI `app` can hide missing lifespan-initialized services. Install critical services explicitly in fixtures instead of relying on prior suite order.

### Gotchas — Operations

13. **`config.py` validates the JWT secret on startup.** In production, a default JWT secret triggers `SystemExit` via `@model_validator(mode="after")`. Override `JWT_SECRET` before bringing prod up.
14. **`SecretStr` fields are not strings.** Callers must use `.get_secret_value()`. Tests that mock settings must construct with `SecretStr("value")`, not a plain string.
15. **Workflow step IDs use underscores, not hyphens.** Jinja2 treats `step-1` as subtraction (`step` minus `1`) and silently breaks template resolution.

---

## 9. Style and Conventions

### Python

- **PEP 8** with `ruff` enforcement (line-length 99, target py311).
- **Rule sets**: E, F, W, I, N, UP, B, A, SIM, TCH.
- **`from __future__ import annotations`** at the top of new modules.
- **Type hints** on every public surface; `mypy --strict` is the bar.
- **No emojis** in code, comments, or commit messages.
- **`logger = structlog.get_logger(__name__)`** at module top.
- **Lazy log args**: `logger.info("text", value=value)` — never f-string a log call.

### YAML / JSON

- Two-space indentation.
- Workflow step IDs use underscores, not hyphens.
- Agent definition `capabilities` come from the taxonomy in `agents/capabilities.py`.

### Markdown

- **Plain English.** Define jargon on first use.
- **No emojis** in documentation.
- Headings start at H1; subsections nest from there.

### Commits

- Conventional Commits format: `type(scope): summary`.
- Wrap message body at 72 columns.
- No AI co-author footers unless explicitly requested.

### Git

- Cut feature branches from **fresh `origin/main`**:
  ```bash
  git fetch origin
  git checkout -b feat/xxx origin/main
  ```
- Never reuse a merged branch. (Branch tracking can mislead about state.)
- Squash-merge PRs to `main`.
- Tag releases as `v<MAJOR>.<MINOR>.<PATCH>` (for example `v2.1.0`).

### Pytest

- `asyncio_mode = "auto"` is set in `pyproject.toml` — do not decorate every async test.
- `testpaths = ["tests"]` — keep tests under `engine/tests/`.
- Tests must assert on behavior, not just route existence or generic error codes.

---

## 10. Further Reading

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — top-level architecture
- [`docs/architecture/overview.md`](docs/architecture/overview.md) — system overview
- [`docs/api-reference.md`](docs/api-reference.md) — every REST endpoint
- [`docs/cli-reference.md`](docs/cli-reference.md) — every `agent33` command
- [`docs/configuration.md`](docs/configuration.md) — every env var
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — common deployment + runtime issues
- [`docs/architecture/multi-tenancy.md`](docs/architecture/multi-tenancy.md) — tenant model and isolation
- [`docs/architecture/security-model.md`](docs/architecture/security-model.md) — auth, secrets, sandboxing
