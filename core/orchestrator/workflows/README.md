# Workflow Specifications

Purpose: Canonical workflow definition specifications for AGENT-33 orchestration.

## Documents

| Document | Purpose |
|----------|---------|
| [ASSET_FIRST_WORKFLOW_SCHEMA.md](ASSET_FIRST_WORKFLOW_SCHEMA.md) | Asset-centric workflow definitions with lineage and freshness |
| [DAG_EXECUTION_ENGINE.md](DAG_EXECUTION_ENGINE.md) | DAG-based stage execution with fork-join and conditionals |
| [EXPRESSION_LANGUAGE_SPEC.md](EXPRESSION_LANGUAGE_SPEC.md) | Safe expression language for dynamic workflow behavior |

## Related
- `core/orchestrator/statecharts/` - State machine workflow format
- `core/orchestrator/agent-protocols/` - Agent coordination
- `core/orchestrator/decision/` - Decision routing
- `core/orchestrator/sensors/` - Event-driven triggers
