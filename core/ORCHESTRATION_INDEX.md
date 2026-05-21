# Orchestration Index

This index connects the core orchestration system, AEP workflow, and reusable workflows.

## Model-Agnostic Principle
All guidance is written to be model-neutral. If a task requires a specific tool or model, document it in TASKS.

## Orchestration
- `core/orchestrator/README.md`
- `core/orchestrator/OPERATOR_MANUAL.md`
- `core/orchestrator/AGENT_ROUTING_MAP.md`
- `core/orchestrator/handoff/STATUS.md`
- `core/orchestrator/handoff/PLAN.md`
- `core/orchestrator/handoff/TASKS.md`
- `core/orchestrator/handoff/DEFINITION_OF_DONE.md`
- `core/orchestrator/handoff/REVIEW_CAPTURE.md`
- `core/orchestrator/handoff/REVIEW_CHECKLIST.md`
- `core/orchestrator/handoff/SESSION_WRAP.md`
- `core/orchestrator/handoff/PRIORITIES.md`

## Policy Pack
- `core/packs/policy-pack-v1/AGENTS.md`
- `core/packs/policy-pack-v1/ORCHESTRATION.md`
- `core/packs/policy-pack-v1/EVIDENCE.md`
- `core/packs/policy-pack-v1/RISK_TRIGGERS.md`
- `core/packs/policy-pack-v1/ACCEPTANCE_CHECKS.md`
- `core/packs/policy-pack-v1/PROMOTION_GUIDE.md`

## Modular Rules
- `core/packs/policy-pack-v1/rules/README.md`
- `core/packs/policy-pack-v1/rules/security.md`
- `core/packs/policy-pack-v1/rules/testing.md`
- `core/packs/policy-pack-v1/rules/git-workflow.md`
- `core/packs/policy-pack-v1/rules/coding-style.md`
- `core/packs/policy-pack-v1/rules/agents.md`
- `core/packs/policy-pack-v1/rules/patterns.md`
- `core/packs/policy-pack-v1/rules/performance.md`

## Tool Governance
- `core/orchestrator/TOOL_GOVERNANCE.md`
- `core/orchestrator/TOOLS_AS_CODE.md`
- `core/orchestrator/QWEN_CODE_TOOL_PROTOCOL.md`

## AEP Workflow
- `core/arch/workflow.md`
- `core/arch/templates.md`
- `core/arch/phase-planning.md`
- `core/arch/test-matrix.md`
- `core/arch/verification-log.md`

## Workflows
- `core/workflows/README.md`
- `core/workflows/PROMOTION_CRITERIA.md`
- `core/workflows/SOURCES_INDEX.md`

## Skills
- `core/workflows/skills/README.md`
- `core/workflows/skills/tdd-workflow.md`
- `core/workflows/skills/security-review.md`
- `core/workflows/skills/coding-standards.md`
- `core/workflows/skills/backend-patterns.md`

## Hooks
- `core/workflows/hooks/README.md`
- `core/workflows/hooks/HOOK_REGISTRY.md`
- `core/workflows/hooks/examples/evidence-capture-hook.md`
- `core/workflows/hooks/examples/pre-commit-security-hook.md`
- `core/workflows/hooks/examples/session-end-handoff-hook.md`
- `core/workflows/hooks/examples/scope-validation-hook.md`

## Agent Memory
- `core/agents/AGENT_MEMORY_PROTOCOL.md`
- `core/orchestrator/RELATIONSHIP_TYPES.md`
- `core/ARTIFACT_INDEX.md`

## Commands
- `core/workflows/commands/README.md`
- `core/workflows/commands/COMMAND_REGISTRY.md`
- `core/workflows/commands/status.md`
- `core/workflows/commands/tasks.md`
- `core/workflows/commands/verify.md`
- `core/workflows/commands/handoff.md`
- `core/workflows/commands/plan.md`
- `core/workflows/commands/review.md`
- `core/workflows/commands/tdd.md`
- `core/workflows/commands/build-fix.md`
- `core/workflows/commands/docs.md`
- `core/workflows/commands/e2e.md`
- `core/workflows/commands/refactor.md`

## Incremental Processing (CA-007)
- `core/orchestrator/incremental/README.md`
- `core/orchestrator/incremental/CHANGE_DETECTION.md`
- `core/orchestrator/incremental/ARTIFACT_GRAPH.md`

## Parallel Execution (CA-008)
- `core/orchestrator/parallel/README.md`
- `core/orchestrator/parallel/SEMAPHORE_CONTROL.md`
- `core/orchestrator/parallel/EXECUTION_MODES.md`

## Change Triggers (CA-009)
- `core/orchestrator/triggers/README.md`
- `core/orchestrator/triggers/TRIGGER_CATALOG.md`

## Configuration Schemas (CA-010)
- `core/schemas/README.md`
- `core/schemas/agent.schema.json`
- `core/schemas/workflow.schema.json`
- `core/schemas/orchestrator.schema.json`

## Execution Modes (CA-011)
- `core/orchestrator/modes/README.md`
- `core/orchestrator/modes/DRY_RUN_SPEC.md`

## MDC Rules (CA-012)
- `core/packs/mdc-rules/README.md`
- `core/packs/mdc-rules/orchestrator.mdc`
- `core/packs/mdc-rules/refinement.mdc`
- `core/packs/mdc-rules/evidence.mdc`

## Artifact Filtering (CA-013)
- `core/orchestrator/filters/README.md`
- `core/orchestrator/filters/GLOB_PATTERNS.md`

## Dependency Graph (CA-014)
- `core/orchestrator/dependencies/README.md`
- `core/orchestrator/dependencies/DEPENDENCY_GRAPH_SPEC.md`

## Analytics (CA-015)
- `core/orchestrator/analytics/README.md`
- `core/orchestrator/analytics/METRICS_CATALOG.md`

## Config Generation (CA-016)
- `core/orchestrator/config-gen/README.md`
- `core/orchestrator/config-gen/GENERATOR_SPEC.md`

## Platform Integrations (CA-017)
- `core/orchestrator/integrations/README.md`
- `core/orchestrator/integrations/CHANNEL_INTEGRATION_SPEC.md`
- `core/orchestrator/integrations/VOICE_MEDIA_SPEC.md`
- `core/orchestrator/integrations/CREDENTIAL_MANAGEMENT_SPEC.md`
- `core/orchestrator/integrations/PRIVACY_ARCHITECTURE.md`

## Competitive Features Index
- `core/orchestrator/COMPETITIVE_FEATURES_INDEX.md`

## Workflow Definitions (CA-018 to CA-030)
- `core/orchestrator/workflows/README.md`
- `core/orchestrator/workflows/ASSET_FIRST_WORKFLOW_SCHEMA.md`
- `core/orchestrator/workflows/DAG_EXECUTION_ENGINE.md`
- `core/orchestrator/workflows/EXPRESSION_LANGUAGE_SPEC.md`

## Agent Coordination (CA-031 to CA-040)
- `core/orchestrator/agent-protocols/AGENT_HANDOFF_PROTOCOL.md`
- `core/orchestrator/agent-protocols/COMMUNICATION_FLOW_SCHEMA.md`
- `core/orchestrator/agent-protocols/GUARDRAILS_VALIDATION_HOOKS.md`

## State Machines & Decision (CA-041 to CA-050)
- `core/orchestrator/statecharts/STATECHART_WORKFLOW_FORMAT.md`
- `core/orchestrator/statecharts/TASK_DEFINITION_REGISTRY.md`
- `core/orchestrator/statecharts/BACKPRESSURE_SPEC.md`
- `core/orchestrator/decision/DECISION_ROUTING_SPEC.md`

## Observability & Testing (CA-051 to CA-060)
- `core/orchestrator/lineage/LINEAGE_TRACKING_SPEC.md`
- `core/orchestrator/sensors/ARTIFACT_SENSOR_SPEC.md`
- `core/orchestrator/observability/HEALTH_DASHBOARD_SPEC.md`
- `core/orchestrator/testing/WORKFLOW_TESTING_FRAMEWORK.md`
- `core/orchestrator/plugins/PLUGIN_REGISTRY_SPEC.md`

## Distribution & Sync (Phase 9 / CA-061)
- `core/orchestrator/distribution/README.md`
- `core/orchestrator/distribution/DISTRIBUTION_SYNC_SPEC.md`

## Governance & Community (Phase 10 / CA-062)
- `core/orchestrator/community/README.md`
- `core/orchestrator/community/GOVERNANCE_COMMUNITY_SPEC.md`

## Research
- `core/research/06-SECURITY-ANALYSIS.md`
- `core/research/07-FEATURE-PARITY.md`

---

## Engine Implementation

The AGENT-33 engine (`engine/`) provides a working runtime implementation of the orchestration concepts defined in this index.

### Implementation Status

| Orchestration Concept | Engine Module | Status |
|---|---|---|
| Agent Definitions & Routing | `engine/src/agent33/agents/` | Implemented |
| Workflow DAG Engine | `engine/src/agent33/workflows/` | Implemented |
| Tool Governance | `engine/src/agent33/tools/` | Implemented |
| Security & Credentials | `engine/src/agent33/security/` | Implemented |
| Messaging Integrations | `engine/src/agent33/messaging/` | Implemented |
| Sensors & Triggers | `engine/src/agent33/automation/` | Implemented |
| Observability & Lineage | `engine/src/agent33/observability/` | Implemented |
| Memory & RAG | `engine/src/agent33/memory/` | Implemented |
| State Machines | `engine/src/agent33/workflows/state_machine.py` | Implemented |
| Plugin System | `engine/src/agent33/plugins/` | Implemented |

### Engine Documentation

- [Getting Started](../engine/docs/getting-started.md)
- [Architecture](../engine/docs/architecture.md)
- [API Reference](../engine/docs/api-reference.md)
- [Workflow Guide](../engine/docs/workflow-guide.md)
- [Agent Guide](../engine/docs/agent-guide.md)
- [Security Guide](../engine/docs/security-guide.md)
- [Integration Guide](../engine/docs/integration-guide.md)
- [CLI Reference](../engine/docs/cli-reference.md)
- [Use Cases](../engine/docs/use-cases.md)
- [Orchestration Mapping](../engine/docs/orchestration-mapping.md)
- [Feature Roadmap](../engine/docs/feature-roadmap.md)
