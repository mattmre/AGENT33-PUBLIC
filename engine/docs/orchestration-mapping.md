# Orchestration Mapping: Core Specs to Engine Implementation

This document maps every concept defined in `core/orchestrator/` to its concrete implementation in the `engine/` Python package. Use it to trace any spec requirement to the code that fulfills it.

## How to Read This Document

Each section follows the format:

```
Core Spec Path  ->  Engine Module Path  ->  Key Classes / Functions
```

---

## 1. Agent Roles and Routing

The core defines 10 agent roles (Director, Orchestrator, Implementer, QA, Reviewer, Researcher, Documentation, Security, Architect, Test Engineer) in the Agent Routing Map and Agent Registry.

| Core Spec | Engine Module | Key Classes / Functions |
|-----------|---------------|------------------------|
| `core/orchestrator/AGENT_ROUTING_MAP.md` | `agents/registry.py` | `AgentRegistry`, `AgentRegistry.resolve_by_task_type()`, `AgentRegistry.get()` |
| `core/orchestrator/AGENT_REGISTRY.md` | `agents/definition.py` | `AgentDefinition` dataclass (name, version, role, capabilities, constraints) |
| `core/packs/policy-pack-v1/AGENTS.md` | `agents/runtime.py` | `AgentRuntime` -- instantiates an agent with its LLM, tools, and memory |
| `core/orchestrator/agent-protocols/AGENT_HANDOFF_PROTOCOL.md` | `agents/runtime.py` | `AgentRuntime.handoff()`, `AgentRuntime.receive_context()` |
| `core/orchestrator/agent-protocols/COMMUNICATION_FLOW_SCHEMA.md` | `messaging/bus.py` | `MessageBus.publish()`, `MessageBus.subscribe()` |

### Role-to-Definition Mapping

| Core Role (AGT-ID) | Engine Agent Kind | Defined In |
|---------------------|-------------------|------------|
| Director (AGT-002) | `role: "director"` | `agents/definition.py` |
| Orchestrator (AGT-001) | `role: "orchestrator"` | `agents/definition.py` |
| Implementer (AGT-003) | `role: "worker"` | `agents/definition.py` |
| QA (AGT-004) | `role: "worker"` | `agents/definition.py` |
| Reviewer (AGT-005) | `role: "reviewer"` | `agents/definition.py` |
| Researcher (AGT-006) | `role: "worker"` | `agents/definition.py` |
| Documentation (AGT-007) | `role: "worker"` | `agents/definition.py` |
| Security (AGT-008) | `role: "reviewer"` | `agents/definition.py` |
| Architect (AGT-009) | `role: "reviewer"` | `agents/definition.py` |
| Test Engineer (AGT-010) | `role: "worker"` | `agents/definition.py` |

---

## 2. Handoff Protocol

The core handoff system uses STATUS, PLAN, TASKS, and DECISIONS documents to pass context between sessions and agents.

| Core Spec | Engine Module | Key Classes / Functions |
|-----------|---------------|------------------------|
| `core/orchestrator/handoff/STATUS.md` | `workflows/checkpoint.py` | `WorkflowCheckpoint` -- serializes workflow state between runs |
| `core/orchestrator/handoff/PLAN.md` | `workflows/definition.py` | `WorkflowDefinition` -- the plan expressed as a workflow DAG |
| `core/orchestrator/handoff/TASKS.md` | `workflows/dag.py` | `DAGNode` -- individual task with inputs, outputs, acceptance criteria |
| `core/orchestrator/handoff/DECISIONS.md` | `observability/lineage.py` | `LineageTracker.record_decision()` -- captures decision rationale |
| `core/orchestrator/handoff/REVIEW_CAPTURE.md` | `observability/lineage.py` | `LineageTracker.record_review()` |
| `core/orchestrator/handoff/SESSION_WRAP.md` | `workflows/checkpoint.py` | `WorkflowCheckpoint.save()` -- persists state at session end |

---

## 3. Tool Governance

| Core Spec | Engine Module | Key Classes / Functions |
|-----------|---------------|------------------------|
| `core/orchestrator/TOOL_GOVERNANCE.md` | `tools/governance.py` | `ToolGovernance` -- enforces approval, audit, and risk tiers |
| `core/orchestrator/TOOLS_AS_CODE.md` | `tools/registry.py` | `ToolRegistry` -- declarative tool registration and discovery |
| Tool allowlists (per-agent) | `security/allowlists.py` | `Allowlist`, `check_tool_allowed()` |
| `core/orchestrator/QWEN_CODE_TOOL_PROTOCOL.md` | `tools/base.py` | `BaseTool` -- base class with `execute()`, `validate_inputs()` |
| Built-in tools | `tools/builtin/` | `shell.py`, `file_ops.py`, `web_fetch.py`, `browser.py` |

---

## 4. Agent Routing and LLM Selection

| Core Spec | Engine Module | Key Classes / Functions |
|-----------|---------------|------------------------|
| `core/orchestrator/AGENT_ROUTING_MAP.md` | `llm/router.py` | `LLMRouter` -- selects provider based on task type and agent constraints |
| Model-agnostic principle | `llm/base.py` | `BaseLLM` -- abstract interface; swap OpenAI/Ollama without code changes |
| Provider: OpenAI | `llm/openai.py` | `OpenAIProvider` |
| Provider: Ollama (local) | `llm/ollama.py` | `OllamaProvider` |
| Agent discovery (CA-035) | `agents/registry.py` | `AgentRegistry.discover()`, `AgentRegistry.list_by_capability()` |

---

## 5. Workflow Engine

| Core Spec | Engine Module | Key Classes / Functions |
|-----------|---------------|------------------------|
| `core/orchestrator/workflows/DAG_EXECUTION_ENGINE.md` | `workflows/dag.py` | `DAG`, `DAGNode`, `DAG.topological_sort()` |
| DAG execution | `workflows/executor.py` | `WorkflowExecutor.run()`, `WorkflowExecutor.run_parallel()` |
| `core/orchestrator/workflows/ASSET_FIRST_WORKFLOW_SCHEMA.md` | `workflows/definition.py` | `WorkflowDefinition`, `StepDefinition` |
| `core/orchestrator/workflows/EXPRESSION_LANGUAGE_SPEC.md` | `workflows/expressions.py` | `ExpressionEvaluator`, `evaluate()` |
| `core/orchestrator/statecharts/STATECHART_WORKFLOW_FORMAT.md` | `workflows/state_machine.py` | `StateMachine`, `State`, `Transition` |
| `core/orchestrator/statecharts/BACKPRESSURE_SPEC.md` | `workflows/executor.py` | Backpressure handling in `WorkflowExecutor` |
| Checkpoint / resume | `workflows/checkpoint.py` | `WorkflowCheckpoint.save()`, `.load()`, `.resume()` |
| Workflow actions | `workflows/actions/` | `invoke_agent.py`, `run_command.py`, `validate.py`, `transform.py`, `conditional.py`, `parallel_group.py`, `wait.py` |

---

## 6. Sensors and Triggers (Automation)

| Core Spec | Engine Module | Key Classes / Functions |
|-----------|---------------|------------------------|
| `core/orchestrator/triggers/TRIGGER_CATALOG.md` | `automation/sensors/` | Sensor base + concrete sensors |
| File-change triggers | `automation/sensors/file_change.py` | `FileChangeSensor` |
| Freshness policies (CA-023) | `automation/sensors/freshness.py` | `FreshnessSensor` |
| Event-driven triggers (CA-029) | `automation/sensors/event.py` | `EventSensor` |
| Sensor registry | `automation/sensors/registry.py` | `SensorRegistry` |
| Webhook triggers | `automation/webhooks.py` | `WebhookHandler`, API route in `api/routes/webhooks.py` |
| Cron / scheduled triggers | `automation/scheduler.py` | `Scheduler`, `CronTrigger` |
| Dead-letter handling | `automation/dead_letter.py` | `DeadLetterQueue` |

---

## 7. Observability

| Core Spec | Engine Module | Key Classes / Functions |
|-----------|---------------|------------------------|
| `core/orchestrator/analytics/METRICS_CATALOG.md` | `observability/metrics.py` | `MetricsCollector`, `Counter`, `Histogram` |
| `core/orchestrator/lineage/LINEAGE_TRACKING_SPEC.md` | `observability/lineage.py` | `LineageTracker`, `LineageGraph` |
| `core/orchestrator/observability/HEALTH_DASHBOARD_SPEC.md` | `api/routes/dashboard.py` | Dashboard API route; `observability/alerts.py` for alert rules |
| Structured event logging | `observability/logging.py` | Structured JSON logger |
| Distributed tracing | `observability/tracing.py` | `TracingMiddleware`, span context propagation |
| Execution replay (CA-057) | `observability/replay.py` | `ExecutionReplayer` |
| Alerts | `observability/alerts.py` | `AlertRule`, `AlertManager` |

---

## 8. Security Hardening

| Core Spec | Engine Module | Key Classes / Functions |
|-----------|---------------|------------------------|
| `core/packs/policy-pack-v1/rules/security.md` | `security/` | Full security package |
| Secrets management | `security/vault.py` | `Vault`, `Vault.get_secret()`, `Vault.set_secret()` |
| Encryption at rest | `security/encryption.py` | `encrypt()`, `decrypt()`, key rotation |
| Authentication | `security/auth.py` | `authenticate()`, token validation |
| Authorization / RBAC | `security/permissions.py` | `PermissionChecker`, `Role`, `check_permission()` |
| Prompt injection defense | `security/injection.py` | `InjectionDetector`, `sanitize_input()` |
| Tool allowlists | `security/allowlists.py` | `Allowlist`, per-agent tool restrictions |
| HTTP security middleware | `security/middleware.py` | CORS, rate limiting, header validation |
| Credential management (CA-063) | `security/vault.py` | Credential rotation and scoping |

---

## 9. Integration and Messaging

| Core Spec | Engine Module | Key Classes / Functions |
|-----------|---------------|------------------------|
| `core/orchestrator/integrations/CHANNEL_INTEGRATION_SPEC.md` | `messaging/` | Full messaging package |
| Telegram | `messaging/telegram.py` | `TelegramAdapter` |
| Discord | `messaging/discord.py` | `DiscordAdapter` |
| Slack | `messaging/slack.py` | `SlackAdapter` |
| WhatsApp | `messaging/whatsapp.py` | `WhatsAppAdapter` |
| Base adapter interface | `messaging/base.py` | `BaseMessagingAdapter` |
| Message models | `messaging/models.py` | `Message`, `Conversation`, `Attachment` |
| Internal message bus | `messaging/bus.py` | `MessageBus` -- inter-agent communication |
| Device pairing | `messaging/pairing.py` | `PairingManager` |

---

## 10. Memory and RAG

| Core Spec | Engine Module | Key Classes / Functions |
|-----------|---------------|------------------------|
| Agent memory/state (CA-038) | `memory/` | Full memory package |
| Short-term (conversation) | `memory/short_term.py` | `ShortTermMemory` |
| Long-term (persistent) | `memory/long_term.py` | `LongTermMemory` |
| RAG retrieval | `memory/rag.py` | `RAGRetriever`, `RAGRetriever.query()` |
| Embeddings | `memory/embeddings.py` | `EmbeddingProvider`, `embed()` |
| Session state | `memory/session.py` | `SessionStore` |
| Context assembly | `memory/context.py` | `ContextBuilder` |
| Document ingestion | `memory/ingestion.py` | `DocumentIngester` |
| Retention policies | `memory/retention.py` | `RetentionPolicy`, `RetentionPolicy.enforce()` |

---

## 11. Testing

| Core Spec | Engine Module | Key Classes / Functions |
|-----------|---------------|------------------------|
| `core/orchestrator/testing/WORKFLOW_TESTING_FRAMEWORK.md` | `testing/` | Testing harnesses |
| Workflow testing | `testing/workflow_harness.py` | `WorkflowTestHarness` |
| Agent testing | `testing/agent_harness.py` | `AgentTestHarness` |
| Mock LLM for tests | `testing/mock_llm.py` | `MockLLM` -- deterministic responses for CI |

---

## 12. Plugins

| Core Spec | Engine Module | Key Classes / Functions |
|-----------|---------------|------------------------|
| `core/orchestrator/plugins/PLUGIN_REGISTRY_SPEC.md` | `plugins/loader.py` | `PluginLoader`, `PluginLoader.discover()`, `PluginLoader.load()` |

---

## 13. API Surface

| Concern | Engine Module | Key Classes / Functions |
|---------|---------------|------------------------|
| Health check | `api/routes/health.py` | `GET /health` |
| Chat / agent invoke | `api/routes/chat.py` | `POST /api/v1/chat` |
| Agent CRUD | `api/routes/agents.py` | Agent management endpoints |
| Workflow execution | `api/routes/workflows.py` | `POST /api/v1/workflows/run` |
| Auth endpoints | `api/routes/auth.py` | Login, token refresh |
| Dashboard | `api/routes/dashboard.py` | Metrics and health dashboard |
| Webhooks | `api/routes/webhooks.py` | Inbound webhook receiver |

---

## Cross-Reference: Multi-Role Workflow (Core) to Engine Execution

The core defines a Standard Implementation Flow (see `AGENT_ROUTING_MAP.md`):

```
Orchestrator -> Researcher -> Architect -> Implementer -> QA -> Reviewer -> Documentation
```

In the engine this becomes:

1. `WorkflowExecutor` loads a `WorkflowDefinition` (the plan).
2. `DAG.topological_sort()` determines step order.
3. Each step calls `AgentRuntime.run()` with the appropriate agent from `AgentRegistry`.
4. `LLMRouter` selects the LLM provider per agent constraints.
5. `WorkflowCheckpoint.save()` persists state after each step.
6. `LineageTracker` records decisions, reviews, and artifacts throughout.
7. `MetricsCollector` emits timing and cost data to the dashboard.
