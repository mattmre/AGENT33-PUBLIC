# Competitive Features Index

Purpose: De-duplicated, consolidated index of all features adopted from competitive analysis of 12 orchestration frameworks. Maps each feature to its implementation specification.

Related docs:
- `docs/competitive-analysis/SUMMARY.md`
- `core/ORCHESTRATION_INDEX.md`

## Already Implemented (CA-007 to CA-017)

| ID | Feature | Source | Spec Location | Status |
|----|---------|--------|---------------|--------|
| CA-007 | Incremental Detection | Incrementalist | `orchestrator/incremental/` | ✅ Complete |
| CA-008 | Parallel Execution | Incrementalist | `orchestrator/parallel/` | ✅ Complete |
| CA-009 | Trigger Catalog | Incrementalist | `orchestrator/triggers/` | ✅ Complete |
| CA-010 | Configuration Schemas | Incrementalist | `schemas/` | ✅ Complete |
| CA-011 | Execution Modes | Incrementalist | `orchestrator/modes/` | ✅ Complete |
| CA-012 | MDC Rules | Incrementalist | `packs/mdc-rules/` | ✅ Complete |
| CA-013 | Artifact Filtering | Incrementalist | `orchestrator/filters/` | ✅ Complete |
| CA-014 | Dependency Graphs | Incrementalist | `orchestrator/dependencies/` | ✅ Complete |
| CA-015 | Analytics & Metrics | Incrementalist | `orchestrator/analytics/` | ✅ Complete |
| CA-016 | Config Generation | Incrementalist | `orchestrator/config-gen/` | ✅ Complete |
| CA-017 | Platform Integrations | External Platform | `orchestrator/integrations/` | ✅ Complete |

## Newly Implemented - De-duplicated Feature Clusters

### Cluster 1: Workflow Definition (CA-018 to CA-030)
Consolidated from: Netflix Conductor, Kestra, Dagster, Orca

| De-dup ID | Feature | Sources | Spec Location |
|-----------|---------|---------|---------------|
| CA-018 | Asset-First Workflow Schema | Dagster CA-119, Conductor CA-017 | `orchestrator/workflows/ASSET_FIRST_WORKFLOW_SCHEMA.md` |
| CA-019 | DAG-Based Stage Execution | Orca CA-107, Dagster CA-119, Kestra CA-041 | `orchestrator/workflows/DAG_EXECUTION_ENGINE.md` |
| CA-020 | Expression Language | Conductor CA-021, Orca CA-110, Camunda CA-057 | `orchestrator/workflows/EXPRESSION_LANGUAGE_SPEC.md` |
| CA-021 | Task Definition Registry | Conductor CA-018, Kestra CA-043 | `orchestrator/statecharts/TASK_DEFINITION_REGISTRY.md` |
| CA-022 | Dynamic Fork-Join | Conductor CA-023, Kestra CA-047, Orca CA-112 | Covered in DAG_EXECUTION_ENGINE.md |
| CA-023 | Freshness Policies | Dagster CA-122 | Covered in ASSET_FIRST_WORKFLOW_SCHEMA.md |
| CA-024 | Partition Definitions | Dagster CA-125 | Covered in ASSET_FIRST_WORKFLOW_SCHEMA.md |
| CA-025 | IO Manager Abstraction | Dagster CA-127 | Covered in ASSET_FIRST_WORKFLOW_SCHEMA.md |
| CA-026 | Pipeline Templates | Orca CA-115, Conductor CA-025 | Covered in DAG_EXECUTION_ENGINE.md |
| CA-027 | Sub-Workflow Composition | Conductor CA-024, Kestra CA-049 | Covered in DAG_EXECUTION_ENGINE.md |
| CA-028 | Conditional Branching | Conductor CA-022, Camunda CA-058 | Covered in DAG_EXECUTION_ENGINE.md |
| CA-029 | Event-Driven Triggers | Kestra CA-044, Conductor CA-026 | Covered in ARTIFACT_SENSOR_SPEC.md |
| CA-030 | Workflow Versioning | Kestra CA-050, Conductor CA-027 | Covered in TASK_DEFINITION_REGISTRY.md |

### Cluster 2: Agent Coordination (CA-031 to CA-040)
Consolidated from: OpenAI Swarm, Agency Swarm, wshobson/agents

| De-dup ID | Feature | Sources | Spec Location |
|-----------|---------|---------|---------------|
| CA-031 | Agent Handoff Protocol | Swarm CA-131, Agency CA-077, wshobson CA-029 | `orchestrator/agent-protocols/AGENT_HANDOFF_PROTOCOL.md` |
| CA-032 | Communication Flow Schema | Agency CA-082 | `orchestrator/agent-protocols/COMMUNICATION_FLOW_SCHEMA.md` |
| CA-033 | Guardrails/Validation Hooks | Agency CA-084, wshobson CA-035 | `orchestrator/agent-protocols/GUARDRAILS_VALIDATION_HOOKS.md` |
| CA-034 | Context Variables | Swarm CA-133, Agency CA-079 | Covered in AGENT_HANDOFF_PROTOCOL.md |
| CA-035 | Agent Discovery | Swarm CA-136, wshobson CA-031 | Covered in AGENT_REGISTRY.md (existing) |
| CA-036 | Delegation Patterns | Swarm CA-134, Agency CA-080 | Covered in AGENT_HANDOFF_PROTOCOL.md |
| CA-037 | Multi-Agent Routing | wshobson CA-033, Agency CA-081 | Covered in AGENT_ROUTING_MAP.md (existing) |
| CA-038 | Agent Memory/State | wshobson CA-037, Agency CA-086 | Covered in COMMUNICATION_FLOW_SCHEMA.md |
| CA-039 | Tool Sharing Between Agents | Swarm CA-138, wshobson CA-034 | Covered in TOOL_GOVERNANCE.md (existing) |
| CA-040 | Agent Lifecycle Management | Agency CA-088, wshobson CA-040 | Covered in GUARDRAILS_VALIDATION_HOOKS.md |

### Cluster 3: State Machines & Decision (CA-041 to CA-050)
Consolidated from: XState, Camunda, Osmedeus

| De-dup ID | Feature | Sources | Spec Location |
|-----------|---------|---------|---------------|
| CA-041 | Statechart Workflow Format | XState CA-065 | `orchestrator/statecharts/STATECHART_WORKFLOW_FORMAT.md` |
| CA-042 | Decision Routing | Osmedeus CA-093, Conductor CA-022, Camunda CA-058 | `orchestrator/decision/DECISION_ROUTING_SPEC.md` |
| CA-043 | Backpressure | Camunda CA-060, Kestra CA-048 | `orchestrator/statecharts/BACKPRESSURE_SPEC.md` |
| CA-044 | BPMN Process Modeling | Camunda CA-053 | Covered in STATECHART_WORKFLOW_FORMAT.md |
| CA-045 | Parallel Regions | XState CA-069 | Covered in STATECHART_WORKFLOW_FORMAT.md |
| CA-046 | History States | XState CA-071 | Covered in STATECHART_WORKFLOW_FORMAT.md |
| CA-047 | Machine Composition | XState CA-073 | Covered in STATECHART_WORKFLOW_FORMAT.md |
| CA-048 | Synthetic Stage Composition | Orca CA-113 | Covered in DAG_EXECUTION_ENGINE.md |
| CA-049 | Canary Execution | Orca CA-116 | Covered in DAG_EXECUTION_ENGINE.md |
| CA-050 | Timer/Delay Transitions | XState CA-070, Camunda CA-059 | Covered in STATECHART_WORKFLOW_FORMAT.md |

### Cluster 4: Observability & Testing (CA-051 to CA-060)
Consolidated from: Dagster, all tools

| De-dup ID | Feature | Sources | Spec Location |
|-----------|---------|---------|---------------|
| CA-051 | Lineage Tracking | Dagster CA-124 | `orchestrator/lineage/LINEAGE_TRACKING_SPEC.md` |
| CA-052 | Artifact Sensors | Dagster CA-123 | `orchestrator/sensors/ARTIFACT_SENSOR_SPEC.md` |
| CA-053 | Health Dashboard | Dagster CA-128 | `orchestrator/observability/HEALTH_DASHBOARD_SPEC.md` |
| CA-054 | Workflow Testing Framework | Dagster CA-126, XState CA-074 | `orchestrator/testing/WORKFLOW_TESTING_FRAMEWORK.md` |
| CA-055 | Plugin Registry | Osmedeus CA-089 | `orchestrator/plugins/PLUGIN_REGISTRY_SPEC.md` |
| CA-056 | Visual DAG Rendering | All tools | Covered in LINEAGE_TRACKING_SPEC.md |
| CA-057 | Execution Replay | Orca CA-117 | Covered in LINEAGE_TRACKING_SPEC.md |
| CA-058 | Model-Based Testing | XState CA-074 | Covered in WORKFLOW_TESTING_FRAMEWORK.md |
| CA-059 | Structured Event Logging | All tools | Covered in TRACE_SCHEMA.md (existing) |
| CA-060 | Cost Tracking | Dagster CA-129 | Covered in METRICS_CATALOG.md (existing) |

### Cluster 5: Distribution & Governance (CA-061 to CA-065)
New for AGENT-33

| De-dup ID | Feature | Sources | Spec Location |
|-----------|---------|---------|---------------|
| CA-061 | Distribution & Sync | Phase 9 | `orchestrator/distribution/DISTRIBUTION_SYNC_SPEC.md` |
| CA-062 | Community Governance | Phase 10 | `orchestrator/community/GOVERNANCE_COMMUNITY_SPEC.md` |
| CA-063 | Platform Integrations | External Platform CA-017 | `orchestrator/integrations/` (5 specs) |
| CA-064 | Security Analysis | External Platform | `research/06-SECURITY-ANALYSIS.md` |
| CA-065 | Feature Parity Analysis | External Platform | `research/07-FEATURE-PARITY.md` |

## De-duplication Summary

| Metric | Count |
|--------|-------|
| Raw features from 12 analyses | ~136 |
| After de-duplication | 65 unique features |
| Covered by existing specs | 12 (CA-007 to CA-017, plus existing AGENT_REGISTRY, TOOL_GOVERNANCE, etc.) |
| New specs created | 15 specification documents |
| Features per new spec (avg) | 3.5 (many features consolidated into comprehensive specs) |
