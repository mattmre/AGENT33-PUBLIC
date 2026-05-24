# Functionality and Workflows

This is the current behavior map for AGENT-33 on `main` as of February 15, 2026.

## 1. Runtime Architecture

Primary entry point:
- `engine/src/agent33/main.py`

Startup wiring initializes:
- PostgreSQL-backed `LongTermMemory`
- Redis client
- NATS bus
- Agent registry from `engine/agent-definitions`
- Model router + embedding provider/cache
- BM25 index + hybrid searcher + RAG pipeline
- Progressive recall
- Skill registry + skill injector
- Code executor bridge for workflow `execute-code` action

Routers mounted:
- Health, chat, agents, workflows, auth, webhooks, dashboard, memory, reviews, traces, evaluations, autonomy, releases, improvements, training

## 2. Capability Inventory

| Domain | Status | Notes |
| --- | --- | --- |
| Chat completions | Operational | `/v1/chat/completions` proxies to Ollama with injection scan |
| Agent registry + invoke | Operational | Registry discovery from JSON definitions; invoke supports skills + progressive recall injection |
| Workflow engine | Operational | Sequential/parallel/dependency-aware modes; 8 step actions (`invoke-agent`, `run-command`, `validate`, `transform`, `conditional`, `parallel-group`, `wait`, `execute-code`) |
| Memory + RAG | Operational | Vector + hybrid retrieval; progressive recall levels |
| Tool framework | Partial | Tool registry/governance exists, but full runtime bootstrap is not fully wired in `main.py` |
| Code execution layer | Partial | `CodeExecutor` wired, but starts with `tool_registry=None`; adapters must be registered explicitly |
| Review automation | Operational | In-memory two-layer signoff lifecycle |
| Trace + failure pipeline | Operational | In-memory trace collector and failure records |
| Evaluation + regression gates | Operational | In-memory evaluation runs, baselines, regression recorder |
| Autonomy budgets | Operational | In-memory budgets, preflight, runtime enforcement, escalations |
| Release automation | Operational | In-memory release lifecycle, sync rules/executions, rollback records |
| Improvement operations | Operational | In-memory intake, lessons, checklists, metrics, roadmap refresh |
| Messaging webhooks | Partial | Routes exist; adapters must be registered explicitly |
| Training APIs | Partial | Routes exist; default startup only initializes `training_store`, not full runner/optimizer wiring |

## 3. Persistence Boundaries

Persistent (database/backing service):
- `memory_records` via `LongTermMemory` (PostgreSQL + pgvector)
- Workflow registry and execution history (`api/routes/workflows.py`) via `OrchestrationStateStore` when `orchestration_state_store_path` is configured
- Workflow run archives, replay events, and extracted artifacts (`workflows/run_archive.py`) via the file-backed archive under `workflow_run_archive_dir`
- Review records (`review/service.py`) via `OrchestrationStateStore` when `orchestration_state_store_path` is configured
- Trace/failure records (`observability/trace_collector.py`) via `OrchestrationStateStore`
- Autonomy budgets/enforcers/escalations (`autonomy/service.py`) via `OrchestrationStateStore`
- Release records/sync/rollback state (`release/service.py`) via `OrchestrationStateStore`
- Improvement intakes/lessons/metrics/checklists/refreshes (`improvement/service.py`) via pluggable learning signal stores
- Approval tokens, tool approvals, process state, and mutation audit records via their configured state stores
- Training store tables (when `training_enabled` and initialized)
- Redis ephemeral cache/state
- NATS event transport

In-memory only (lost on restart):
- Evaluation runs/baselines/regressions (`evaluation/service.py` + recorder)
- Auth users and API keys (`api/routes/auth.py`, `security/auth.py`)
- Live workflow WebSocket snapshots/queues (`workflows/ws_manager.py`) before they are flushed into the run archive

## 4. Workflow Lifecycles

### 4.1 Review Lifecycle

States:
- `draft -> ready -> l1-review -> l1-approved -> (optional l2-review -> l2-approved) -> approved -> merged`

Main APIs:
- `/v1/reviews/{id}/assess`
- `/v1/reviews/{id}/assign-l1`
- `/v1/reviews/{id}/l1`
- `/v1/reviews/{id}/assign-l2`
- `/v1/reviews/{id}/l2`
- `/v1/reviews/{id}/approve`
- `/v1/reviews/{id}/merge`

### 4.2 Release Lifecycle

States:
- `planned -> frozen -> rc -> validating -> released`
- Failure/rollback branches: `failed`, `rolled_back`

Main APIs:
- `/v1/releases/{id}/freeze`
- `/v1/releases/{id}/rc`
- `/v1/releases/{id}/validate`
- `/v1/releases/{id}/publish`
- `/v1/releases/{id}/rollback`

### 4.3 Evaluation Lifecycle

Flow:
1. Create run (`/v1/evaluations/runs`)
2. Submit task results (`/runs/{id}/results`)
3. Compute metrics + gate report
4. Save baseline (`/runs/{id}/baseline`)
5. Triage/resolve regressions

### 4.4 Autonomy Budget Lifecycle

States:
- `draft -> pending_approval -> active -> suspended|expired|completed`

Flow:
1. Create budget
2. Activate or transition
3. Run preflight checks
4. Create enforcer
5. Evaluate command/file/network requests
6. Track escalations

### 4.5 Improvement Lifecycle

Research intake states:
- `submitted -> triaged -> analyzing -> accepted|deferred|rejected -> tracked`

Associated loops:
- Lesson capture and verification
- Periodic checklist completion
- Metrics snapshots and trend reporting
- Roadmap refresh records

### 4.6 Trace Lifecycle

States:
- `running -> completed|failed|cancelled`

Flow:
1. Start trace
2. Add step actions
3. Record failures if present
4. Complete trace

## 5. Known Integration Gaps

- `SessionSummarizer` is exposed via `session_summarizer_class` in startup, but `memory_search.summarize_session` expects `app.state.session_summarizer`.
- `ObservationCapture` is created without long-term memory/embedder bindings by default.
- Tool registry/governance exists but is not fully attached as an app-wide execution path during startup.
- Messaging adapters are not auto-registered in `webhooks._adapters` by default.
- Training routes expect `training_runner` and `agent_optimizer`; default startup only guarantees `training_store` when enabled.
- CLI `agent33 run` targets a legacy path (`/api/v1/workflows/run`) while workflow execution API is `/v1/workflows/{name}/execute`.

## 6. Pending and In-Progress Capabilities

The project is under active development, and some capabilities may be in progress on feature branches. This document reflects the current operational runtime on the active branch.

For historical context on development activity and capability evolution, refer to the PR review snapshot in `docs/pr-review-2026-02-15.md`. Note that the snapshot may not reflect the current state of open or merged pull requests.
