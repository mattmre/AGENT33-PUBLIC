# Feature Implementation Roadmap

Status of all competitive features (CA-007 through CA-065) in the engine, grouped by cluster. Each entry shows the feature ID, name, implementation status, engine module, and notes.

Status legend:
- **Implemented** -- Code exists and is functional.
- **Partial** -- Core logic exists but not all spec requirements are met.
- **Planned** -- Spec complete, implementation not yet started.

---

## Foundational Features (CA-007 to CA-017)

| ID | Feature | Status | Engine Module | Notes |
|----|---------|--------|---------------|-------|
| CA-007 | Incremental Detection | Partial | `automation/sensors/file_change.py` | File-change sensor implemented; full artifact-graph diffing not yet wired |
| CA-008 | Parallel Execution | Implemented | `workflows/dag.py`, `workflows/executor.py`, `workflows/actions/parallel_group.py` | DAG topological sort with concurrent step execution |
| CA-009 | Change Triggers | Implemented | `automation/sensors/`, `automation/webhooks.py` | File, event, freshness sensors plus webhook ingress |
| CA-010 | Configuration Schemas | Implemented | `agents/definition.py`, `workflows/definition.py` | Pydantic models enforce schema validation |
| CA-011 | Execution Modes | Partial | `workflows/executor.py` | Sequential and parallel modes; dry-run mode planned |
| CA-012 | MDC Rules | Planned | -- | Rules exist in `core/packs/mdc-rules/`; engine loader not yet built |
| CA-013 | Artifact Filtering | Partial | `automation/sensors/file_change.py` | Glob-based filtering in sensor; dedicated filter module planned |
| CA-014 | Dependency Graphs | Implemented | `workflows/dag.py` | `DAG` class with topological sort and cycle detection |
| CA-015 | Analytics and Metrics | Implemented | `observability/metrics.py`, `api/routes/dashboard.py` | Counters, histograms, dashboard API |
| CA-016 | Config Generation | Planned | -- | Spec exists; CLI generator not yet implemented |
| CA-017 | Platform Integrations | Implemented | `messaging/telegram.py`, `messaging/discord.py`, `messaging/slack.py`, `messaging/whatsapp.py` | Four channel adapters with unified base |

---

## Cluster 1: Workflow Definition (CA-018 to CA-030)

| ID | Feature | Status | Engine Module | Notes |
|----|---------|--------|---------------|-------|
| CA-018 | Asset-First Workflow Schema | Implemented | `workflows/definition.py` | Workflows defined as asset DAGs with inputs/outputs |
| CA-019 | DAG-Based Stage Execution | Implemented | `workflows/dag.py`, `workflows/executor.py` | Full DAG execution with fork-join |
| CA-020 | Expression Language | Implemented | `workflows/expressions.py` | `ExpressionEvaluator` for dynamic step parameters |
| CA-021 | Task Definition Registry | Implemented | `agents/registry.py`, `tools/registry.py` | Agents and tools registered by ID and capability |
| CA-022 | Dynamic Fork-Join | Implemented | `workflows/actions/parallel_group.py`, `workflows/dag.py` | Parallel group action handles fan-out/fan-in |
| CA-023 | Freshness Policies | Implemented | `automation/sensors/freshness.py` | `FreshnessSensor` triggers on stale assets |
| CA-024 | Partition Definitions | Partial | `workflows/definition.py` | Schema supports partitions; runtime partitioning planned |
| CA-025 | IO Manager Abstraction | Partial | `workflows/actions/transform.py` | Transform action handles IO; dedicated IO manager planned |
| CA-026 | Pipeline Templates | Implemented | `workflows/definition.py` | Workflow definitions serve as reusable templates |
| CA-027 | Sub-Workflow Composition | Implemented | `workflows/executor.py` | Executor supports nested workflow invocation |
| CA-028 | Conditional Branching | Implemented | `workflows/actions/conditional.py` | `ConditionalAction` with expression evaluation |
| CA-029 | Event-Driven Triggers | Implemented | `automation/sensors/event.py`, `automation/webhooks.py` | Event sensor plus webhook-triggered workflows |
| CA-030 | Workflow Versioning | Partial | `workflows/definition.py` | Version field on definitions; migration tooling planned |

---

## Cluster 2: Agent Coordination (CA-031 to CA-040)

| ID | Feature | Status | Engine Module | Notes |
|----|---------|--------|---------------|-------|
| CA-031 | Agent Handoff Protocol | Implemented | `agents/runtime.py` | `AgentRuntime.handoff()` with context transfer |
| CA-032 | Communication Flow Schema | Implemented | `messaging/bus.py`, `messaging/models.py` | Typed message models with pub/sub bus |
| CA-033 | Guardrails / Validation Hooks | Implemented | `tools/governance.py`, `security/injection.py` | Tool governance + injection detection |
| CA-034 | Context Variables | Implemented | `memory/context.py`, `memory/session.py` | Context builder assembles agent state |
| CA-035 | Agent Discovery | Implemented | `agents/registry.py` | `AgentRegistry.discover()` by capability |
| CA-036 | Delegation Patterns | Implemented | `agents/runtime.py` | Handoff-based delegation between agents |
| CA-037 | Multi-Agent Routing | Implemented | `llm/router.py`, `agents/registry.py` | LLM router + registry resolve agent per task |
| CA-038 | Agent Memory / State | Implemented | `memory/short_term.py`, `memory/long_term.py`, `memory/session.py` | Short-term, long-term, and session memory |
| CA-039 | Tool Sharing Between Agents | Implemented | `tools/registry.py`, `tools/governance.py` | Shared registry with per-agent allowlists |
| CA-040 | Agent Lifecycle Management | Implemented | `agents/runtime.py` | Runtime manages init, execution, teardown |

---

## Cluster 3: State Machines and Decision (CA-041 to CA-050)

| ID | Feature | Status | Engine Module | Notes |
|----|---------|--------|---------------|-------|
| CA-041 | Statechart Workflow Format | Implemented | `workflows/state_machine.py` | `StateMachine`, `State`, `Transition` |
| CA-042 | Decision Routing | Implemented | `workflows/actions/conditional.py`, `llm/router.py` | Conditional actions + LLM-based routing |
| CA-043 | Backpressure | Partial | `workflows/executor.py` | Basic concurrency limits; full backpressure signaling planned |
| CA-044 | BPMN Process Modeling | Planned | -- | Spec exists in statechart format; BPMN import not built |
| CA-045 | Parallel Regions | Implemented | `workflows/state_machine.py` | State machine supports parallel states |
| CA-046 | History States | Partial | `workflows/state_machine.py`, `workflows/checkpoint.py` | Checkpoint enables resume; deep history planned |
| CA-047 | Machine Composition | Implemented | `workflows/state_machine.py` | Nested state machine composition |
| CA-048 | Synthetic Stage Composition | Implemented | `workflows/dag.py` | DAG supports synthetic grouping nodes |
| CA-049 | Canary Execution | Planned | -- | Spec exists; canary executor not yet built |
| CA-050 | Timer / Delay Transitions | Implemented | `workflows/actions/wait.py` | `WaitAction` with duration and deadline modes |

---

## Cluster 4: Observability and Testing (CA-051 to CA-060)

| ID | Feature | Status | Engine Module | Notes |
|----|---------|--------|---------------|-------|
| CA-051 | Lineage Tracking | Implemented | `observability/lineage.py` | `LineageTracker` records full execution graph |
| CA-052 | Artifact Sensors | Implemented | `automation/sensors/file_change.py`, `automation/sensors/freshness.py` | File and freshness sensors |
| CA-053 | Health Dashboard | Implemented | `observability/metrics.py`, `observability/alerts.py`, `api/routes/dashboard.py` | Metrics, alerts, and dashboard API |
| CA-054 | Workflow Testing Framework | Implemented | `testing/workflow_harness.py`, `testing/agent_harness.py` | Harnesses for workflow and agent testing |
| CA-055 | Plugin Registry | Implemented | `plugins/loader.py` | `PluginLoader` with discovery and hot-loading |
| CA-056 | Visual DAG Rendering | Planned | -- | Lineage graph exists; visual renderer not built |
| CA-057 | Execution Replay | Implemented | `observability/replay.py` | `ExecutionReplayer` for post-mortem analysis |
| CA-058 | Model-Based Testing | Partial | `testing/workflow_harness.py`, `testing/mock_llm.py` | Mock LLM enables deterministic tests; state model testing planned |
| CA-059 | Structured Event Logging | Implemented | `observability/logging.py` | JSON structured logger |
| CA-060 | Cost Tracking | Partial | `observability/metrics.py` | Token counts tracked; dollar-cost attribution planned |

---

## Cluster 5: Distribution and Governance (CA-061 to CA-065)

| ID | Feature | Status | Engine Module | Notes |
|----|---------|--------|---------------|-------|
| CA-061 | Distribution and Sync | Planned | -- | Spec at `core/orchestrator/distribution/`; no engine code yet |
| CA-062 | Community Governance | Planned | -- | Spec at `core/orchestrator/community/`; no engine code yet |
| CA-063 | Platform Integrations | Implemented | `messaging/`, `security/vault.py` | Channel adapters + credential management |
| CA-064 | Security Analysis | Implemented | `security/` | Full security package (vault, encryption, auth, injection) |
| CA-065 | Feature Parity Analysis | Implemented | -- | Research doc; no direct engine code (analysis artifact) |

---

## Additional Engine Features (Beyond CA Index)

| Feature | Engine Module | Notes |
|---------|---------------|-------|
| RAG / Retrieval-Augmented Generation | `memory/rag.py`, `memory/embeddings.py`, `memory/ingestion.py` | Full RAG pipeline with embedding, ingestion, and retrieval |
| Tool Governance | `tools/governance.py` | Approval workflows, risk tiers, audit logging |
| Dead-Letter Queue | `automation/dead_letter.py` | Failed sensor events queued for retry or inspection |
| Device Pairing | `messaging/pairing.py` | QR/code-based device linking for messaging channels |
| Retention Policies | `memory/retention.py` | Automated memory cleanup by age and relevance |
| HTTP Security Middleware | `security/middleware.py` | CORS, rate limiting, header validation |
| Distributed Tracing | `observability/tracing.py` | Span propagation across agent calls |
| Built-in Tools | `tools/builtin/` | Shell, file operations, web fetch, browser |

---

## Summary

| Status | Count |
|--------|-------|
| Implemented | 42 |
| Partial | 12 |
| Planned | 5 |

---

## Future Roadmap

The following capabilities are planned beyond the current CA feature set:

### Horizontal Scaling
- Distributed workflow executor with task queues (Redis/NATS).
- Multi-node agent runtime with load balancing.
- Sharded memory stores for high-throughput RAG.

### Model Fine-Tuning
- Agent-specific fine-tuning pipeline for specialized tasks.
- Feedback loop from observability metrics to training data.
- LoRA adapter management per agent role.

### Visual Workflow Editor
- Browser-based DAG editor with drag-and-drop steps.
- Live preview of expression evaluation.
- Real-time execution monitoring overlay.
- Export to `workflow.json` definitions.

### Marketplace
- Community-contributed agent definitions and workflow templates.
- Plugin marketplace with versioning and reviews.
- Tool sharing across organizations.
- One-click deploy of published workflows.

### Additional Planned Work
- BPMN import/export (CA-044).
- Canary execution with traffic splitting (CA-049).
- Full dry-run mode for all workflow types (CA-011).
- Dollar-cost attribution in analytics (CA-060).
- Distribution and sync protocol (CA-061).
- Community governance framework (CA-062).
